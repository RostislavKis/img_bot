## 2026-02-09 — T-005.2: Исправления generate.py + FLUX img2img + мягкий перевод промптов

**Цель:** Убрать синтаксические проблемы в generate.py, подключить FLUX img2img для enhance/edit и добавить мягкий перевод RU→EN без падений.

**Тикет:** T-005.2

**Изменено/добавлено:**
- `bot/handlers/generate.py`
  - Исправлен импорт settings через DI (убран `from config.settings import settings`)
  - Добавлены константы: `WORKFLOW_FLUX_DEV_IMG2IMG`, `WORKFLOW_FLUX_SCHNELL_IMG2IMG`
  - Добавлен `_inject_denoise()` и поддержка `denoise` в `_run_image_job()`
  - Enhance/Edit/Mask: выбор FLUX img2img если доступен, иначе `image_default`
    * enhance → denoise=0.25
    * edit → denoise=0.55
    * mask → denoise=0.65 (через `image_default`)
  - Добавлен мягкий перевод RU→EN через argostranslate (fallback без падения)
  - Перевод применяется перед инжектом промпта

- `tools/make_flux_img2img.py`
  - Скрипт для автогенерации FLUX img2img workflow из txt2img
  - Добавляет LoadImage + VAEEncode, переключает latent

**Как проверить:**
- Сгенерировать workflow:
  - `python tools/make_flux_img2img.py --in workflows/flux_dev_fp8.json --out workflows/flux_dev_fp8_img2img.json`
- Проверить редактирование фото (кнопки):
  - Enhance/Edit должны выбирать FLUX img2img, если файл существует
  - Mask остаётся на `image_default`

---

# CHANGELOG_INTERNAL (img_bot)

Р–СѓСЂРЅР°Р» Р’РЎР•РҐ РІРЅСѓС‚СЂРµРЅРЅРёС… РёР·РјРµРЅРµРЅРёР№ РїСЂРѕРµРєС‚Р°. Р’СЃРµ Р·Р°РїРёСЃРё РЅР° СЂСѓСЃСЃРєРѕРј.

**РџСЂР°РІРёР»Рѕ:** РєР°Р¶РґС‹Р№ РєРѕРјРјРёС‚ СЃ РёР·РјРµРЅРµРЅРёРµРј РєРѕРґР° РћР‘РЇР—РђРќ СЃРѕРґРµСЂР¶Р°С‚СЊ Р·Р°РїРёСЃСЊ Р·РґРµСЃСЊ.

---

## 2025-01-17 — T-004.1: Smoke-check инструмент ComfyUI (диагностика API)

**Цель:** Иметь стабильную проверку здоровья ComfyUI с понятным диагнозом и exit code.

**Тикет:** T-004.1

**Добавлено:**
- `tools/smoke_check.py` — smoke-check скрипт:
  - Проверяет: `/`, `/system_stats`, `/queue`, `/object_info`
  - Печатает OK/FAIL по каждому endpoint
  - Возвращает exit code: 0 (OK) / 1 (FAIL)
  - Поддерживает повторные попытки: `--repeat N --delay S`
  - URL задаётся `--url` или переменной окружения `COMFY_URL`
  - Мини-диагностика при ошибке: почему не удалось подключиться

**Использование:**

```sh
# Простая проверка
python tools/smoke_check.py

# С кастомным URL
python tools/smoke_check.py --url http://localhost:8188

# С повторными попытками (полезно при старте ComfyUI)
python tools/smoke_check.py --repeat 5 --delay 1.0

# С переменной окружения
COMFY_URL=http://192.168.1.100:8188 python tools/smoke_check.py
```

**Результат:**

- Быстрая проверка доступности ComfyUI API перед запуском бота
- Понятный диагноз при недоступности (ComfyUI не запущен, неправильный URL, версия API и т.п.)
- Exit code для CI/скриптов автоматизации

---

## 2025-01-17 — T-003.3: Детерминированный генератор WORKFLOWS_REFERENCE (без timestamp)

**Цель:** Убрать timestamp из генератора справочника, чтобы избежать "пустых" коммитов и рассинхрона в CI.

**Тикет:** T-003.3

**Обновлено:**

- `tools/gen_workflows_reference.py` — полностью переписан для детерминированного вывода
  - Убран timestamp из шапки файла (была строка с датой/временем генерации)
  - Улучшена функция `_normalize_nodes()` — поддержка как dict, так и list формата nodes
  - Улучшена `_guess_kind()` — более надёжная эвристика определения типа (image/video/unknown)
  - Добавлена `_md_escape_cell()` — экранирование символов для Markdown таблиц
  - Детерминированный порядок: сортировка workflows по имени (sorted)
  - Стабильный вывод: одинаковый JSON → одинаковый WORKFLOWS_REFERENCE.md

**Результат:**

- Генератор теперь детерминированный: при одинаковых workflows/*.json выдаёт идентичный WORKFLOWS_REFERENCE.md
- CI `.github/workflows/docs-workflows-reference.yml` не будет ловить ложные изменения
- Коммиты станут чище (не будет diff на одну строку с timestamp)

---

## 2025-01-17 — T-004.2: Smoke-check на urllib (без зависимостей от requests)

**Цель:** Убрать зависимость от `requests`, чтобы smoke-check работал в чистом venv без установки пакетов.

**Тикет:** T-004.2

**Обновлено:**
- `tools/smoke_check.py` — переписан с использованием стандартной библиотеки
  - Заменён `requests` на `urllib.request` (стандартная библиотека Python)
  - Новая структура: `CheckResult` dataclass с `ok`, `status`, `elapsed_ms`, `error`, `data`
  - Функция `_http_json()` — универсальный GET с таймаутом и парсингом JSON
  - Функция `_print_endpoint()` — форматированный вывод результата (✅ OK / ❌ FAIL)
  - Функция `_summarize()` — краткая сводка по ответу (ключи JSON, количество элементов в queue, количество нод)
  - Убран корневой endpoint `/` (не нужен для проверки API)
  - Проверяются: `/system_stats`, `/queue`, `/object_info`

**Результат:**
- Smoke-check теперь работает в чистом Python venv без `pip install requests`
- Более стабильный (стандартная библиотека гарантированно есть)
- Лучший вывод: показывает HTTP status, время ответа (ms), ошибки с контекстом
- Exit codes: 0 (OK), 1 (FAIL), 2 (invalid args)

**Использование:**

```sh
# Простая проверка
python tools/smoke_check.py

# С повторными попытками (полезно при старте ComfyUI)
python tools/smoke_check.py --repeat 5 --delay 1.0

# Кастомный URL и timeout
python tools/smoke_check.py --url http://192.168.1.100:8188 --timeout 5.0
```

---

## 2025-01-17 — T-004.3: Нормализация line endings через .gitattributes

**Цель:** Убрать постоянные предупреждения Git "LF will be replaced by CRLF" и избежать пустых коммитов из-за различий в окончаниях строк.

**Тикет:** T-004.3

**Обновлено:**
- `.gitattributes` — полная переписка для Python проекта (вместо старого .NET шаблона)
  - Установлено `* text=auto eol=lf` — все текстовые файлы хранятся в репо с LF
  - Windows scripts (*.bat, *.cmd, *.ps1) — eol=crlf (правильно для Windows)
  - Код и конфиги (*.py, *.yml, *.json, *.md) — eol=lf (Unix стиль)
  - Shell scripts и hooks (.githooks/*, *.sh) — eol=lf (обязательно)
  - Бинарные файлы помечены как `binary`: изображения, видео, модели ML (*.safetensors, *.pt, *.ckpt)

**Результат:**
- Git больше не предупреждает об автозамене LF↔CRLF при коммитах на Windows
- CI/генераторы не создают "пустые" коммиты из-за различий в line endings
- Репозиторий детерминированный: одинаковый контент → одинаковый git diff
- Pre-commit hooks (в .githooks/) корректно работают на всех платформах

---

## 2025-01-17 — T-005: Сквозной пайплайн Telegram → ComfyUI → output → отправка

**Цель:** Создать полноценный асинхронный пайплайн для обработки запросов генерации через Telegram с очередью, воркерами, таймаутами, retry-логикой и отправкой результатов.

**Тикет:** T-005

**Добавлено:**
- `core/job_queue.py` — очередь задач с воркерами
  - Класс `Job` — задача с метаданными (kind, chat_id, user_id, payload, timeouts, retries)
  - Класс `JobQueue` — асинхронная очередь с N воркерами
  - `JobStatus` enum: queued, running, retrying, done, failed, canceled
  - Retry-логика: экспоненциальный backoff с джиттером
  - Timeout на выполнение задачи (asyncio.timeout)
  - Cancel support: graceful отмена через Event
  - Callbacks: on_status, on_done, on_error для интеграции с UI

- `core/telegram_pipeline.py` — интеграция Telegram + ComfyUI
  - Класс `TelegramComfyPipeline` — главный пайплайн
  - `enqueue_from_message()` — создание job из Telegram сообщения
  - Автоматическое обновление статус-сообщения в Telegram
  - Определение типа результата по расширению (video/gif/image/file)
  - Отправка результата в Telegram: send_video/send_animation/send_photo/send_document
  - Универсальный worker для comfy/client.py (пробует разные сигнатуры методов)
  - Обработка Telegram rate limits (TelegramRetryAfter)
  - Настройки через переменные окружения: PIPELINE_CONCURRENCY, PIPELINE_TIMEOUT_IMAGE_S, PIPELINE_TIMEOUT_VIDEO_S

- `bot/handlers/t005_pipeline_demo.py` — демо handler
  - `/gen <prompt>` — генерация изображения через pipeline
  - `/video <prompt>` — генерация видео через pipeline
  - `/cancel` — отмена последней задачи пользователя

**Результат:**
- Полноценная очередь задач с контролем concurrency (по умолчанию 2 воркера)
- Автоматические retry при сетевых/временных ошибках (по умолчанию 2 повтора)
- Timeouts: 600s для изображений, 1800s для видео (настраиваются)
- Graceful shutdown воркеров при остановке бота
- Универсальная интеграция с comfy/client.py (не требует конкретной сигнатуры)
- Telegram rate limit handling (автоматический retry после sleep)
- Понятные статус-сообщения на русском

**Как использовать:**

1. Добавить в main.py:
```python
from core.telegram_pipeline import TelegramComfyPipeline, PipelineConfig
from bot.handlers.t005_pipeline_demo import router as t005_demo_router

pipeline = TelegramComfyPipeline(bot, PipelineConfig())
bot["pipeline"] = pipeline

dp.startup.register(lambda: pipeline.start())
dp.shutdown.register(lambda: pipeline.stop())

dp.include_router(t005_demo_router)
```

2. Запустить бота:
```sh
python main.py
```

3. В Telegram:
- `/gen beautiful sunset over mountains` → генерация изображения
- `/video dancing cat` → генерация видео
- `/cancel` → отмена текущей задачи

**Требования к comfy/client.py:**

Один из вариантов:
- Функция `run_job(kind, payload) -> path/dict`
- Класс `ComfyClient` с методом `run(kind, payload)`, `execute(...)`, `generate(...)`, `generate_image(...)` или `generate_video(...)`

Pipeline автоматически определит доступные методы и вызовет подходящий.

---

## 2025-01-17 — T-005.1: Fix ComfyUIClient.download_file (убраны отсутствующие self.log и _download_file_once)

**Цель:** Исправить баг в `comfy/client.py` где метод `download_file()` ссылался на несуществующие `self.log` и `_download_file_once()`.

**Тикет:** T-005.1

**Исправлено:**
- `comfy/client.py` — метод `download_file()`
  - Теперь является совместимой обёрткой над `view_bytes()`
  - Убраны ссылки на отсутствующие `self.log` (используется глобальный `log`)
  - Убраны ссылки на отсутствующий метод `_download_file_once()`
  - Добавлена docstring с пояснением истории метода

**Результат:**
- `download_file()` корректно работает как alias для `view_bytes()`
- Нет AttributeError при вызове `download_file()`
- Обратная совместимость сохранена





