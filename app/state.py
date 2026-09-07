"""In-memory состояние бота: активные чаты, проекты, кэш контекста для чата."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

# token -> {"content": ..., "title": ..., "created_at": time.time()} — TTL
# чистится в app.keyboards.register_chat_context.
chat_contexts: Dict[str, Dict[str, object]] = {}

# chat_id -> активная сессия чата: {"content": ..., "title": ..., "history": [...]}
active_chats: Dict[int, Dict[str, object]] = {}

# chat_id -> список ссылок в незавершённом проекте
active_projects: Dict[int, List[str]] = {}

# url -> (timestamp, VideoResult) — чтобы повторная присылка той же ссылки в
# течение URL_CACHE_TTL_SECONDS не гоняла скачивание/распознавание заново.
# "VideoResult" в кавычках, т.к. класс объявлен ниже в этом же модуле.
url_result_cache: Dict[str, Tuple[float, "VideoResult"]] = {}


@dataclass
class VideoResult:
    """Результат сбора данных по одному видео: либо есть материал для
    конспекта (combined_text), либо описание ошибки (error) — не оба сразу."""

    url: str
    combined_text: str = ""
    is_slideshow: bool = False
    error: Optional[str] = None


StatusCallback = Optional[Callable[[str], Awaitable[None]]]
