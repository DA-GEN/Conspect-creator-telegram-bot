"""Тесты на распознавание ссылок: обычный URL_REGEX (используется, чтобы
понять — прислали вообще ссылку или нет) и TIKTOK_PHOTO_URL_REGEX (отличает
TikTok-слайдшоу, которые yt-dlp не умеет скачивать, от обычных видео)."""

from app.config import TIKTOK_PHOTO_URL_REGEX, URL_REGEX

VALID_VIDEO_URLS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://vt.tiktok.com/ZSqM7cnjF/",
    "https://www.tiktok.com/@user/video/7123456789012345678",
    "https://www.instagram.com/reel/Dcs467mO9x-/",
    "http://example.com/video",  # http, не только https
]

GARBAGE_TEXTS = [
    "привет, как дела?",
    "просто текст без ссылки",
    "ftp://example.com/file.mp4",  # не http(s) — намеренно не поддерживается
    "www.youtube.com/watch?v=abc",  # без схемы http(s) — тоже не считается ссылкой
    "",
]


def test_url_regex_matches_known_video_platforms():
    for url in VALID_VIDEO_URLS:
        assert URL_REGEX.search(url), f"ожидали, что {url!r} распознается как ссылка"


def test_url_regex_rejects_garbage_text():
    for text in GARBAGE_TEXTS:
        assert not URL_REGEX.search(text), f"{text!r} не должен считаться ссылкой"


def test_url_regex_finds_all_urls_in_mixed_message():
    text = "вот два видео: https://youtu.be/aaa и https://vt.tiktok.com/bbb/ гляньте"
    found = URL_REGEX.findall(text)
    assert found == ["https://youtu.be/aaa", "https://vt.tiktok.com/bbb/"]


def test_tiktok_photo_regex_matches_slideshow_links():
    assert TIKTOK_PHOTO_URL_REGEX.search("https://www.tiktok.com/@user/photo/7123456789012345678")


def test_tiktok_photo_regex_rejects_regular_tiktok_video():
    assert not TIKTOK_PHOTO_URL_REGEX.search("https://www.tiktok.com/@user/video/7123456789012345678")


def test_tiktok_photo_regex_rejects_other_platforms():
    assert not TIKTOK_PHOTO_URL_REGEX.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
