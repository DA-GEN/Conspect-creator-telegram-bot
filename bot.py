"""
Telegram-бот: скачивает аудио из видео (YouTube/TikTok/Instagram),
расшифровывает его в текст через Groq Whisper и по желанию делает
структурированный конспект через Groq LLM.

Используются только бесплатные технологии:
- aiogram 3.x (асинхронный Telegram-бот)
- yt-dlp (скачивание аудио)
- Groq Cloud API (free tier): whisper-large-v3 для STT, llama3-*-8192 для LLM
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import shutil
import tempfile
import uuid
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv
from groq import Groq
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# --------------------------------------------------------------------------
# Конфигурация
# --------------------------------------------------------------------------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Заполните .env (см. .env.example).")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY не найден. Заполните .env (см. .env.example).")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("video2text_bot")

STT_MODEL = "whisper-large-v3"
LLM_MODEL_PRIMARY = "llama3-70b-8192"
LLM_MODEL_FALLBACK = "llama3-8b-8192"

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # лимит free-тарифа Groq на размер аудиофайла
TELEGRAM_MSG_LIMIT = 4096
MAX_TRANSCRIPT_CHARS_FOR_LLM = 15000  # защита от переполнения контекстного окна модели

URL_REGEX = re.compile(r"https?://[^\s]+", re.IGNORECASE)

SUMMARY_PROMPT = (
    "Сделай подробный, структурированный конспект следующего текста. "
    "Выдели главные мысли, используй списки.\n\nТекст:\n{text}"
)

DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

router = Router()
groq_client = Groq(api_key=GROQ_API_KEY)

# token -> url. Используется, чтобы прокинуть длинную ссылку через
# callback_data, у которого жёсткий лимит в 64 байта.
pending_links: Dict[str, str] = {}


# --------------------------------------------------------------------------
# Вспомогательные функции
# --------------------------------------------------------------------------


def build_choice_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Только текст", callback_data=f"text:{token}"),
                InlineKeyboardButton(text="📋 Сделать конспект", callback_data=f"summary:{token}"),
            ]
        ]
    )


def split_text(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> List[str]:
    """Режет текст на части не длиннее лимита Telegram, стараясь резать по границам строк/слов."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    return chunks


def download_audio_sync(url: str, out_dir: str) -> str:
    """
    Скачивает только аудиодорожку через yt-dlp (без ffmpeg-конвертации).
    Выполняется в отдельном потоке, т.к. yt-dlp синхронный и блокирующий.
    """
    ydl_opts = {
        # Предпочитаем m4a (как просили), иначе — любой лучший аудиопоток,
        # и только если у платформы нет отдельного аудиопотока (характерно
        # для некоторых TikTok/Instagram роликов) — берём "best" целиком.
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "retries": 3,
        "socket_timeout": 30,
        "http_headers": {"User-Agent": DOWNLOAD_USER_AGENT},
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    if os.path.exists(filename):
        return filename

    # На случай если yt-dlp изменил расширение (например, после merge)
    candidates = glob.glob(os.path.join(out_dir, "*"))
    if candidates:
        return candidates[0]

    raise FileNotFoundError("yt-dlp не вернул файл после скачивания")


def transcribe_audio_sync(file_path: str) -> str:
    """Отправляет аудиофайл в Groq Whisper и возвращает распознанный текст."""
    with open(file_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            file=(os.path.basename(file_path), audio_file.read()),
            model=STT_MODEL,
        )
    return (transcription.text or "").strip()


def summarize_text_sync(text: str) -> str:
    """Просит LLM Groq сделать структурированный конспект. При недоступности
    основной модели пробует запасную, чтобы не падать из-за деприкейта модели."""
    truncated = text[:MAX_TRANSCRIPT_CHARS_FOR_LLM]
    prompt = SUMMARY_PROMPT.format(text=truncated)

    last_error: Optional[Exception] = None
    for model in (LLM_MODEL_PRIMARY, LLM_MODEL_FALLBACK):
        try:
            completion = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return completion.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001 — специально широкий catch, есть fallback-модель
            last_error = exc
            logger.warning("Модель %s не сработала: %s", model, exc)

    raise RuntimeError(f"Не удалось получить конспект от Groq: {last_error}")


# --------------------------------------------------------------------------
# Хендлеры
# --------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет! Пришли мне ссылку на видео (YouTube, TikTok, Instagram) — "
        "я расшифрую его в текст или сделаю конспект.\n\n"
        "Просто вставь ссылку в чат."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Отправь ссылку на видео с YouTube, TikTok или Instagram.\n"
        "Я предложу расшифровать аудио в текст или сразу сделать конспект."
    )


@router.message(F.text)
async def handle_link(message: Message) -> None:
    text = (message.text or "").strip()
    match = URL_REGEX.search(text)

    if not match:
        await message.answer(
            "❗ Это не похоже на ссылку. Пришли, пожалуйста, прямую ссылку на видео "
            "(YouTube, TikTok или Instagram)."
        )
        return

    url = match.group(0)
    token = uuid.uuid4().hex[:16]
    pending_links[token] = url

    await message.answer(
        "Что сделать с этим видео?",
        reply_markup=build_choice_keyboard(token),
    )


@router.callback_query(F.data.startswith("text:") | F.data.startswith("summary:"))
async def handle_choice(callback: CallbackQuery) -> None:
    await callback.answer()

    if not callback.data or not isinstance(callback.message, Message):
        return

    mode, token = callback.data.split(":", 1)
    url = pending_links.pop(token, None)

    status_message = callback.message

    if not url:
        await status_message.edit_text("⚠️ Ссылка устарела или уже обработана. Пришлите её ещё раз.")
        return

    await status_message.edit_text("⏳ Скачиваю аудио...")

    tmp_dir = tempfile.mkdtemp(prefix="tgbot_audio_")

    try:
        try:
            audio_path = await asyncio.to_thread(download_audio_sync, url, tmp_dir)
        except DownloadError as exc:
            logger.error("yt-dlp не смог скачать %s: %s", url, exc)
            await status_message.edit_text(
                "❌ Не удалось скачать аудио по этой ссылке. Возможно, видео приватное, "
                "удалено или платформа временно заблокировала запрос."
            )
            return
        except Exception:  # noqa: BLE001 — не должны падать из-за сети/провайдера
            logger.exception("Неожиданная ошибка при скачивании %s", url)
            await status_message.edit_text("❌ Не удалось скачать видео из-за непредвиденной ошибки.")
            return

        try:
            file_size = os.path.getsize(audio_path)
        except OSError:
            logger.exception("Не удалось получить размер файла %s", audio_path)
            await status_message.edit_text("❌ Ошибка чтения скачанного файла.")
            return

        logger.info("Скачано %s (%.2f МБ)", audio_path, file_size / 1024 / 1024)

        if file_size > MAX_AUDIO_BYTES:
            await status_message.edit_text(
                "❌ Аудиодорожка слишком большая (более 25 МБ) — бесплатный тариф "
                "Groq не сможет её обработать. Попробуй видео покороче."
            )
            return

        await status_message.edit_text("⏳ Расшифровываю аудио...")

        try:
            transcript = await asyncio.to_thread(transcribe_audio_sync, audio_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка транскрибации Groq Whisper")
            await status_message.edit_text(f"❌ Не удалось распознать речь: {exc}")
            return

        if not transcript:
            await status_message.edit_text("⚠️ Не удалось извлечь текст из аудио (пустой результат).")
            return

        if mode == "text":
            await status_message.edit_text("✅ Готово! Отправляю текст...")
            for chunk in split_text(transcript):
                await status_message.answer(chunk)
            return

        # mode == "summary"
        await status_message.edit_text("⏳ Готовлю конспект...")
        try:
            summary = await asyncio.to_thread(summarize_text_sync, transcript)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка создания конспекта через Groq LLM")
            await status_message.edit_text(
                f"❌ Не удалось создать конспект: {exc}\n\nВот расшифровка целиком:"
            )
            for chunk in split_text(transcript):
                await status_message.answer(chunk)
            return

        await status_message.edit_text("✅ Конспект готов!")
        for chunk in split_text(summary):
            await status_message.answer(chunk)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info("Временная папка %s удалена", tmp_dir)


# --------------------------------------------------------------------------
# Точка входа
# --------------------------------------------------------------------------


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Бот запущен, начинаю polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
