"""Клиент Groq и все функции, обращающиеся к его API: STT, vision-анализ,
конспекты, ответы в чате."""

import base64
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from groq import Groq

from app.config import (
    CHAT_SYSTEM_PROMPT,
    CONTEXT_QUERY_PROMPT,
    GROQ_API_KEY,
    LLM_MODEL_FALLBACK,
    LLM_MODEL_PRIMARY,
    MAX_IMAGES,
    MAX_TOKENS_CHAT,
    MAX_TOKENS_CONTEXT,
    MAX_TOKENS_PROJECT_SUMMARY,
    MAX_TOKENS_SUMMARY,
    MAX_TOKENS_VISION,
    MAX_TRANSCRIPT_CHARS_FOR_LLM,
    NO_VISUAL_INFO,
    PROJECT_SUMMARY_PROMPT,
    STT_MODEL,
    SUMMARY_PROMPT,
    VISION_BATCH_CONCURRENCY,
    VISION_MODEL_FALLBACK,
    VISION_MODEL_PRIMARY,
    VISUAL_ANALYSIS_PROMPT,
)

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=GROQ_API_KEY)


def transcribe_audio_sync(file_path: str) -> str:
    """Отправляет аудиофайл в Groq Whisper и возвращает распознанный текст."""
    with open(file_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            file=(os.path.basename(file_path), audio_file.read()),
            model=STT_MODEL,
        )
    return (transcription.text or "").strip()


def encode_image_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def is_no_visual_info(visual_notes: str) -> bool:
    return visual_notes.strip().strip(".!").upper() == NO_VISUAL_INFO


def call_llm_with_fallback(
    messages: List[Dict[str, object]], models: tuple, purpose: str, max_tokens: Optional[int] = None
) -> str:
    """Запрос к Groq chat completions с фолбэком на вторую модель при ошибке
    (rate limit, деприкейт модели и т.п.) — общая логика для всех LLM-вызовов.
    max_tokens ограничивает длину ответа: без него модель сама решает, сколько
    генерировать, и на free-тарифе Groq это легко ловит 429 по output-tokens.

    Reasoning-модели (семейство gpt-oss) тратят часть max_tokens на скрытые
    reasoning-токены ДО видимого ответа — при нехватке бюджета API вернёт
    200 OK с пустым content, без исключения. Такой ответ нельзя молча
    прокидывать дальше (Telegram, например, отказывается слать пустое
    сообщение) — считаем его провалом модели и пробуем следующую."""
    last_error: Optional[Exception] = None
    for model in models:
        try:
            completion = groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=max_tokens,
            )
            content = (completion.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("модель вернула пустой ответ (не хватило max_tokens после reasoning)")
            return content
        except Exception as exc:  # noqa: BLE001 — специально широкий catch, есть fallback-модель
            last_error = exc
            logger.warning("Модель %s не сработала (%s): %s", model, purpose, exc)

    raise RuntimeError(f"Не удалось получить ответ от Groq ({purpose}): {last_error}")


def analyze_image_batch_sync(transcript: str, image_paths: List[str], label: str) -> str:
    """Один запрос к vision-модели Groq на батч картинок (не больше MAX_IMAGES —
    лимит модели за раз). Возвращает NO_VISUAL_INFO, если картинки бесполезны."""
    prompt = VISUAL_ANALYSIS_PROMPT.format(label=label, transcript=transcript[:MAX_TRANSCRIPT_CHARS_FOR_LLM] or "(пусто)")
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image_b64(p)}"}}
        for p in image_paths
    ]
    messages = [{"role": "user", "content": content}]
    return call_llm_with_fallback(
        messages, (VISION_MODEL_PRIMARY, VISION_MODEL_FALLBACK), "vision", max_tokens=MAX_TOKENS_VISION
    )


def analyze_images_sync(transcript: str, image_paths: List[str]) -> str:
    """Анализирует ВСЕ картинки, а не только первые MAX_IMAGES: за один запрос к
    vision-модели влезает не больше MAX_IMAGES картинок (лимит моделей Groq),
    поэтому при слайдшоу из большего числа фото разбивает их на батчи. Батчи
    независимы друг от друга (используют только общий transcript как контекст),
    поэтому гоняем их параллельно (с ограничением VISION_BATCH_CONCURRENCY,
    чтобы не словить rate limit разом). Возвращает NO_VISUAL_INFO, если ни один
    батч не дал полезной информации."""
    batches = [image_paths[i : i + MAX_IMAGES] for i in range(0, len(image_paths), MAX_IMAGES)]

    def run_batch(item: tuple) -> str:
        i, batch = item
        label = f"слайды {i * MAX_IMAGES + 1}-{i * MAX_IMAGES + len(batch)} из {len(image_paths)}" if len(batches) > 1 else "кадры"
        return analyze_image_batch_sync(transcript, batch, label)

    if len(batches) == 1:
        raw_notes = [run_batch((0, batches[0]))]
    else:
        with ThreadPoolExecutor(max_workers=min(len(batches), VISION_BATCH_CONCURRENCY)) as executor:
            raw_notes = list(executor.map(run_batch, enumerate(batches)))

    notes = [note for note in raw_notes if not is_no_visual_info(note)]
    return "\n\n".join(notes) if notes else NO_VISUAL_INFO


def build_combined_text(transcript: str, visual_notes: str) -> str:
    """Собирает текст для конспекта/чат-контекста из расшифровки и (если есть
    и полезны) визуальных деталей."""
    parts = []
    if transcript:
        parts.append(f"Расшифровка аудио:\n{transcript}")
    if visual_notes and not is_no_visual_info(visual_notes):
        parts.append(f"Визуальные детали (из кадров):\n{visual_notes}")
    return "\n\n".join(parts)


def summarize_text_sync(text: str) -> str:
    """Просит LLM Groq сделать структурированный конспект одного видео."""
    prompt = SUMMARY_PROMPT.format(text=text[:MAX_TRANSCRIPT_CHARS_FOR_LLM])
    return call_llm_with_fallback(
        [{"role": "user", "content": prompt}], (LLM_MODEL_PRIMARY, LLM_MODEL_FALLBACK), "конспект", max_tokens=MAX_TOKENS_SUMMARY
    )


def answer_context_query_sync(instruction: str, text: str) -> str:
    """Отвечает на конкретный запрос пользователя по материалу видео (команда
    /context) — без общего конспекта, только то, что попросили."""
    prompt = CONTEXT_QUERY_PROMPT.format(instruction=instruction, text=text[:MAX_TRANSCRIPT_CHARS_FOR_LLM])
    return call_llm_with_fallback(
        [{"role": "user", "content": prompt}], (LLM_MODEL_PRIMARY, LLM_MODEL_FALLBACK), "запрос по видео", max_tokens=MAX_TOKENS_CONTEXT
    )


def summarize_project_sync(materials: str) -> str:
    """Просит LLM Groq сгруппировать материалы нескольких видео по темам и
    сделать один общий структурированный конспект (см. PROJECT_SUMMARY_PROMPT)."""
    prompt = PROJECT_SUMMARY_PROMPT.format(materials=materials)
    return call_llm_with_fallback(
        [{"role": "user", "content": prompt}],
        (LLM_MODEL_PRIMARY, LLM_MODEL_FALLBACK),
        "конспект проекта",
        max_tokens=MAX_TOKENS_PROJECT_SUMMARY,
    )


def chat_answer_sync(content: str, history: List[Dict[str, str]], question: str) -> str:
    """Отвечает на вопрос пользователя по сохранённому тексту (транскрипт/конспект),
    учитывая историю диалога."""
    system_prompt = CHAT_SYSTEM_PROMPT.format(content=content[:MAX_TRANSCRIPT_CHARS_FOR_LLM])
    messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": question}]
    return call_llm_with_fallback(messages, (LLM_MODEL_PRIMARY, LLM_MODEL_FALLBACK), "чат", max_tokens=MAX_TOKENS_CHAT)
