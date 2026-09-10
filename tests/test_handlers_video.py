"""Мок-тесты для хендлера ссылок (app.handlers.video.handle_link):
- мусорный текст без ссылки отклоняется без сетевых вызовов;
- валидная ссылка запускает пайплайн (gather_video_data замокан — реальных
  скачиваний и вызовов Groq в тестах быть не должно)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.handlers.video import handle_link
from app.state import VideoResult, active_chats, active_projects


@pytest.fixture(autouse=True)
def _clean_module_state():
    """active_chats/active_projects — общие для процесса dict'ы, чистим
    вокруг каждого теста, чтобы тесты не влияли друг на друга."""
    active_chats.clear()
    active_projects.clear()
    yield
    active_chats.clear()
    active_projects.clear()


def _make_message(text: str, chat_id: int = 1) -> AsyncMock:
    message = AsyncMock()
    message.text = text
    message.chat.id = chat_id
    return message


async def test_handle_link_rejects_text_without_url():
    message = _make_message("просто текст без ссылки")

    await handle_link(message)

    message.answer.assert_awaited_once()
    (text,), _ = message.answer.call_args
    assert "не похоже на ссылку" in text


async def test_handle_link_ignores_non_http_scheme():
    message = _make_message("ftp://example.com/file.mp4")

    await handle_link(message)

    (text,), _ = message.answer.call_args
    assert "не похоже на ссылку" in text


async def test_handle_link_runs_pipeline_for_valid_url_and_reports_error():
    message = _make_message("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    status_message = AsyncMock()
    message.answer.return_value = status_message

    async def fake_gather(url, on_status):
        return VideoResult(url=url, error="видео недоступно")

    with patch("app.handlers.video.gather_video_data", side_effect=fake_gather) as mocked:
        await handle_link(message)

    mocked.assert_awaited_once()
    status_message.edit_text.assert_awaited()
    (text,), _ = status_message.edit_text.call_args
    assert "видео недоступно" in text


async def test_handle_link_adds_url_to_active_project_instead_of_processing():
    chat_id = 7
    active_projects[chat_id] = []
    message = _make_message("https://youtu.be/aaa", chat_id=chat_id)

    with patch("app.handlers.video.gather_video_data") as mocked:
        await handle_link(message)

    mocked.assert_not_called()
    assert active_projects[chat_id] == ["https://youtu.be/aaa"]
    message.answer.assert_awaited_once()
