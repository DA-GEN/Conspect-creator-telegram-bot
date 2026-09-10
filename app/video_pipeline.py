"""Общий пайплайн сбора данных по одному видео: скачивание → расшифровка →
визуальный анализ. Используется и для одиночных ссылок, и для видео внутри
проекта."""

import asyncio
import logging
import os
import shutil
import tempfile
import time

from yt_dlp.utils import DownloadError

from app.config import MAX_AUDIO_BYTES, TIKTOK_PHOTO_URL_REGEX, URL_CACHE_TTL_SECONDS
from app.downloader import download_media_sync
from app.groq_client import analyze_images_sync, build_combined_text, is_no_visual_info, transcribe_audio_sync
from app.state import StatusCallback, VideoResult, url_result_cache

logger = logging.getLogger(__name__)


def _prune_expired_cache() -> None:
    now = time.time()
    expired = [u for u, (ts, _) in url_result_cache.items() if now - ts > URL_CACHE_TTL_SECONDS]
    for u in expired:
        url_result_cache.pop(u, None)


async def gather_video_data(url: str, on_status: StatusCallback = None) -> VideoResult:
    """
    Скачивает видео/слайдшоу, расшифровывает аудио и анализирует кадры/фото —
    общий пайплайн, используемый и для одиночных ссылок, и для видео внутри
    проекта. on_status — необязательный колбэк для промежуточных статусов
    (для проекта, где не нужен статус на каждое видео, можно не передавать).

    Успешный результат кэшируется на URL_CACHE_TTL_SECONDS: если та же ссылка
    прилетит ещё раз (повторно в чат, в новый проект и т.п.), не гоняем весь
    пайплайн заново. Ошибки не кэшируются — они могут быть временными (сеть,
    rate limit).
    """
    _prune_expired_cache()
    cached = url_result_cache.get(url)
    if cached and time.time() - cached[0] < URL_CACHE_TTL_SECONDS:
        logger.info("Кэш: результат для %s уже есть, пропускаю обработку", url)
        return cached[1]

    async def status(text: str) -> None:
        if on_status:
            await on_status(text)

    tmp_dir = tempfile.mkdtemp(prefix="tgbot_media_")
    try:
        await status("⏳ Скачиваю видео...")
        try:
            media = await asyncio.to_thread(download_media_sync, url, tmp_dir)
        except DownloadError as exc:
            logger.error("yt-dlp не смог скачать %s: %s", url, exc)
            if TIKTOK_PHOTO_URL_REGEX.search(str(exc)):
                return VideoResult(
                    url=url, error="не удалось получить фото из TikTok-слайдшоу (не сработал и запасной способ)"
                )
            return VideoResult(
                url=url, error="не удалось скачать (приватное, удалено или платформа заблокировала запрос)"
            )
        except Exception:  # noqa: BLE001 — не должны падать из-за сети/провайдера
            logger.exception("Неожиданная ошибка при скачивании %s", url)
            return VideoResult(url=url, error="непредвиденная ошибка при скачивании")

        audio_path: str | None = media["audio_path"]
        image_paths: list[str] = media["image_paths"]
        is_slideshow: bool = media.get("is_slideshow", False)

        if not audio_path and not image_paths:
            return VideoResult(url=url, error="не удалось получить ни аудио, ни изображение")

        if audio_path:
            try:
                file_size = os.path.getsize(audio_path)
            except OSError:
                logger.exception("Не удалось получить размер файла %s", audio_path)
                file_size = 0
                audio_path = None

            if audio_path and file_size > MAX_AUDIO_BYTES:
                logger.warning(
                    "Аудиодорожка %s больше лимита Groq (%.2f МБ) — пропускаю", audio_path, file_size / 1024 / 1024
                )
                audio_path = None

        transcript = ""
        if audio_path:
            await status("⏳ Расшифровываю аудио...")
            try:
                transcript = await asyncio.to_thread(transcribe_audio_sync, audio_path)
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка транскрибации Groq Whisper")
                transcript = ""

        visual_notes = ""
        if image_paths:
            await status("⏳ Анализирую кадры/фото...")
            try:
                visual_notes = await asyncio.to_thread(analyze_images_sync, transcript, image_paths)
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка визуального анализа Groq")
                visual_notes = ""

        has_visual = bool(visual_notes) and not is_no_visual_info(visual_notes)

        if is_slideshow and has_visual:
            # Слайдшоу из нескольких фото: аудио — обычно просто музыка, самих
            # слайдов достаточно, без отдельной обёртки транскриптом.
            result = VideoResult(url=url, combined_text=visual_notes, is_slideshow=True)
            url_result_cache[url] = (time.time(), result)
            return result

        combined = build_combined_text(transcript, visual_notes)
        if not combined:
            return VideoResult(url=url, error="не удалось извлечь ни текст, ни визуальную информацию")

        result = VideoResult(url=url, combined_text=combined, is_slideshow=is_slideshow)
        url_result_cache[url] = (time.time(), result)
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
