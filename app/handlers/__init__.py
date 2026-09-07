"""Сборка всех роутеров бота в один. Порядок include важен: обработчик
video.handle_link подписан на F.text (ловит вообще любой текст), поэтому
подключается последним — иначе он перехватывал бы команды раньше их
собственных хендлеров."""

from aiogram import Router

from app.handlers import basic, chat, context, project, video

router = Router()
router.include_router(basic.router)
router.include_router(chat.router)
router.include_router(project.router)
router.include_router(context.router)
router.include_router(video.router)
