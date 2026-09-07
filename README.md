# new_tg_bot

Telegram-бот, который скачивает аудио из видео (YouTube, TikTok, Instagram),
расшифровывает его в текст и по желанию делает структурированный конспект.

Использует только бесплатные технологии:
- **aiogram 3.x** — асинхронный Telegram-бот
- **yt-dlp** — скачивание аудиодорожки
- **Groq Cloud API (free tier)** — `whisper-large-v3` для распознавания речи,
  `llama3-70b-8192` (с fallback на `llama3-8b-8192`) для конспекта

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить BOT_TOKEN и GROQ_API_KEY
python bot.py
```

- `BOT_TOKEN` — токен бота от [@BotFather](https://t.me/BotFather)
- `GROQ_API_KEY` — ключ с https://console.groq.com/keys (бесплатный тариф)

> ffmpeg не требуется: бот скачивает уже готовый аудиопоток (m4a/webm) через
> yt-dlp без постобработки. Если для какой-то платформы нет отдельного
> аудиопотока, скачивается видео целиком — Groq Whisper принимает и такие
> файлы (mp4) напрямую.

## Как пользоваться

1. Отправить боту ссылку на видео (YouTube/TikTok/Instagram).
2. Выбрать в inline-клавиатуре: «Только текст» или «Сделать конспект».
3. Дождаться расшифровки — бот пришлёт результат, разбив на части, если
   текст длиннее лимита Telegram (4096 символов).

## Структура

- `bot.py` — весь код бота (конфиг, хендлеры, интеграция с yt-dlp и Groq)
- `.env` — секреты (не коммитится)
- `requirements.txt` — зафиксированные версии зависимостей
