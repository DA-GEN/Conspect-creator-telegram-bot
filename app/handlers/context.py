"""Команда /context: ответ по видео на конкретный запрос пользователя,
а не общий структурированный конспект.

Пример: /context напиши список osint инструментов и их возможностей <ссылка>
"""

import asyncio
import logging
import shutil
import tempfile

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

from app.config import URL_REGEX
from app.files import build_result_filename, write_result_file
from app.groq_client import answer_context_query_sync
from app.keyboards import register_chat_context
from app.tg_utils import safe_edit_text
from app.video_pipeline import gather_video_data

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("context"))
async def cmd_context(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    if not args:
        await message.answer(
            "Использование:\n<code>/context &lt;что нужно найти или сделать&gt; &lt;ссылка на видео&gt;</code>\n\n"
            "Например:\n<code>/context напиши список OSINT-инструментов и их "
            "возможностей https://...</code>\n\n"
            "В отличие от обычного конспекта, бот ответит именно на твой запрос, без лишнего.",
            parse_mode="HTML",
        )
        return

    match = URL_REGEX.search(args)
    if not match:
        await message.answer("❗ Не нашёл ссылку на видео в сообщении. Формат:\n/context <запрос> <ссылка на видео>")
        return

    url = match.group(0)
    instruction = (args[: match.start()] + args[match.end() :]).strip(" \n-—:")
    if not instruction:
        await message.answer("Напиши, что именно нужно найти или сделать, кроме самой ссылки.")
        return

    await process_context_query(message, url, instruction)


async def process_context_query(message: Message, url: str, instruction: str) -> None:
    status_message = await message.answer("⏳ Начинаю обработку...")

    async def on_status(text: str) -> None:
        await safe_edit_text(status_message, text)

    result = await gather_video_data(url, on_status)

    if result.error:
        await safe_edit_text(status_message, f"❌ Не удалось обработать видео: {result.error}.")
        return

    await safe_edit_text(status_message, "⏳ Готовлю ответ на запрос...")
    try:
        answer = await asyncio.to_thread(answer_context_query_sync, instruction, result.combined_text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка ответа на запрос через Groq LLM")
        await safe_edit_text(status_message, f"❌ Не удалось получить ответ: {exc}")
        return

    tmp_dir = tempfile.mkdtemp(prefix="tgbot_context_")
    try:
        await safe_edit_text(status_message, "✅ Готово! Отправляю файл...")
        result_filename = build_result_filename(url)
        result_path = write_result_file(
            tmp_dir,
            result_filename,
            f"Запрос: {instruction}",
            url,
            [("Ответ", answer)],
        )
        keyboard = register_chat_context(
            f"Запрос пользователя: {instruction}\n\nОтвет:\n{answer}\n\n{result.combined_text}",
            "этому запросу",
        )
        await status_message.answer_document(FSInputFile(result_path), reply_markup=keyboard)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
