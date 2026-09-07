"""Inline-клавиатуры и регистрация контекста для чат-режима."""

import time
import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import CHAT_CONTEXT_TTL_SECONDS
from app.state import chat_contexts


def build_chat_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Начать чат", callback_data=f"chat:{token}")]]
    )


def _prune_expired_contexts() -> None:
    """chat_contexts иначе растёт бесконечно — по токену на каждый
    обработанный конспект/расшифровку, без TTL это утечка памяти."""
    now = time.time()
    expired = [token for token, ctx in chat_contexts.items() if now - ctx["created_at"] > CHAT_CONTEXT_TTL_SECONDS]
    for token in expired:
        chat_contexts.pop(token, None)


def register_chat_context(content: str, title: str) -> InlineKeyboardMarkup:
    """Сохраняет текст-контекст под токеном и возвращает клавиатуру с кнопкой чата по нему."""
    _prune_expired_contexts()
    token = uuid.uuid4().hex[:16]
    chat_contexts[token] = {"content": content, "title": title, "created_at": time.time()}
    return build_chat_keyboard(token)
