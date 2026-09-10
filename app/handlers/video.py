"""Обработка обычных текстовых сообщений: одиночные ссылки на видео,
добавление ссылок в проект, вопросы в чат-режиме (иначе)."""

import asyncio
import logging
import shutil
import tempfile

from aiogram import F, Router
from aiogram.types import FSInputFile, Message

from app.config import MAX_PROJECT_VIDEOS, URL_REGEX
from app.files import build_result_filename, write_result_file
from app.groq_client import summarize_text_sync
from app.handlers.chat import handle_chat_question
from app.keyboards import register_chat_context
from app.state import active_chats, active_projects
from app.tg_utils import safe_edit_text
from app.video_pipeline import gather_video_data

logger = logging.getLogger(__name__)

router = Router()


async def process_single_video(message: Message, url: str) -> None:
    """Обрабатывает одну ссылку вне проекта: скачивание → расшифровка/анализ →
    конспект → файл с кнопкой чата."""
    status_message = await message.answer("⏳ Начинаю обработку...")

    async def on_status(text: str) -> None:
        await safe_edit_text(status_message, text)

    result = await gather_video_data(url, on_status)

    if result.error:
        await safe_edit_text(status_message, f"❌ Не удалось обработать видео: {result.error}.")
        return

    tmp_dir = tempfile.mkdtemp(prefix="tgbot_result_")
    try:
        result_filename = build_result_filename(url)

        if result.is_slideshow:
            # Слайдшоу из нескольких фото: аудио — обычно просто музыка, отдельный
            # проход через LLM-конспект тут не нужен — самих слайдов достаточно.
            await safe_edit_text(status_message, "✅ Готово! Отправляю файл...")
            result_path = write_result_file(
                tmp_dir,
                result_filename,
                "Визуальное описание",
                url,
                [("Визуальное описание", result.combined_text)],
            )
            keyboard = register_chat_context(result.combined_text, "этому описанию")
            await status_message.answer_document(FSInputFile(result_path), reply_markup=keyboard)
            return

        await safe_edit_text(status_message, "⏳ Готовлю конспект...")
        try:
            summary = await asyncio.to_thread(summarize_text_sync, result.combined_text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка создания конспекта через Groq LLM")
            result_path = write_result_file(
                tmp_dir,
                result_filename,
                "Материал",
                url,
                [("Материал", result.combined_text)],
            )
            keyboard = register_chat_context(result.combined_text, "этому материалу")
            await safe_edit_text(
                status_message, f"❌ Не удалось создать конспект: {exc}\n\nВот необработанный материал:"
            )
            await status_message.answer_document(FSInputFile(result_path), reply_markup=keyboard)
            return

        await safe_edit_text(status_message, "✅ Конспект готов! Отправляю файл...")
        result_path = write_result_file(tmp_dir, result_filename, "Конспект", url, [("Конспект", summary)])
        keyboard = register_chat_context(f"Конспект:\n{summary}\n\n{result.combined_text}", "этому конспекту")
        await status_message.answer_document(FSInputFile(result_path), reply_markup=keyboard)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.message(F.text)
async def handle_link(message: Message) -> None:
    text = (message.text or "").strip()
    chat_id = message.chat.id

    if chat_id in active_chats:
        if URL_REGEX.search(text):
            active_chats.pop(chat_id, None)  # новая ссылка — выходим из режима чата
        else:
            await handle_chat_question(message, text)
            return

    urls = URL_REGEX.findall(text)

    if chat_id in active_projects:
        if not urls:
            await message.answer(
                f"Пришли ссылку на видео (в проекте сейчас {len(active_projects[chat_id])}), "
                "или /finishproject, чтобы завершить, либо /cancelproject."
            )
            return
        project = active_projects[chat_id]
        room_left = MAX_PROJECT_VIDEOS - len(project)
        added, skipped = urls[:room_left], urls[room_left:]
        project.extend(added)
        note = f" ({len(skipped)} проигнорировано — достигнут лимит {MAX_PROJECT_VIDEOS})" if skipped else ""
        await message.answer(
            f"➕ Добавлено ссылок: {len(added)}{note}. Всего в проекте: {len(project)}. "
            "Когда закончишь — /finishproject."
        )
        return

    if not urls:
        await message.answer(
            "❗ Это не похоже на ссылку. Пришли, пожалуйста, прямую ссылку на видео (YouTube, TikTok или Instagram)."
        )
        return

    if len(urls) > 1:
        await message.answer(
            f"Замечено ссылок: {len(urls)} — обработаю только первую. Чтобы получить общий "
            "конспект сразу по нескольким видео, начни проект: /newproject"
        )

    await process_single_video(message, urls[0])
