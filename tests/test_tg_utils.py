"""Тесты для мелких Telegram-утилит: safe_edit_text и split_for_telegram."""

from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest

from app.tg_utils import TELEGRAM_MESSAGE_LIMIT, safe_edit_text, split_for_telegram


def test_split_for_telegram_returns_single_chunk_for_short_text():
    assert split_for_telegram("короткий текст") == ["короткий текст"]


def test_split_for_telegram_splits_long_text_on_newline_boundary():
    line = "а" * 100
    text = "\n".join([line] * 50)  # заведомо длиннее лимита
    chunks = split_for_telegram(text, limit=210)

    assert len(chunks) > 1
    assert all(len(chunk) <= 210 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_split_for_telegram_respects_default_limit():
    text = "x" * (TELEGRAM_MESSAGE_LIMIT * 2)
    chunks = split_for_telegram(text)
    assert all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) == len(text)


async def test_safe_edit_text_calls_edit_text():
    message = AsyncMock()

    await safe_edit_text(message, "новый текст")

    message.edit_text.assert_awaited_once_with("новый текст")


async def test_safe_edit_text_swallows_not_modified_error():
    message = AsyncMock()
    message.edit_text.side_effect = TelegramBadRequest(
        method=AsyncMock(), message="Bad Request: message is not modified"
    )

    await safe_edit_text(message, "тот же текст")  # не должно бросить исключение


async def test_safe_edit_text_reraises_other_errors():
    message = AsyncMock()
    message.edit_text.side_effect = TelegramBadRequest(method=AsyncMock(), message="Bad Request: chat not found")

    try:
        await safe_edit_text(message, "текст")
    except TelegramBadRequest:
        pass
    else:
        raise AssertionError("ожидали, что исключение пробросится дальше")
