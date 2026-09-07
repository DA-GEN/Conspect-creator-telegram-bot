# Лёгкий образ Python 3.12 + ffmpeg (обязателен для yt-dlp — извлечение
# аудио и кадров из видео).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Не root: контейнер не должен работать от root без необходимости.
RUN useradd --create-home --uid 1000 botuser \
    && mkdir -p /app/logs \
    && chown -R botuser:botuser /app
USER botuser

# BOT_TOKEN и GROQ_API_KEY передаются переменными окружения самим хостингом
# (или через --env-file/docker-compose) — .env в образ не попадает, см.
# .dockerignore.
CMD ["python", "bot.py"]
