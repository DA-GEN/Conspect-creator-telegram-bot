"""In-memory состояние бота: активные чаты, проекты, кэш контекста для чата."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# token -> {"content": ..., "title": ..., "created_at": time.time()} — TTL
# чистится в app.keyboards.register_chat_context.
chat_contexts: dict[str, dict[str, object]] = {}

# chat_id -> активная сессия чата: {"content": ..., "title": ..., "history": [...]}
active_chats: dict[int, dict[str, object]] = {}

# chat_id -> список ссылок в незавершённом проекте
active_projects: dict[int, list[str]] = {}

# url -> (timestamp, VideoResult) — чтобы повторная присылка той же ссылки в
# течение URL_CACHE_TTL_SECONDS не гоняла скачивание/распознавание заново.
# "VideoResult" в кавычках, т.к. класс объявлен ниже в этом же модуле.
url_result_cache: dict[str, tuple[float, "VideoResult"]] = {}


@dataclass
class VideoResult:
    """Результат сбора данных по одному видео: либо есть материал для
    конспекта (combined_text), либо описание ошибки (error) — не оба сразу."""

    url: str
    combined_text: str = ""
    is_slideshow: bool = False
    error: str | None = None


StatusCallback = Callable[[str], Awaitable[None]] | None
