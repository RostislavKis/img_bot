# 🔧 Краткая сводка изменений для HunyuanVideo I2V

## ФАЙЛЫ

### ✅ СОЗДАНЫ:
1. `utils/files.py` — утилиты для работы с файлами
2. `docs/HUNYUAN_I2V_IMPLEMENTATION.md` — документация

### ✅ ИЗМЕНЕНЫ:
1. `config/settings.py` — добавлены `comfy_input_dir` и `tmp_dir`
2. `bot/handlers/generate.py` — обновлены функции и обработчики

---

## КЛЮЧЕВЫЕ ИЗМЕНЕНИЯ

### 1. config/settings.py
```python
# ДОБАВЛЕНО (после comfy_output_dir):
comfy_input_dir: Path = Field(
    Path(r"D:\ComfyUI\input"),
    alias="COMFYUI_INPUT_DIR",
)

# ДОБАВЛЕНО (после logs_dir):
tmp_dir: Path = Field(
    BASE_DIR / "data" / "tmp",
    alias="BOT_TMP_DIR",
)
```

### 2. bot/handlers/generate.py — Импорты
```python
# ДОБАВЛЕНО (в начало):
from pathlib import Path
from utils.files import ensure_comfy_input_image, save_telegram_photo, validate_input_image
```

### 3. bot/handlers/generate.py — Новые функции (после _inject_hunyuan_i2v_settings)
```python
def _inject_hunyuan_input_image(workflow, image_filename):
    """Инжектит входное изображение в LoadImage ноду."""
    # См. полный код в файле

async def _generate_start_image(client, loader, prompt, settings, tmp_dir, comfy_input_dir):
    """Генерирует стартовое изображение для I2V."""
    # См. полный код в файле
```

### 4. bot/handlers/generate.py — Обработчик msg_photo
```python
# ИЗМЕНЕНО:
async def msg_photo(message, state, settings, t, lang):
    # Старый код:
    # await state.update_data(input_image_bytes=data, input_image_name=name)
    
    # Новый код:
    tmp_file = save_telegram_photo(photo_bytes, settings.tmp_dir)
    comfy_filename = ensure_comfy_input_image(tmp_file, settings.comfy_input_dir)
    await state.update_data(
        input_image_local_path=str(tmp_file),
        input_image_comfy_name=comfy_filename
    )
```

### 5. bot/handlers/generate.py — Обработчик msg_prompt (HunyuanVideo блок)
```python
# ДОБАВЛЕНО (в начале HunyuanVideo блока):
if workflow_name == "video_hunyuan15_720p_api":
    # 0) Получить или сгенерировать входное изображение
    input_image_comfy_name = st.get("input_image_comfy_name")
    
    if not input_image_comfy_name:
        # Автогенерация
        await status_msg.edit_text("⏳ Генерирую стартовый кадр...")
        client = ComfyUIClient(...)
        input_image_comfy_name = await _generate_start_image(...)
        await status_msg.edit_text("✓ Стартовый кадр готов — запускаю видео...")
    else:
        # Валидация
        if not validate_input_image(input_image_comfy_name, settings.comfy_input_dir):
            raise RuntimeError("Входное изображение невалидно")
    
    if not input_image_comfy_name:
        raise RuntimeError("Нужна стартовая картинка для I2V")
    
    # Инжект входного изображения
    _inject_hunyuan_input_image(wf, input_image_comfy_name)
    
    # Далее существующий код: _inject_hunyuan_i2v_prompts, presets, etc.
```

### 6. bot/handlers/generate.py — Для других workflow
```python
# ДОБАВЛЕНО (в else блок после _inject_prompt):
else:
    _inject_prompt(wf, prompt)
    
    # ... существующие настройки (flux_dev, schnell, sdxl) ...
    
    if client is None:
        client = ComfyUIClient(...)
    
    # Поддержка input image для старых workflow
    input_image_comfy_name = st.get("input_image_comfy_name")
    if input_image_comfy_name:
        if validate_input_image(input_image_comfy_name, settings.comfy_input_dir):
            ok = _inject_image_filename(wf, input_image_comfy_name)
            if ok:
                log.info("Input image injected")
    
    # ... существующий код: checkpoint selection, queue_prompt ...
```

### 7. bot/handlers/generate.py — Finally блок
```python
# ИЗМЕНЕНО (в finally):
# Старый код:
# await state.update_data(input_image_bytes=None, input_image_name=None, ...)

# Новый код:
await state.update_data(
    input_image_local_path=None,
    input_image_comfy_name=None,
    generation_mode=None
)
```

---

## БЫСТРЫЙ ЧЕКЛИСТ

### Перед запуском:
- [ ] Создать папку `C:\dev\img_bot\data\tmp`
- [ ] Проверить папку `D:\ComfyUI\input` (должна существовать)
- [ ] Добавить в `.env.local` (опционально):
  ```
  COMFYUI_INPUT_DIR=D:\ComfyUI\input
  BOT_TMP_DIR=C:\dev\img_bot\data\tmp
  ```

### Тестирование:
- [ ] Протестировать: отправить фото + "video: кот играет"
- [ ] Протестировать: отправить только "video: дракон летит"
- [ ] Проверить логи: `logs/bot.log`
- [ ] Проверить что файлы копируются в `D:\ComfyUI\input\`

---

## ВАЖНЫЕ НОТЫ

1. **Node 80** в `workflows/video_hunyuan15_720p_api.json` — это LoadImage нода
2. **Автогенерация** использует `flux_dev_fp8` для качественного стартового кадра
3. **Все пути** НЕ захардкожены — используются из config/settings
4. **Валидация** входного изображения предотвращает запуск с плейсхолдером
5. **Сообщения** пользователю понятные на каждом этапе

---

**Все изменения готовы к коммиту и использованию! 🚀**
