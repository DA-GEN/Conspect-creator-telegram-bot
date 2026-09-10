"""Скачивание видео/аудио/фото: yt-dlp + запасной путь через tikwm.com для
TikTok-слайдшоу, плюс извлечение кадров через ffmpeg."""

import glob
import json
import logging
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.config import (
    DOWNLOAD_USER_AGENT,
    MAX_IMAGES,
    MAX_SLIDESHOW_IMAGES,
    TIKTOK_PHOTO_URL_REGEX,
    TIKWM_API_URL,
)

logger = logging.getLogger(__name__)


def _grab_frame(video_path: str, out_dir: str, i: int, ts: float) -> str | None:
    frame_path = os.path.join(out_dir, f"frame_{i}.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(ts), "-i", video_path, "-frames:v", "1", "-q:v", "3", frame_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.debug("Кадр на %.1fs не извлечён (возможно, нет видео): %s", ts, exc)
        return None
    return frame_path if os.path.exists(frame_path) else None


def extract_frames_sync(video_path: str, out_dir: str, duration: float, count: int = MAX_IMAGES) -> list[str]:
    """
    Вытаскивает через ffmpeg несколько равномерно распределённых по длительности
    кадров. Каждый кадр — независимый seek+decode одним процессом ffmpeg, поэтому
    гоняем их параллельно (subprocess.run отпускает GIL на время ожидания
    дочернего процесса — тут потоки, а не asyncio, вполне уместны). Если у
    файла нет видеопотока (чистое аудио, например TikTok-пост без видео) —
    ffmpeg просто не найдёт кадр, и функция вернёт пустой список.
    """
    timestamps = [duration * (i + 1) / (count + 1) for i in range(count)] if duration > 0 else [1.0]

    with ThreadPoolExecutor(max_workers=len(timestamps)) as executor:
        results = list(executor.map(lambda args: _grab_frame(video_path, out_dir, *args), enumerate(timestamps)))

    return [p for p in results if p]


def download_url_to_file(url: str, path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as out:
        shutil.copyfileobj(resp, out)


def download_tiktok_slideshow_sync(url: str, out_dir: str) -> dict[str, object]:
    """
    Запасной способ для TikTok-слайдшоу (постов из нескольких фото,
    /photo/<id>) — yt-dlp такие ссылки не поддерживает вообще (падает с
    "Unsupported URL"), а прямой запрос к веб-странице TikTok блокируется
    капчей. Вместо этого берём прямые ссылки на фото и музыку через
    сторонний публичный агрегатор tikwm.com.
    """
    api_url = TIKWM_API_URL + "?" + urllib.parse.urlencode({"url": url, "hd": 1})
    req = urllib.request.Request(api_url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if payload.get("code") != 0:
        raise RuntimeError(f"tikwm.com: {payload.get('msg', 'неизвестная ошибка')}")

    data = payload.get("data") or {}
    image_urls = list(data.get("images") or [])[:MAX_SLIDESHOW_IMAGES]
    if not image_urls:
        raise RuntimeError("tikwm.com не вернул фото для этого поста")

    music_url = data.get("music")
    audio_path = os.path.join(out_dir, "media_audio.m4a") if music_url else None
    image_paths = [os.path.join(out_dir, f"slide_{i}.jpg") for i in range(len(image_urls))]

    # Каждое фото (и музыка) — независимый HTTP-запрос к CDN, латентность
    # доминирует над пропускной способностью, поэтому качаем их параллельно.
    with ThreadPoolExecutor(max_workers=min(len(image_urls) + 1, 8)) as executor:
        futures = [
            executor.submit(download_url_to_file, img_url, path)
            for img_url, path in zip(image_urls, image_paths, strict=True)
        ]
        if music_url:
            futures.append(executor.submit(download_url_to_file, music_url, audio_path))
        for future in futures:
            future.result()  # пробрасываем исключение, если хоть одна загрузка упала

    return {"audio_path": audio_path, "image_paths": image_paths, "is_slideshow": True}


def download_media_via_ytdlp_sync(url: str, out_dir: str) -> dict[str, object]:
    """
    Скачивает видео целиком, если у платформы есть видеопоток (нужно для
    визуального анализа кадров), иначе — только аудио (например,
    TikTok-слайдшоу без видео, только музыка/голос).

    Возвращает {"audio_path": путь к файлу для Whisper (или None),
                 "image_paths": список путей к извлечённым кадрам}.
    """
    ydl_opts = {
        # Предпочитаем видео+аудио (до 480p, этого достаточно для анализа
        # кадров и не раздувает трафик), иначе — лучший доступный поток
        # (для платформ без видео — просто аудио).
        "format": "bv*[height<=480]+ba/b[height<=480]/bestaudio/best",
        "outtmpl": os.path.join(out_dir, "media.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "retries": 3,
        "socket_timeout": 30,
        "http_headers": {"User-Agent": DOWNLOAD_USER_AGENT},
        "merge_output_format": "mp4",
        "keepvideo": True,  # не удалять видео после извлечения аудио — нужно для кадров
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    base, _ = os.path.splitext(filename)
    mp3_path = base + ".mp3"
    video_path = filename if os.path.exists(filename) else None
    audio_path = mp3_path if os.path.exists(mp3_path) else video_path

    if not video_path and not audio_path:
        # На случай если yt-dlp назвал файл иначе, чем ожидалось
        candidates = glob.glob(os.path.join(out_dir, "media.*"))
        if not candidates:
            raise FileNotFoundError("yt-dlp не вернул файл после скачивания")
        video_path = candidates[0]
        audio_path = audio_path or video_path

    image_paths = extract_frames_sync(video_path, out_dir, info.get("duration") or 0) if video_path else []

    return {"audio_path": audio_path, "image_paths": image_paths, "is_slideshow": False}


def download_media_sync(url: str, out_dir: str) -> dict[str, object]:
    """Выполняется в отдельном потоке, т.к. и yt-dlp, и urllib — блокирующие.
    Основной путь — yt-dlp; для TikTok-слайдшоу (которые yt-dlp не умеет
    скачивать) — фолбэк через tikwm.com."""
    try:
        return download_media_via_ytdlp_sync(url, out_dir)
    except DownloadError as exc:
        if not TIKTOK_PHOTO_URL_REGEX.search(str(exc)):
            raise
        logger.info("TikTok-слайдшоу, пробую запасной способ (tikwm.com): %s", url)
        try:
            return download_tiktok_slideshow_sync(url, out_dir)
        except Exception as fallback_exc:  # noqa: BLE001 — оборачиваем в тот же тип, что и основной путь
            logger.exception("tikwm.com тоже не смог скачать слайдшоу: %s", url)
            raise DownloadError(f"TikTok slideshow fallback failed: {fallback_exc}") from fallback_exc
