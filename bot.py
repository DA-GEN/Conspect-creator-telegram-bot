"""
Точка входа Telegram-бота. Вся логика разложена по пакету app/:
- app/config.py        — переменные окружения, константы, промпты
- app/state.py          — состояние в памяти (чаты, проекты)
- app/downloader.py     — скачивание видео/аудио/фото (yt-dlp + tikwm.com)
- app/groq_client.py    — вызовы Groq (STT, vision, конспекты, чат)
- app/video_pipeline.py — сбор данных по одному видео
- app/files.py          — запись .md-файла результата
- app/keyboards.py      — inline-клавиатуры
- app/handlers/         — обработчики команд и сообщений Telegram

Используются только бесплатные технологии:
- aiogram 3.x (асинхронный Telegram-бот)
- yt-dlp + ffmpeg (скачивание видео, извлечение аудио и кадров)
- Groq Cloud API (free tier): whisper-large-v3 для STT,
  qwen/qwen3.6-27b (vision) для анализа кадров, LLM-модели для конспекта/чата
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.commands import BOT_COMMANDS
from app.config import BOT_TOKEN
from app.handlers import router
from app.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands(BOT_COMMANDS)

    logger.info("Бот запущен, начинаю polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
