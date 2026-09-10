"""Мок-тесты для базовых хендлеров: /start и /help не делают сетевых
вызовов, поэтому Message достаточно замокать — реальный объект aiogram не
нужен."""

from unittest.mock import AsyncMock

from app.handlers.basic import cmd_help, cmd_start


async def test_cmd_start_sends_welcome_message():
    message = AsyncMock()

    await cmd_start(message)

    message.answer.assert_awaited_once()
    (text,), _kwargs = message.answer.call_args
    assert "Привет" in text
    assert "/newproject" in text


async def test_cmd_help_sends_html_formatted_help():
    message = AsyncMock()

    await cmd_help(message)

    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert kwargs.get("parse_mode") == "HTML"
    assert "/context" in text
    assert "/endchat" in text
