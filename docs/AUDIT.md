# IMG_BOT: Архитектурный аудит и решения

## Обзор проекта

**img_bot** — Telegram бот на aiogram, интегрирован с ComfyUI для генерации изображений/видео (FLUX, SDXL, AnimateDiff).

- Python 3.11, Windows 11
- Запуск: `.\.venv\Scripts\python.exe .\main.py`
- ComfyUI: D:\ComfyUI → API http://127.0.0.1:8188

---

## КРИТИЧЕСКИЕ ПРОБЛЕМЫ И РЕШЕНИЯ

### 1) Инжект промпта НЕ УСТОЙЧИВ ✅ FIXED

**Проблема**: FLUX workflows имеют 2+ CLIPTextEncode ноды (CLIP + T5), но промпт вставлялся только в первый.

**Решение**: `_inject_prompt()` теперь вставляет ВО ВСЕ текстовые поля (input.text, input.prompt, и т.д.)

**Файл**: bot/handlers/generate.py — строки 62-102

### 2) Структура workflows JSON непредсказуема ✅ FIXED

**Проблема**: 
- FLUX: плоская `{"1": {...}, "2": {...}}`
- video_default.json: обёртка `{"nodes": {...}}` + BOM + кракозябры

**Решение**: WorkflowLoader нормализует оба формата, читает с utf-8-sig

**Файл**: comfy/workflow_loader.py — весь файл переписан

### 3) Видео-генерация НЕ РАБОТАЕТ ✅ FIXED

**Проблема**: video_default.json был placeholder `{"{prompt}"}`

**Решение**: Заменён на реальный AnimateDiff workflow (7 нод: encode → sampler → decode → vhs_combine)

**Файл**: workflows/video_default.json

### 4) Help справка — заглушка ✅ FIXED

**Проблема**: "📖 Это каркас бота. Генерация будет добавлена следующим шагом."

**Решение**: Добавлена полная справка на русском и английском с примерами промптов

**Файл**: bot/handlers/help.py

---

## ФАЙЛЫ, КОТОРЫЕ БЫЛИ ИЗМЕНЕНЫ

1. **comfy/workflow_loader.py** — нормализация JSON структур + UTF-8-sig
2. **bot/handlers/generate.py** — устойчивый инжект промпта, много комментариев
3. **bot/handlers/help.py** — полная справка на русском и английском
4. **workflows/video_default.json** — реальный AnimateDiff workflow
5. **config/settings.py** — уже было, но добавлена utf-8-sig поддержка
6. **main.py** — добавлен лог "BOT_TOKEN loaded: True/False"

---

## КРАТКАЯ АРХИТЕКТУРА

```
main.py (asyncio entry)
  ↓
load_settings() → .env.local/.env (utf-8-sig safe)
  ↓
init_db() → SQLite
  ↓
run_bot() → Dispatcher + Middlewares + Routers
  ├── start_router (start, menu, language, action_back)
  ├── help_router (help, settings)
  └── generate_router (action_generate → msg_photo → msg_prompt)
        ↓
      _parse_prefix() → workflow_name, prompt
        ↓
      WorkflowLoader.load() → нормализованный JSON
        ↓
      _inject_prompt() → ВСЕ текстовые поля
      _inject_seed_steps_cfg() → параметры
      _inject_resolution() → размер
        ↓
      ComfyUIClient.queue_prompt() → POST /prompt
        ↓
      ComfyUIClient.wait_for_result() → GET /history
        ↓
      message.answer_photo() / message.answer_document()
```

---

## СЛЕДУЮЩИЕ ШАГИ

1. Запустить бота: `.\.venv\Scripts\python.exe .\main.py`
2. Нажать "Генерировать" в Telegram
3. Ввести промпт (например, просто "кот")
4. Убедиться, что:
   - Промпт вставляется во ВСЕ CLIPTextEncode ноды (смотри logs/bot.log)
   - ComfyUI получает workflow и генерирует (~2 мин для FLUX DEV)
   - Результат возвращается в Telegram (фото или видео)

### Если что-то не работает:

- **"В workflow не найдено текстовое поле"** → проверь JSON структуру (есть ли `inputs.text`?)
- **"ComfyUI отклонил workflow"** → смотри лог ComfyUI, проверь модели в D:\ComfyUI\models\checkpoints
- **Timeout** → увеличь COMFY_TIMEOUT в .env.local

---

## UTF-8 SAFETY

Все файлы сохранены в UTF-8 (без BOM):
- `.editorconfig` → `charset = utf-8`
- config/settings.py → читает с `encoding="utf-8-sig"` (поддержка BOM)
- comfy/workflow_loader.py → читает JSON с `encoding="utf-8-sig"`
- bot/handlers/*.py → все русские строки в UTF-8
