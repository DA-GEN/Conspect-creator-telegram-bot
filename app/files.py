"""Формирование имени и содержимого .md-файла с результатом."""

import os
import re

FILENAME_UNSAFE_REGEX = re.compile(r"[^A-Za-z0-9_-]+")


def build_result_filename(url: str) -> str:
    """result_<последние 5 символов ссылки>.md, с санитайзингом под имя файла."""
    trimmed = url.strip().rstrip("/")
    suffix = FILENAME_UNSAFE_REGEX.sub("", trimmed[-5:]) or "video"
    return f"result_{suffix}.md"


def write_result_file(out_dir: str, filename: str, title: str, url: str, sections: list[tuple]) -> str:
    """Пишет .md-файл с результатом. sections — список (заголовок, текст).
    url — необязательный: для проектов с несколькими источниками строку
    "Источник:" не пишем, а список ссылок передают отдельной секцией."""
    parts = [f"# {title}"]
    if url:
        parts += ["", f"Источник: {url}"]
    for heading, body in sections:
        parts.extend(["", f"## {heading}", "", body])
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    return path
