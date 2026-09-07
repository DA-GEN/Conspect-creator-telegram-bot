"""Мелкие утилиты для работы с Telegram API."""

from typing import List

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

# У Telegram жёсткий лимит 4096 символов на текст сообщения; берём с запасом,
# чтобы не упереться в него на пограничных случаях (эмодзи, форматирование).
TELEGRAM_MESSAGE_LIMIT = 4000


async def safe_edit_text(message: Message, text: str) -> None:
    """edit_text, который не падает, если Telegram отказывает с "message is
    not modified" (новый текст статуса совпал с текущим — например, если
    первый статус-колбэк дублирует текст только что отправленного сообщения)."""
    try:
        await message.edit_text(text)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """Режет длинный текст на части не длиннее limit — иначе Telegram просто
    отклонит сообщение (message is too long). Старается резать по границам
    строк, потом слов, и только в крайнем случае — посередине."""
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
