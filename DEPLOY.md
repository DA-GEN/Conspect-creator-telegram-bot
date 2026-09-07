# Публикация на GitHub и деплой на хостинг

## ⚠️ Сначала — про токены

В процессе разработки реальные `BOT_TOKEN` и `GROQ_API_KEY` были показаны в
переписке (не в коде — в чате с ассистентом). Они никогда не попадали в git
(`.env` в `.gitignore`, проверено по всей истории коммитов), но раз они
светились в тексте переписки, безопаснее их перевыпустить, прежде чем
репозиторий станет публичным:

- Telegram: у [@BotFather](https://t.me/BotFather) → `/mybots` → выбрать
  бота → **API Token** → **Revoke current token**.
- Groq: https://console.groq.com/keys → удалить старый ключ, создать новый.

Впиши новые значения в свой локальный `.env` (в репозиторий он не попадёт).

## 1. Публикация на GitHub

В этом окружении нет `gh` (GitHub CLI) и не настроен git remote — создать
репозиторий и запушить код может только сам аккаунт-владелец (нужна твоя
авторизация), поэтому эти шаги — на твоей стороне. Всё остальное
(`.gitignore`, структура, Docker) уже готово.

```bash
# 1. Создать пустой репозиторий на GitHub (без README/license — они уже есть)
#    Через веб: https://github.com/new
#    Либо через gh CLI, если установлен:
gh repo create YOUR_USERNAME/new_tg_bot --private --source=. --remote=origin

# 2. Если создавал через веб-интерфейс — подключить remote вручную:
git remote add origin git@github.com:YOUR_USERNAME/new_tg_bot.git

# 3. Закоммитить текущее состояние (если ещё не закоммичено)
git add .
git commit -m "Prepare project for GitHub + hosting deployment"

# 4. Запушить
git push -u origin main
```

Перед пушем стоит ещё раз проверить, что `.env` не попадёт в коммит:
```bash
git status   # .env НЕ должен быть в списке
```

Приватный или публичный репозиторий — на твой выбор; код не содержит
секретов, но приватный безопаснее по умолчанию.

## 2. Хостинг — что нужно понимать

Бот использует **long polling** (постоянно опрашивает Telegram), а не
webhook — значит, ему нужен **процесс, работающий непрерывно**, а не
классический serverless/FaaS (AWS Lambda и подобные не подходят без
переделки на webhook). Также нужен установленный **ffmpeg** в системе.
Подходит: VPS, Docker-хостинг, PaaS с типом сервиса "worker"/"background
process" (не обычный web-сервис на HTTP).

Есть три готовых варианта — используй любой.

### Вариант A — Docker (любой хостинг с поддержкой контейнеров)

Самый портируемый способ — `Dockerfile` и `docker-compose.yml` уже в
репозитории.

```bash
# На сервере: склонировать репозиторий и создать .env с реальными токенами
git clone <URL_твоего_репозитория>
cd new_tg_bot
cp .env.example .env
nano .env   # вписать BOT_TOKEN и GROQ_API_KEY

# Собрать и запустить в фоне, с автоперезапуском при падении/перезагрузке сервера
docker compose up -d --build

# Логи
docker compose logs -f

# Остановить
docker compose down
```

`restart: unless-stopped` в `docker-compose.yml` перезапускает бота
автоматически при падении процесса или перезагрузке сервера.

Подходит для: любой VPS с Docker (Hetzner, DigitalOcean, Oracle Cloud Free
Tier и т.п.), а также PaaS с поддержкой Dockerfile (Railway, Render, Fly.io
— выбрать там тип сервиса **Worker / Background Service**, не Web Service,
и подключить `BOT_TOKEN`/`GROQ_API_KEY` через их интерфейс переменных
окружения вместо `.env`).

### Вариант B — обычный VPS без Docker (systemd)

Если не хочется возиться с Docker — план Б: python-процесс под systemd.

```bash
# На сервере
sudo useradd --system --create-home botuser
sudo mkdir -p /opt/new_tg_bot
sudo chown botuser:botuser /opt/new_tg_bot

sudo -u botuser git clone <URL_твоего_репозитория> /opt/new_tg_bot
cd /opt/new_tg_bot
sudo apt install -y ffmpeg python3-venv
sudo -u botuser python3 -m venv .venv
sudo -u botuser .venv/bin/pip install -r requirements.txt
sudo -u botuser cp .env.example .env
sudo -u botuser nano .env   # вписать токены

# Установить unit-файл (уже в репозитории, deploy/bot.service)
sudo cp deploy/bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now bot.service

# Проверить статус и логи
sudo systemctl status bot.service
sudo journalctl -u bot.service -f
```

Systemd сам перезапустит бота при падении (`Restart=on-failure`) и при
перезагрузке сервера (`enable`).

### Вариант C — PaaS без сервера в собственности

Если не хочется администрировать VPS — любой хостинг, поддерживающий
"Background Worker" из Dockerfile или напрямую из GitHub-репозитория
(например Railway.app, Render.com, Fly.io — конкретные шаги в их
веб-интерфейсе меняются, общий принцип один):

1. Подключить GitHub-репозиторий.
2. Выбрать тип сервиса **Worker/Background**, не Web Service (боту не нужен
   HTTP-порт).
3. Если платформа не подхватывает `Dockerfile` автоматически — команда
   запуска: `python bot.py`, команда сборки: `pip install -r requirements.txt`.
4. **Важно**: убедиться, что в образе/окружении есть `ffmpeg` — если
   платформа не даёт Dockerfile, а только buildpack, проверь, что у неё есть
   apt-пакет ffmpeg или используй Docker-режим той же платформы.
5. Добавить переменные окружения `BOT_TOKEN` и `GROQ_API_KEY` через
   настройки проекта на платформе (не через `.env`-файл).

## 3. После деплоя

- Логи пишутся в `logs/bot.log` (с ротацией) и в stdout — в Docker/systemd
  smотри именно stdout (`docker compose logs` / `journalctl`), т.к.
  `logs/` внутри контейнера/сервера может быть эфемерной, если не
  примонтирован volume (в `docker-compose.yml` volume уже настроен).
- Состояние бота (активные чаты, проекты, кэш) хранится в памяти процесса —
  при перезапуске оно сбрасывается. Для личного/небольшого использования
  это ожидаемо и не требует доработки.
- Если планируешь запускать бота параллельно и локально для тестов, и на
  хостинге — следи, чтобы одновременно был активен только один процесс с
  одним и тем же `BOT_TOKEN` (иначе `TelegramConflictError`, оба экземпляра
  борются за один и тот же long polling).
