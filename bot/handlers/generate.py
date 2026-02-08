from __future__ import annotations

import os
import random
from io import BytesIO
from typing import Dict, List, Any, Optional, Tuple, NamedTuple

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.states import GenStates
from bot.keyboards.main_menu import get_back_keyboard, get_main_menu_keyboard
from comfy.client import ComfyUIClient
from comfy.workflow_loader import WorkflowLoader
from utils.logger import get_logger

router = Router()
log = get_logger(__name__)


class PromptTarget(NamedTuple):
    """Целевое текстовое поле для инжекта промпта."""
    node_id: str
    class_type: str
    key: str


PROMPT_KEYS = (
    "text",
    "prompt",
    "positive",
    "positive_prompt",
    "prompt_text",
    "text_g",
    "text_l",
    "clip_text",
    "conditioning_text",
)

NEG_KEYS_HINTS = ("negative", "neg", "bad", "undesired")


def _parse_prefix(text: str, default_mode: str = "dev") -> Tuple[str, str]:
    """
    Разбирает префиксы в тексте и возвращает (workflow_name, clean_prompt).
    
    Поддерживаемые префиксы:
    • dev: / fluxdev:        → flux_dev_fp8 (качество FLUX)
    • schnell: / fast:       → flux_schnell_fp8 (быстро FLUX)
    • xl: / photo:           → sdxl_base_refiner (фото-реализм SDXL)
    • video: / vid:          → video_sd15 (видео AnimateDiff SD1.5)
    • edit:                  → image_edit (редактирование фото)
    
    default_mode может быть: "dev", "schnell", "xl", "video", "edit"
    Если default_mode="schnell" и без префикса → flux_schnell_fp8.
    """
    t = (text or "").strip()
    low = t.lower()

    def cut(pfx: str) -> str:
        return t[len(pfx):].strip()

    # Video (HunyuanVideo 1.5 - 720p API format)
    if low.startswith("video:"):
        return "video_hunyuan15_720p_api", cut("video:")
    if low.startswith("vid:"):
        return "video_hunyuan15_720p_api", cut("vid:")

    # Edit
    if low.startswith("edit:"):
        return "image_edit", cut("edit:")

    # FLUX Schnell (быстро)
    if low.startswith("schnell:"):
        return "flux_schnell_fp8", cut("schnell:")
    if low.startswith("fast:"):
        return "flux_schnell_fp8", cut("fast:")

    # FLUX Dev (качество)
    if low.startswith("fluxdev:"):
        return "flux_dev_fp8", cut("fluxdev:")
    if low.startswith("dev:"):
        return "flux_dev_fp8", cut("dev:")

    # SDXL (фото-реализм)
    if low.startswith("xl:"):
        return "sdxl_base_refiner", cut("xl:")
    if low.startswith("photo:"):
        return "sdxl_base_refiner", cut("photo:")

    # Default
    default_workflow = {
        "dev": "flux_dev_fp8",
        "schnell": "flux_schnell_fp8",
        "xl": "sdxl_base_refiner",
        "video": "video_hunyuan15_720p_api",
        "edit": "image_edit",
    }.get(default_mode, "flux_dev_fp8")

    log.debug(f"Using default workflow: {default_workflow} (mode={default_mode})")
    return default_workflow, t


def _is_negative_field(key: str) -> bool:
    """Проверяет, относится ли ключ к negative/conditioning."""
    k = (key or "").lower()
    return any(x in k for x in NEG_KEYS_HINTS)


def _find_prompt_targets(workflow: Dict[str, Any]) -> List[PromptTarget]:
    """
    Сканирует workflow и находит ВСЕ текстовые поля для инжекта промпта.
    
    Возвращает список PromptTarget (node_id, class_type, key).
    
    Логика:
    1) Фаза 1: ищет inputs с известными PROMPT_KEYS
    2) Фаза 2 (fallback): поля с "prompt" или "text" в названии
    3) ИСКЛЮЧАЕТ: ноды с "negative" в key И CLIPTextEncode с индексом >= 3
    """
    targets: List[PromptTarget] = []
    
    # Фаза 1: ищем известные PROMPT_KEYS
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        
        class_type = str(node.get("class_type") or "unknown")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        
        for prompt_key in PROMPT_KEYS:
            if prompt_key in inputs and isinstance(inputs.get(prompt_key), str):
                if not _is_negative_field(prompt_key):
                    target = PromptTarget(node_id=str(node_id), class_type=class_type, key=prompt_key)
                    targets.append(target)
    
    # Фаза 2: fallback — ищем "prompt" или "text" в названии, исключая негативные
    if not targets:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            
            class_type = str(node.get("class_type") or "unknown")
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            
            # ВАЖНО: пропускаем CLIPTextEncode с индексом >= 3 (вторая и выше = негатив)
            node_idx = int(node_id) if node_id.isdigit() else 0
            if class_type == "CLIPTextEncode" and node_idx >= 3:
                log.debug(f"Skipping node {node_id} (CLIPTextEncode negative)")
                continue

            for k, v in inputs.items():
                if not isinstance(v, str):
                    continue
                lk = str(k).lower()
                if _is_negative_field(lk):
                    continue
                if ("prompt" in lk) or ("text" in lk):
                    target = PromptTarget(node_id=str(node_id), class_type=class_type, key=str(k))
                    targets.append(target)
    
    return sorted(targets, key=lambda t: (t.node_id, t.key))


def _inject_prompt(workflow: Dict[str, Any], prompt: str) -> None:
    """
    Вставляет prompt во ВСЕ найденные текстовые поля workflow.
    
    Логирует КАЖДОЕ обновление:
    ✓ inject node=6 class=CLIPTextEncode key=text len=109
    
    Если ничего не найдено (updated==0) — выводит диагностическую таблицу.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Пустой prompt")

    targets = _find_prompt_targets(workflow)
    updated = 0
    
    # Вставляем в найденные цели
    for target in targets:
        node = workflow.get(target.node_id, {})
        inputs = node.get("inputs", {})
        
        if target.key in inputs:
            inputs[target.key] = prompt
            updated += 1
            log.info(f"✓ inject node={target.node_id} class={target.class_type} key={target.key} len={len(prompt)}")
    
    if updated == 0:
        # Диагностика: выводим таблицу нод и их string-ключей
        log.warning("⚠️ Инжект промпта не найден! Построена диагностическая таблица:")
        
        # Собираем список всех class_type и ключей
        table_rows = []
        all_class_types = set()
        
        for node_id, node in sorted(workflow.items()):
            if not isinstance(node, dict):
                continue
            
            class_type = str(node.get("class_type") or "unknown")
            all_class_types.add(class_type)
            
            inputs = node.get("inputs", {})
            string_keys = []
            
            for k, v in inputs.items():
                if isinstance(v, str):
                    string_keys.append(str(k))
            
            table_rows.append({
                "node_id": str(node_id),
                "class_type": class_type,
                "string_keys": ", ".join(string_keys) if string_keys else "(нет)",
            })
        
        # Выводим таблицу
        log.warning("=" * 90)
        log.warning(f"{'Node ID':<10} {'Class Type':<25} {'String Keys in inputs':<50}")
        log.warning("-" * 90)
        for row in table_rows:
            log.warning(f"{row['node_id']:<10} {row['class_type']:<25} {row['string_keys']:<50}")
        log.warning("=" * 90)
        
        # Список всех class_type в workflow
        log.warning(f"Все class_type в workflow: {', '.join(sorted(all_class_types))}")
        log.warning(f"Известные PROMPT_KEYS: {', '.join(PROMPT_KEYS)}")
        
        raise ValueError(
            f"В workflow не найдено текстовое поле для промпта.\n"
            f"Смотри логи для диагностической таблицы нод."
        )


def _inject_seed_steps_cfg(workflow: Dict[str, Any], *, steps: Optional[int] = None, cfg: Optional[float] = None) -> None:
    """Мягко вставляет seed/steps/cfg, только если ключи существуют."""
    seed = random.randint(1, 2_000_000_000)
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        if "seed" in inputs:
            try:
                inputs["seed"] = int(seed)
            except Exception:
                pass

        if steps is not None and "steps" in inputs:
            try:
                inputs["steps"] = int(steps)
            except Exception:
                pass

        if cfg is not None:
            for k in ("cfg", "guidance", "guidance_scale"):
                if k in inputs:
                    try:
                        inputs[k] = float(cfg)
                    except Exception:
                        pass


def _inject_resolution(workflow: Dict[str, Any], *, width: Optional[int] = None, height: Optional[int] = None) -> None:
    """Мягко вставляет width/height, только если ключи существуют."""
    if width is None and height is None:
        return
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if width is not None and "width" in inputs:
            try:
                inputs["width"] = int(width)
            except Exception:
                pass
        if height is not None and "height" in inputs:
            try:
                inputs["height"] = int(height)
            except Exception:
                pass


def _find_inputs(workflow: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Находит все inputs-dict, содержащие конкретный ключ."""
    out: List[Dict[str, Any]] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and key in inputs:
            out.append(inputs)
    return out


def _get_current_value(workflow: Dict[str, Any], key: str) -> str:
    """Получает первое значение конкретного ключа из всех нод."""
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and key in inputs:
            return str(inputs.get(key) or "").strip()
    return ""


def _choose_by_hint(available: List[str], hint: str) -> Optional[str]:
    """Выбирает элемент из списка по подстроке (case-insensitive)."""
    h = (hint or "").lower()
    for n in available:
        if h in n.lower():
            return n
    return None


def _choose_checkpoint(available: List[str], workflow_name: str, current: str) -> str:
    """
    Выбирает checkpoint по названию workflow.
    
    Стратегия:
    1) Если workflow уже содержит valid checkpoint — не трогаем
    2) HunyuanVideo → НЕ использует checkpoint, пропускаем
    3) video_sd15 → ТОЛЬКО SD1.5 (запретить SDXL)
    4) FLUX workflows → ищем flux1-dev или flux1-schnell
    5) SDXL → ищем RealVisXL или JuggerнаутXL
    6) Fallback → первый в списке
    """
    if not available:
        raise RuntimeError("В ComfyUI нет ни одного checkpoint (models\\checkpoints пуст).")

    if current and current in available:
        log.debug(f"Checkpoint уже задан в workflow: {current}")
        return current

    w = (workflow_name or "").lower()

    # HunyuanVideo (НЕ использует checkpoint)
    if "hunyuan" in w:
        log.info(f"HunyuanVideo workflow НЕ требует checkpoint выбора")
        return ""

    # VIDEO SD1.5 (жёсткий выбор только SD1.5, НЕ SDXL)
    if "video_sd15" in w or workflow_name == "video_sd15":
        sd15_candidates = [
            c for c in available
            if (("sd15" in c.lower()) or ("sd_15" in c.lower()) or ("1.5" in c.lower()) or ("v1-5" in c.lower()))
            and ("xl" not in c.lower()) and ("sdxl" not in c.lower())
        ]
        if sd15_candidates:
            pick = sd15_candidates[0]
            log.info(f"video_sd15: Selected SD1.5 checkpoint: {pick}")
            return pick
        else:
            available_list = ", ".join(available)
            raise RuntimeError(
                f"video_sd15 требует SD1.5 checkpoint, но найдены только: {available_list}.\n"
                f"Переименуй/добавь SD1.5 checkpoint с 'sd15', '1.5' или 'v1-5' в названии."
            )

    # FLUX Dev (качество)
    if "flux_dev" in w or (w == "flux_dev_fp8"):
        pick = _choose_by_hint(available, "flux1-dev") or _choose_by_hint(available, "dev-fp8")
        if pick:
            log.debug(f"FLUX Dev selected: {pick}")
            return pick

    # FLUX Schnell (быстро)
    if "flux_schnell" in w or (w == "flux_schnell_fp8"):
        pick = _choose_by_hint(available, "flux1-schnell") or _choose_by_hint(available, "schnell-fp8")
        if pick:
            log.debug(f"FLUX Schnell selected: {pick}")
            return pick

    # SDXL (фото-реализм)
    if "sdxl" in w or "photo" in w or "xl" in w:
        # Приоритет: RealVisXL → JuggerнаутXL → SD_XL_base → первый
        pick = (
            _choose_by_hint(available, "RealVisXL")
            or _choose_by_hint(available, "JuggernautXL")
            or _choose_by_hint(available, "sd_xl_base")
            or available[0]
        )
        log.debug(f"SDXL selected: {pick}")
        return pick

    # Fallback: первый в списке
    log.warning(f"No specific checkpoint hint matched for {workflow_name}, using first available: {available[0]}")
    return available[0]


def _choose_unet(available: List[str], workflow_name: str, current: str) -> str:
    """Выбирает UNET по названию workflow."""
    if not available:
        raise RuntimeError("В ComfyUI нет ни одного UNET (UNETLoader пуст).")

    if current and current in available:
        return current

    w = (workflow_name or "").lower()
    if "kontext" in w:
        return _choose_by_hint(available, "kontext") or available[0]
    if "fill" in w:
        return _choose_by_hint(available, "fill") or available[0]
    if "dev" in w or "flux_dev" in w:
        return _choose_by_hint(available, "dev") or available[0]
    return _choose_by_hint(available, "schnell") or available[0]


def _inject_image_filename(workflow: Dict[str, Any], comfy_input_name: str) -> bool:
    """Подставляет имя загруженного изображения в LoadImage nodes."""
    injected = False
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if "image" in inputs and isinstance(inputs.get("image"), str):
            if "LoadImage" in class_type or class_type.lower() == "loadimage":
                inputs["image"] = comfy_input_name
                injected = True

    if not injected:
        targets = _find_inputs(workflow, "image")
        for inp in targets:
            if isinstance(inp.get("image"), str):
                inp["image"] = comfy_input_name
                injected = True
                break

    return injected


# ============================================================================
# CALLBACK HANDLERS
# ============================================================================

@router.callback_query(F.data == "action_generate_dev")
async def cb_generate_dev(call: CallbackQuery, state: FSMContext, t, lang):
    """КАРТИНКА (DEV) — качество"""
    await call.answer()
    await state.update_data(generation_mode="dev")
    await state.set_state(GenStates.waiting_prompt)
    msg = "📸 <b>Режим: Картинка (DEV)</b>\n\n"
    msg += "Введи промпт одним сообщением.\n"
    msg += "Лучшее качество, ~2 минуты.\n\n"
    msg += "Пример:\n"
    msg += '<code>красивая девушка в аниме-стиле с голубыми глазами</code>'
    await call.message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")


@router.callback_query(F.data == "action_generate_schnell")
async def cb_generate_schnell(call: CallbackQuery, state: FSMContext, t, lang):
    """БЫСТРО — скорость"""
    await call.answer()
    await state.update_data(generation_mode="schnell")
    await state.set_state(GenStates.waiting_prompt)
    msg = "⚡ <b>Режим: Быстро (Schnell)</b>\n\n"
    msg += "Введи промпт одним сообщением.\n"
    msg += "Хорошее качество, ~30 секунд.\n\n"
    msg += "Пример:\n"
    msg += '<code>кот спит на подушке</code>'
    await call.message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")


@router.callback_query(F.data == "action_generate_video")
async def cb_generate_video(call: CallbackQuery, state: FSMContext, t, lang):
    """ВИДЕО — AnimateDiff"""
    await call.answer()
    await state.update_data(generation_mode="video")
    await state.set_state(GenStates.waiting_prompt)
    msg = "🎬 <b>Режим: Видео</b>\n\n"
    msg += "Введи промпт для анимации.\n"
    msg += "16 фреймов GIF, ~1-2 минуты.\n\n"
    msg += "Пример:\n"
    msg += '<code>кот прыгает через забор, солнечный день</code>'
    await call.message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")


@router.callback_query(F.data == "action_generate_edit")
async def cb_generate_edit(call: CallbackQuery, state: FSMContext, t, lang):
    """РЕДАКТИРОВАНИЕ — inpainting/image edit"""
    await call.answer()
    await state.update_data(generation_mode="edit")
    msg = "✏️ <b>Режим: Редактирование</b>\n\n"
    msg += "1) Отправь своё фото\n"
    msg += "2) Напиши, что изменить\n\n"
    msg += "Примеры:\n"
    msg += '<code>Измени фон на пляж</code>\n'
    msg += '<code>Добавь солнечные очки</code>'
    await call.message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")


# ============================================================================
# MESSAGE HANDLERS
# ============================================================================

@router.message(F.photo)
async def msg_photo(message: Message, state: FSMContext, settings, t, lang):
    """Получаем фото и сохраняем в state для следующего промпта."""
    try:
        ph = message.photo[-1]
        tg_file = await message.bot.get_file(ph.file_id)
        buf = BytesIO()
        await message.bot.download_file(tg_file.file_path, destination=buf)
        data = buf.getvalue()

        ext = os.path.splitext(tg_file.file_path or "")[1].strip().lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        name = f"tg_{ph.file_unique_id}{ext}"

        await state.update_data(input_image_bytes=data, input_image_name=name)
        await state.set_state(GenStates.waiting_prompt)

        msg = "🖼 Фото получено.\n"
        msg += "Теперь напиши промпт:\n\n"
        msg += "• Для редактирования: <code>Добавь размытый фон</code>\n"
        msg += "• Для видео-анимации: <code>video: кот прыгает</code>"
        await message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")
    except Exception as e:
        log.exception(f"Photo receive failed: {e}")
        await message.answer(
            "❌ Не смог принять фото. Попробуй ещё раз.",
            reply_markup=get_main_menu_keyboard(lang),
        )


@router.message(GenStates.waiting_prompt, F.text)
async def msg_prompt(message: Message, state: FSMContext, settings, t, lang):
    """Основной обработчик генерации: промпт → workflow → ComfyUI → результат."""
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("✍️ Введите промт одним сообщением.", reply_markup=get_back_keyboard(lang))
        return

    if raw.startswith("/"):
        await state.clear()
        await message.answer("🏠 Главное меню:", reply_markup=get_main_menu_keyboard(lang))
        return

    st = await state.get_data()
    generation_mode = st.get("generation_mode", "dev")
    input_image_bytes = st.get("input_image_bytes")
    input_image_name = st.get("input_image_name") or "input.jpg"

    # Разбор префикса с учётом режима
    workflow_name, prompt = _parse_prefix(raw, default_mode=generation_mode)

    if not prompt:
        await message.answer("✍️ Введите промпт одним сообщением.", reply_markup=get_back_keyboard(lang))
        return

    # Логика выбора workflow при наличии фото (входного изображения)
    if input_image_bytes:
        # Если загружено фото и юзер не указал префикса:
        if workflow_name == "flux_dev_fp8" and generation_mode == "dev":
            # Переходим на SDXL для обработки фото (режим "Редактирование")
            workflow_name = "sdxl_base_refiner"
            log.info(f"Фото загружено: переключаемся на workflow={workflow_name}")
        elif workflow_name == "flux_schnell_fp8" and generation_mode == "schnell":
            # Schnell для фото? Переходим на SDXL
            workflow_name = "sdxl_base_refiner"
            log.info(f"Фото загружено (fast mode): переключаемся на workflow={workflow_name}")
        elif workflow_name == "video_default":
            # Видео с фото? Ок, может быть animation из изображения
            log.info(f"Фото загружено + video mode: используем video_default с входным изображением")
        # Если указан xl: или sdxl — не меняем
        # Если указан edit: — используем image_edit если он есть, иначе sdxl_base_refiner

    await state.set_state(GenStates.running)
    status_msg = await message.answer("⏳ Обработка...", parse_mode="HTML")

    client: Optional[ComfyUIClient] = None
    try:
        loader = WorkflowLoader(settings.workflows_dir)
        wf = loader.load(workflow_name)

        log.info(f"Workflow loaded: {workflow_name}, nodes count: {len(wf)}")

        # Тюнинг параметров по умолчанию
        if workflow_name == "video_hunyuan15_720p_api":
            # HunyuanVideo 1.5 I2V специальная обработка (API format)
            log.info(f"HunyuanVideo 1.5 I2V API workflow detected")
            
            # Инжект промпта строго в node 44 (CLIPTextEncode Positive)
            if "44" in wf and wf["44"].get("class_type") == "CLIPTextEncode":
                wf["44"].setdefault("inputs", {})["text"] = prompt
                log.info(f"✓ inject HunyuanVideo positive prompt: node=44 len={len(prompt)}")
            
            # Негативный промпт в node 93 - пустая строка
            if "93" in wf and wf["93"].get("class_type") == "CLIPTextEncode":
                wf["93"].setdefault("inputs", {})["text"] = ""
                log.info(f"✓ inject HunyuanVideo negative prompt: node=93 (empty)")
            
            # Настройка параметров HunyuanVideo15ImageToVideo
            for node_id, node in wf.items():
                if node.get("class_type") == "HunyuanVideo15ImageToVideo":
                    inputs = node.setdefault("inputs", {})
                    inputs["num_frames"] = 49  # Уменьшаем с 121 до 49 кадров
                    log.info(f"✓ HunyuanVideo num_frames set to 49 (node={node_id})")
            
            # Настройка FPS в CreateVideo
            for node_id, node in wf.items():
                if node.get("class_type") == "CreateVideo":
                    inputs = node.setdefault("inputs", {})
                    inputs["fps"] = 16  # Уменьшаем с 24 до 16 FPS
                    log.info(f"✓ CreateVideo FPS set to 16 (node={node_id})")
            
            # Настройка weight_dtype для UNETLoader (fp8_e4m3fn_fast)
            for node_id, node in wf.items():
                if node.get("class_type") == "UNETLoader":
                    inputs = node.setdefault("inputs", {})
                    inputs["weight_dtype"] = "fp8_e4m3fn_fast"
                    log.info(f"✓ UNETLoader weight_dtype set to fp8_e4m3fn_fast (node={node_id})")
            
            # Установка seed если есть noise_seed input
            for node_id, node in wf.items():
                inputs = node.setdefault("inputs", {})
                if "noise_seed" in inputs:
                    seed = random.randint(1, 2_000_000_000)
                    inputs["noise_seed"] = seed
                    log.info(f"✓ HunyuanVideo noise_seed set to {seed} (node={node_id})")
        
        else:
            # Для всех остальных workflow — используем стандартный инжект промпта
            _inject_prompt(wf, prompt)
            
            if workflow_name == "flux_dev_fp8":
                _inject_seed_steps_cfg(wf, steps=28, cfg=1.0)
                _inject_resolution(wf, width=1024, height=1024)
            elif workflow_name == "flux_schnell_fp8":
                _inject_seed_steps_cfg(wf, steps=4, cfg=1.0)
                _inject_resolution(wf, width=1024, height=1024)
            elif workflow_name == "sdxl_base_refiner":
                _inject_seed_steps_cfg(wf, steps=20, cfg=7.5)
                _inject_resolution(wf, width=1024, height=1024)
            elif workflow_name == "video_default" or workflow_name == "video_sd15":
                _inject_seed_steps_cfg(wf, steps=20, cfg=7.0)
                _inject_resolution(wf, width=512, height=512)

        client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)

        # Если есть фото — загружаем в ComfyUI
        if input_image_bytes:
            up = await client.upload_image(bytes(input_image_bytes), str(input_image_name))
            comfy_name = up.get("name") or str(input_image_name)
            ok = _inject_image_filename(wf, comfy_name)
            if not ok:
                log.warning(f"Workflow {workflow_name} не поддерживает входное изображение")
                raise RuntimeError(
                    "Этот workflow не поддерживает входное изображение "
                    "(нет LoadImage / inputs.image)."
                )
            log.info(f"Image uploaded: {comfy_name}")

        # Auto-select: checkpoint и UNET - НЕ для HunyuanVideo
        if workflow_name != "video_hunyuan15_720p_api":
            ckpt_inputs = _find_inputs(wf, "ckpt_name")
            if ckpt_inputs:
                available = await client.get_checkpoint_names()
                if not available:
                    raise RuntimeError("ComfyUI: нет checkpoints в models/checkpoints")
                current = _get_current_value(wf, "ckpt_name")
                chosen = _choose_checkpoint(available, workflow_name, current)
                if chosen:  # Для HunyuanVideo _choose_checkpoint возвращает ""
                    for inp in ckpt_inputs:
                        inp["ckpt_name"] = chosen
                    log.info(f"Workflow={workflow_name} Checkpoint chosen: {chosen}")

            unet_inputs = _find_inputs(wf, "unet_name")
            if unet_inputs:
                available_u = await client.get_unet_names()
                current_u = _get_current_value(wf, "unet_name")
                chosen_u = _choose_unet(available_u, workflow_name, current_u)
                for inp in unet_inputs:
                    inp["unet_name"] = chosen_u
                log.info(f"Workflow={workflow_name} UNET chosen: {chosen_u}")
        else:
            log.info(f"HunyuanVideo API: skipping checkpoint/UNET auto-select (using workflow defaults)")

        # Отправляем в ComfyUI
        pid = await client.queue_prompt(wf)
        if not pid:
            err = (client.last_error or "ComfyUI отклонил workflow").strip()[:800]
            log.error(f"ComfyUI rejected workflow: {err}")
            raise RuntimeError(err)

        log.info(f"Prompt queued: {pid}")

        # Ждём результата
        result = await client.wait_for_result(pid, timeout=settings.comfy_timeout)
        if not result:
            raise RuntimeError(
                "Timeout: ComfyUI не вернул output (проверь очередь/ошибки в ComfyUI)"
            )

        filename = str(result["filename"])
        out_bytes = bytes(result["bytes"])
        mime = str(result.get("mime") or "application/octet-stream")

        log.info(f"Result received: {filename}, size: {len(out_bytes)} bytes, mime: {mime}")

        caption = "✅ Готово!"
        
        # Определяем тип отправки по mime и расширению
        is_video = mime.startswith("video/") or filename.lower().endswith(('.mp4', '.webm', '.mov'))
        is_gif = mime.startswith("image/gif") or filename.lower().endswith('.gif')
        is_image = mime.startswith("image/") and not is_gif
        
        if is_video and len(out_bytes) <= 50 * 1024 * 1024:
            # Отправляем как video (для HunyuanVideo mp4)
            await message.answer_video(
                BufferedInputFile(out_bytes, filename=filename),
                caption=caption,
                supports_streaming=True
            )
        elif is_image and len(out_bytes) <= 10 * 1024 * 1024:
            await message.answer_photo(BufferedInputFile(out_bytes, filename=filename), caption=caption)
        elif is_gif or is_video:
            # GIF или большое видео - как document
            await message.answer_document(BufferedInputFile(out_bytes, filename=filename), caption=caption)
        else:
            await message.answer_document(BufferedInputFile(out_bytes, filename=filename), caption=caption)

        await message.answer("🏠 Главное меню:", reply_markup=get_main_menu_keyboard(lang))
        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        log.exception(f"Generation failed: {e}")
        err_text = f"❌ Ошибка: {e}"
        try:
            await status_msg.edit_text(err_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer(err_text)
        await message.answer("🏠 Главное меню:", reply_markup=get_main_menu_keyboard(lang))

    finally:
        if client is not None:
            await client.close()
        try:
            await state.update_data(input_image_bytes=None, input_image_name=None, generation_mode=None)
        except Exception:
            pass
        await state.clear()


