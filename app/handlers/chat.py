"""Чат-режим: ответы на вопросы по сохранённому конспекту/расшифровке."""

import asyncio
import logging
from typing import Dict, List

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import MAX_CHAT_HISTORY_MESSAGES
from app.groq_client import chat_answer_sync
from app.state import active_chats, chat_contexts
from app.tg_utils import split_for_telegram

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("endchat"))
async def cmd_endchat(message: Message) -> None:
    if active_chats.pop(message.chat.id, None) is not None:
        await message.answer("👋 Чат завершён.")
    else:
        await message.answer("Активного чата сейчас нет.")


async def handle_chat_question(message: Message, question: str) -> None:
    session = active_chats[message.chat.id]
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        answer = await asyncio.to_thread(
            chat_answer_sync, session["content"], session["history"], question
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка чата с Groq")
        await message.answer(f"❌ Не удалось получить ответ: {exc}")
        return

    history: List[Dict[str, str]] = session["history"]
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    del history[:-MAX_CHAT_HISTORY_MESSAGES]

    for chunk in split_for_telegram(answer):
        await message.answer(chunk)


@router.callback_query(F.data.startswith("chat:"))
async def handle_start_chat(callback: CallbackQuery) -> None:
    await callback.answer()

    if not callback.data or not isinstance(callback.message, Message):
        return

    _, token = callback.data.split(":", 1)
    ctx = chat_contexts.get(token)
    status_message = callback.message

    if not ctx:
        await status_message.answer("⚠️ Контекст устарел. Сделай расшифровку/конспект заново.")
        return

    active_chats[status_message.chat.id] = {
        "content": ctx["content"],
        "title": ctx["title"],
        "history": [],
    }
    await status_message.answer(
        f"💬 Режим чата активирован — задавай вопросы по {ctx['title']}.\n"
        "Чтобы выйти, отправь /endchat."
    )
