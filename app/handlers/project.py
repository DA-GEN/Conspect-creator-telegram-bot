"""Команды проекта: /newproject /cancelproject /finishproject и обработка
всех видео проекта в один общий конспект."""

import asyncio
import logging
import shutil
import tempfile
import uuid
from typing import List

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from app.config import MAX_CHARS_PER_VIDEO_IN_PROJECT, MAX_PROJECT_VIDEOS, PROJECT_CONCURRENCY
from app.files import write_result_file
from app.groq_client import summarize_project_sync
from app.keyboards import register_chat_context
from app.state import VideoResult, active_projects
from app.tg_utils import safe_edit_text
from app.video_pipeline import gather_video_data

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("newproject"))
async def cmd_newproject(message: Message) -> None:
    chat_id = message.chat.id
    if chat_id in active_projects:
        await message.answer(
            f"У тебя уже есть незавершённый проект ({len(active_projects[chat_id])} ссылок). "
            "Пришли ещё ссылки, заверши его — /finishproject, либо отмени — /cancelproject."
        )
        return

    active_projects[chat_id] = []
    await message.answer(
        "📁 Новый проект начат. Присылай ссылки на видео — по одной в сообщении "
        "или несколько сразу, можно в разных сообщениях. Когда закончишь — "
        "отправь /finishproject (или /cancelproject, чтобы отменить)."
    )


@router.message(Command("cancelproject"))
async def cmd_cancelproject(message: Message) -> None:
    if active_projects.pop(message.chat.id, None) is not None:
        await message.answer("🗑 Проект отменён.")
    else:
        await message.answer("Активного проекта сейчас нет.")


@router.message(Command("finishproject"))
async def cmd_finishproject(message: Message) -> None:
    chat_id = message.chat.id
    urls = active_projects.pop(chat_id, None)

    if not urls:
        await message.answer("Активного проекта нет или в нём нет ссылок. Начни новый — /newproject.")
        return

    await process_project(message, urls)


async def process_project(message: Message, urls: List[str]) -> None:
    """Обрабатывает все ссылки проекта и присылает один общий конспект,
    сгруппированный ИИ по темам видео. Видео обрабатываются параллельно (с
    ограничением PROJECT_CONCURRENCY, чтобы не словить rate limit Groq разом) —
    при 10+ видео это сильно быстрее последовательной обработки."""
    urls = urls[:MAX_PROJECT_VIDEOS]
    status_message = await message.answer(f"📁 Обрабатываю проект (0/{len(urls)} видео)...")

    semaphore = asyncio.Semaphore(PROJECT_CONCURRENCY)
    done_count = 0

    async def process_one(url: str) -> VideoResult:
        nonlocal done_count
        async with semaphore:
            result = await gather_video_data(url)
        done_count += 1
        await safe_edit_text(status_message, f"📁 Обрабатываю проект ({done_count}/{len(urls)} видео)...")
        return result

    # gather сохраняет порядок результатов по порядку corutin на входе, а не по
    # порядку завершения — нумерация "Видео N" ниже остаётся стабильной.
    results: List[VideoResult] = await asyncio.gather(*(process_one(url) for url in urls))

    if not any(r.combined_text for r in results):
        await safe_edit_text(status_message, "❌ Не удалось обработать ни одно видео из проекта.")
        return

    await safe_edit_text(status_message, "⏳ Группирую по темам и готовлю общий конспект...")

    materials_parts = []
    for i, r in enumerate(results, start=1):
        if r.error:
            materials_parts.append(f"### Видео {i} ({r.url})\nОшибка обработки: {r.error}")
        else:
            materials_parts.append(f"### Видео {i} ({r.url})\n{r.combined_text[:MAX_CHARS_PER_VIDEO_IN_PROJECT]}")
    materials = "\n\n".join(materials_parts)

    try:
        project_summary = await asyncio.to_thread(summarize_project_sync, materials)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка создания конспекта проекта через Groq LLM")
        await safe_edit_text(status_message, f"❌ Не удалось создать общий конспект: {exc}")
        return

    tmp_dir = tempfile.mkdtemp(prefix="tgbot_project_")
    try:
        sources_list = "\n".join(
            f"{i}. {r.url}" + (f" — ⚠️ {r.error}" if r.error else "") for i, r in enumerate(results, start=1)
        )
        result_filename = f"project_{uuid.uuid4().hex[:6]}.md"
        result_path = write_result_file(
            tmp_dir, result_filename, "Конспект проекта", "",
            [("Источники", sources_list), ("Конспект", project_summary)],
        )
        await safe_edit_text(status_message, "✅ Конспект проекта готов! Отправляю файл...")
        keyboard = register_chat_context(project_summary, "этому проекту")
        await status_message.answer_document(FSInputFile(result_path), reply_markup=keyboard)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
