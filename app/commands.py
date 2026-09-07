"""Список команд бота — задаёт всплывающее меню Telegram, которое появляется
при вводе "/" в чате (регистрируется через Bot.set_my_commands в bot.py)."""

from aiogram.types import BotCommand

BOT_COMMANDS = [
    BotCommand(command="start", description="Начало работы, краткая инструкция"),
    BotCommand(command="help", description="Подробная справка: как пользоваться ботом"),
    BotCommand(command="context", description="Ответ по видео на конкретный запрос: /context <запрос> <ссылка>"),
    BotCommand(command="newproject", description="Начать проект — конспект сразу по нескольким видео"),
    BotCommand(command="finishproject", description="Завершить проект и получить общий конспект"),
    BotCommand(command="cancelproject", description="Отменить текущий проект без обработки"),
    BotCommand(command="endchat", description="Выйти из режима чата по конспекту"),
]
