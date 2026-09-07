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

Режим работы выбирается автоматически: если задан RENDER_EXTERNAL_URL
(Render сам прокидывает его для веб-сервисов) — используется webhook, иначе
(локально, на обычном VPS) — long polling.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.commands import BOT_COMMANDS
from app.config import BOT_TOKEN, PORT, RENDER_EXTERNAL_URL, WEBHOOK_SECRET
from app.handlers import router
from app.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook"


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    webhook_url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logger.info("Бот запущен в режиме webhook: %s", webhook_url)

    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/", health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET or None
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    await asyncio.Event().wait()  # держим процесс живым до остановки


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    logger.info("Бот запущен, начинаю polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands(BOT_COMMANDS)

    if RENDER_EXTERNAL_URL:
        await run_webhook(bot, dp)
    else:
        await run_polling(bot, dp)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
