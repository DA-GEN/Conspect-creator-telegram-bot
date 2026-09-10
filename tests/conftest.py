"""Общие фикстуры и настройка окружения для тестов.

app.config читает BOT_TOKEN/GROQ_API_KEY при импорте и падает, если их нет —
поэтому подставляем тестовые значения ДО того, как что-либо импортирует
app.*. conftest.py гарантированно загружается pytest раньше тестовых модулей.
"""

import os

os.environ.setdefault("BOT_TOKEN", "123456:test-bot-token")
os.environ.setdefault("GROQ_API_KEY", "test-groq-api-key")
