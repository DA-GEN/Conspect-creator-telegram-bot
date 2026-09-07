# new_tg_bot

Чистый старт нового Telegram-бота на Python.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить BOT_TOKEN
python main.py
```

## Структура

- `bot/` — код бота (конфигурация, хендлеры и т.д.)
- `main.py` — точка входа
- `.env` — секреты (не коммитится)

Фреймворк и функционал будут добавлены отдельно.
