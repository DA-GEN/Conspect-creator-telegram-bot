"""Тесты формирования имени и содержимого .md-файла с результатом."""

from app.files import build_result_filename, write_result_file


def test_build_result_filename_uses_last_five_chars():
    name = build_result_filename("https://youtu.be/abcde")
    assert name == "result_abcde.md"


def test_build_result_filename_strips_trailing_slash():
    name = build_result_filename("https://vt.tiktok.com/ZSqM7cnjF/")
    assert name == "result_7cnjF.md"


def test_build_result_filename_sanitizes_unsafe_chars():
    name = build_result_filename("https://example.com/x?a=1")
    # последние 5 символов "a=1" -> небезопасные "?", "=" вырезаются
    assert name.startswith("result_")
    assert name.endswith(".md")
    assert "=" not in name
    assert "?" not in name


def test_build_result_filename_falls_back_to_video_when_suffix_empty():
    name = build_result_filename("https://example.com/?????")
    assert name == "result_video.md"


def test_write_result_file_creates_expected_content(tmp_path):
    path = write_result_file(
        str(tmp_path),
        "result_test.md",
        "Конспект",
        "https://example.com/video",
        [("Конспект", "Текст конспекта")],
    )

    content = open(path, encoding="utf-8").read()
    assert content.startswith("# Конспект\n")
    assert "Источник: https://example.com/video" in content
    assert "## Конспект" in content
    assert "Текст конспекта" in content


def test_write_result_file_without_url_skips_source_line(tmp_path):
    path = write_result_file(str(tmp_path), "result_test.md", "Проект", "", [("Тема", "Текст")])

    content = open(path, encoding="utf-8").read()
    assert "Источник:" not in content
