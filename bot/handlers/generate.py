from __future__ import annotations

import asyncio
import json
import os
import random
import re
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, NamedTuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.states import GenStates
from bot.keyboards.main_menu import get_back_keyboard, get_main_menu_keyboard
from comfy.client import ComfyUIClient
from comfy.workflow_loader import WorkflowLoader
from utils.logger import get_logger
from utils.files import ensure_comfy_input_image, save_telegram_photo, validate_input_image

router = Router()
log = get_logger(__name__)

_TRANSLATE_ENABLED = os.getenv("PROMPT_TRANSLATE", "1") != "0"
_CYR = re.compile(r"[А-Яа-яЁё]")
_translate_cache: dict[str, str] = {}
_translate_warned = False


# Workflow constants
WORKFLOW_IMAGE_DEFAULT = "image_default"
WORKFLOW_IMAGE_REFINER = "sdxl_base_refiner"
WORKFLOW_FLUX_DEV_IMG2IMG = "flux_dev_fp8_img2img"
WORKFLOW_FLUX_SCHNELL_IMG2IMG = "flux_schnell_fp8_img2img"


def _translate_ru_to_en_if_needed(text: str) -> str:
    global _translate_warned
    if not _TRANSLATE_ENABLED:
        return text
    if not text or not _CYR.search(text):
        return text
    if text in _translate_cache:
        return _translate_cache[text]
    try:
        from argostranslate import translate as _argos_translate
        out = _argos_translate.translate(text, "ru", "en")
        out = out.strip() if isinstance(out, str) else text
        _translate_cache[text] = out
        return out
    except Exception:
        if not _translate_warned:
            _translate_warned = True
            log.warning("PROMPT_TRANSLATE включен, но argostranslate недоступен/не настроен — отправляю RU как есть")
        return text


# -----------------------------
# HunyuanVideo VRAM-aware presets + auto-fallback
# -----------------------------
HUNYUAN_PRESETS = [
    # 360p (fast mode)
    dict(name="360p", width=640, height=360, num_frames=25, fps=12, steps=12, cfg=5.5, batch_size=1, weight_dtype="fp8_e4m3fn_fast"),
    # 480p (quality mode default)
    dict(name="480p", width=854, height=480, num_frames=33, fps=12, steps=18, cfg=6.2, batch_size=1, weight_dtype="fp8_e4m3fn_fast"),
    # 720p (requires high VRAM)
    dict(name="720p", width=1280, height=720, num_frames=49, fps=16, steps=20, cfg=6.2, batch_size=1, weight_dtype="fp8_e4m3fn_fast"),
]

def _is_oom_error(err: str | None) -> bool:
    """Проверяет, является ли ошибка OOM."""
    if not err:
        return False
    e = err.lower()
    return ("out of memory" in e) or ("cuda oom" in e) or ("allocation on device" in e) or ("oom" in e)

def _pick_hunyuan_preset_index(system_stats: dict | None) -> int:
    """
    Выбирает стартовый пресет по VRAM (если есть данные).
    Возвращает индекс в HUNYUAN_PRESETS.
    """
    try:
        sys_part = (system_stats or {}).get("system") or {}
        devs = (system_stats or {}).get("devices") or (system_stats or {}).get("device") or []

        cuda_dev = None
        if isinstance(devs, list):
            for d in devs:
                if str(d.get("type", "")).lower().startswith("cuda") or str(d.get("name", "")).lower().startswith("cuda"):
                    cuda_dev = d
                    break
            if cuda_dev is None and devs:
                cuda_dev = devs[0]
        elif isinstance(devs, dict):
            cuda_dev = devs

        vram_total = None
        vram_free = None
        for src in [cuda_dev or {}, sys_part]:
            for k in ["vram_total", "vram_total_mb", "gpu_vram_total", "total_vram", "total_vram_mb"]:
                if k in src:
                    vram_total = src.get(k)
                    break
            for k in ["vram_free", "vram_free_mb", "gpu_vram_free", "free_vram", "free_vram_mb"]:
                if k in src:
                    vram_free = src.get(k)
                    break

        def _to_mb(x):
            if x is None:
                return None
            if isinstance(x, (int, float)):
                # иногда это bytes
                if x > 1024 * 1024 * 1024:
                    return int(x / (1024 * 1024))
                return int(x)
            return None

        vram_total_mb = _to_mb(vram_total)
        vram_free_mb = _to_mb(vram_free)

        if not vram_total_mb and not vram_free_mb:
            return 0

        budget = vram_free_mb or vram_total_mb
        if budget is None:
            return 0

        # Пороги VRAM для выбора пресета
        if budget >= 11000:
            return 2  # 720p
        if budget >= 8500:
            return 1  # 480p
        return 0      # 360p
    except Exception:
        return 0

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Показывает состояние ComfyUI и очереди."""
    client = getattr(message.bot, "comfy_client", None)
    loader = getattr(message.bot, "workflow_loader", None)

    if client is None:
        await message.answer("❌ ComfyUI client не инициализирован в боте.")
        return

    try:
        stats = await client.system_stats()
    except Exception as e:
        await message.answer(f"❌ Не смогу получить /system_stats: {e}")
        return

    try:
        q = await client.get_queue_status()
    except Exception as e:
        q = {"error": str(e)}

    sys_part = (stats or {}).get("system") or {}
    comfy_ver = sys_part.get("comfyui_version", "?")
    py_ver = sys_part.get("python_version", "?")
    torch_ver = sys_part.get("pytorch_version", "?")

    q_running = len((q or {}).get("queue_running") or []) if isinstance(q, dict) else "?"
    q_pending = len((q or {}).get("queue_pending") or []) if isinstance(q, dict) else "?"

    wf_count = None
    if loader is not None:
        wf_count = len(loader.get_available_workflows()) if hasattr(loader, "get_available_workflows") else None

    text = (
        f"**ComfyUI:** {comfy_ver}\n"
        f"**Python:** {py_ver}\n"
        f"**PyTorch:** {torch_ver}\n"
        f"**Queue:** running={q_running}, pending={q_pending}\n"
    )
    if wf_count:
        text += f"**Workflows indexed:** {wf_count}\n"

    devs = (stats or {}).get("devices")
    if devs:
        try:
            if isinstance(devs, list) and devs:
                d0 = devs[0]
                name = d0.get("name") or d0.get("device") or "device0"
                vram_t = d0.get("vram_total") or d0.get("vram_total_mb")
                vram_f = d0.get("vram_free") or d0.get("vram_free_mb")
                if vram_t or vram_f:
                    text += f"**GPU:** {name} (vram_total={vram_t}, vram_free={vram_f})\n"
        except Exception:
            pass

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("i2v"))
async def cmd_i2v(message: Message, state: FSMContext, t, lang) -> None:
    """Режим I2V: фото + промпт без необходимости prefix video:."""
    await state.update_data(generation_mode="video", force_video=True, video_quality=False)
    await state.set_state(GenStates.waiting_prompt)
    msg = "🎬 <b>I2V режим</b>\n\n"
    msg += "Отправь фото и промпт одним сообщением (или сначала фото, затем текст).\n"
    msg += "Пример: <code>кот прыгает через забор</code>"
    await message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")


@router.message(Command("videoq"))
async def cmd_videoq(message: Message, state: FSMContext, t, lang) -> None:
    """Quality mode для HunyuanVideo (предпочитает 480p)."""
    await state.update_data(generation_mode="video", force_video=True, video_quality=True)
    await state.set_state(GenStates.waiting_prompt)
    msg = "🎬 <b>Видео QUALITY</b>\n\n"
    msg += "Напиши промпт (можно без prefix).\n"
    msg += "Пример: <code>питбуль бежит по пляжу</code>"
    await message.answer(msg, reply_markup=get_back_keyboard(lang), parse_mode="HTML")


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
    • video: / vid:          → video_hunyuan15_720p_api (видео)
    • edit:                  → image_default (редактирование фото)
    
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

    # Edit (теперь через image_default)
    if low.startswith("edit:"):
        return "image_default", cut("edit:")

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
        "edit": "image_default",
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


def _inject_prompt(workflow: Dict[str, Any], prompt: str, negative_prompt: str = "") -> None:
    """
    Вставляет prompt и опциональный negative_prompt во найденные текстовые поля workflow.
    
    Логирует КАЖДОЕ обновление:
    ✓ inject node=6 class=CLIPTextEncode key=text len=109
    
    Если ничего не найдено (updated==0) — выводит диагностическую таблицу.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Пустой prompt")

    targets = _find_prompt_targets(workflow)
    updated = 0
    negative_updated = 0
    
    # Вставляем в найденные цели
    for target in targets:
        node = workflow.get(target.node_id, {})
        inputs = node.get("inputs", {})
        
        if target.key in inputs:
            # Проверяем если это negative поле
            if _is_negative_field(target.key) and negative_prompt:
                inputs[target.key] = negative_prompt
                negative_updated += 1
                log.info(f"✓ inject negative node={target.node_id} class={target.class_type} key={target.key} len={len(negative_prompt)}")
            elif not _is_negative_field(target.key):
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


def _inject_negative_prompt(workflow: Dict[str, Any], negative_prompt: str) -> None:
    """Вставляет negative prompt в поля, похожие на negative/neg/bad/undesired."""
    negative_prompt = (negative_prompt or "").strip()
    if not negative_prompt:
        return

    updated = 0
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for k, v in inputs.items():
            if not isinstance(v, str):
                continue
            if _is_negative_field(str(k)):
                inputs[k] = negative_prompt
                updated += 1

    if updated:
        log.info(f"✓ inject negative prompt into {updated} fields")


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
    updated = 0
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if width is not None and "width" in inputs:
            try:
                inputs["width"] = int(width)
                updated += 1
            except Exception:

                pass
        if height is not None and "height" in inputs:
            try:
                inputs["height"] = int(height)
                updated += 1
            except Exception:
                pass
    if updated == 0:
        log.warning("No width/height fields found in workflow; consider adding ImageScale node.")


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


def _inject_input_image(workflow: Dict[str, Any], file_name: str) -> None:
    """Пытается найти LoadImage node и заменить inputs.image."""
    for node_id, node in workflow.items():
        try:
            cls = str(node.get("class_type") or "")
            if cls == "LoadImage":
                node["inputs"]["image"] = file_name
                log.info(f"✓ inject input image: node={node_id} file={file_name}")
                return
        except Exception:
            pass


def _inject_mask_image(workflow: Dict[str, Any], mask_file: str) -> bool:
    """
    Пытаемся вставить маску в workflow.
    Возвращает True если удалось найти хоть один подходящий input.
    """
    injected = False
    for node_id, node in workflow.items():
        try:
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for k in ("mask", "image_mask", "mask_image", "inpaint_mask"):
                if k in inputs and isinstance(inputs[k], str):
                    inputs[k] = mask_file
                    injected = True
                    log.info(f"✓ inject mask image: node={node_id} key={k} file={mask_file}")
        except Exception:
            pass
    return injected


def _inject_denoise(workflow: Dict[str, Any], *, denoise: float | None) -> None:
    if denoise is None:
        return
    for _, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if "denoise" in inputs:
            try:
                inputs["denoise"] = float(denoise)
            except Exception:
                pass


async def _send_result_to_telegram(message: Message, *, out_bytes: bytes, filename: str, mime: str) -> None:
    """
    Надёжная отправка результата:
    - несколько попытов
    - fallback: video -> document
    - fallback: photo -> document
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    caption = "✅ Готово!"
    is_video = mime.startswith("video/") or filename.lower().endswith((".mp4", ".webm", ".mov", ".mkv"))
    is_gif = mime.startswith("image/gif") or filename.lower().endswith(".gif")
    is_image = mime.startswith("image/") and not is_gif

    async def _try_send(kind: str) -> None:
        if kind == "video":
            await message.answer_video(
                BufferedInputFile(out_bytes, filename=filename),
                caption=caption,
                supports_streaming=True,
            )
            return
        if kind == "photo":
            await message.answer_photo(
                BufferedInputFile(out_bytes, filename=filename),
                caption=caption,
            )
            return
        await message.answer_document(
            BufferedInputFile(out_bytes, filename=filename),
            caption=caption,
        )

    if is_video:
        order = ["video", "document"]
    elif is_image:
        order = ["photo", "document"]
    else:
        order = ["document"]

    last_err: Exception | None = None
    for kind in order:
        for attempt in range(1, 4):
            try:
                await _try_send(kind)
                return
            except Exception as e:
                last_err = e
                log.warning("Telegram send failed kind=%s attempt=%s: %s", kind, attempt, e)
                await asyncio.sleep(0.7 * attempt)
                continue
    if last_err:
        raise last_err


PHOTO_ACTION_ENHANCE = "photo:enhance"
PHOTO_ACTION_EDIT_PROMPT = "photo:edit_prompt"
PHOTO_ACTION_EDIT_MASK = "photo:edit_mask"


def _photo_actions_kb(lang: str):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Улучшить", callback_data=PHOTO_ACTION_ENHANCE)],
        [InlineKeyboardButton(text="✏️ Редактировать (промпт)", callback_data=PHOTO_ACTION_EDIT_PROMPT)],
        [InlineKeyboardButton(text="🎭 Редактировать (маска + промпт)", callback_data=PHOTO_ACTION_EDIT_MASK)],
    ])


async def _run_image_job(
    *,
    message: Message,
    client: ComfyUIClient,
    loader: WorkflowLoader,
    workflow_name: str,
    input_image_name: str,
    prompt: str,
    negative: str = "",
    mask_image_name: str | None = None,
    denoise: float | None = None,
    settings = None,
) -> None:
    wf_name = workflow_name
    if wf_name == WORKFLOW_IMAGE_REFINER and not _workflow_exists(loader, wf_name):
        wf_name = WORKFLOW_IMAGE_DEFAULT

    wf = loader.load(wf_name)
    _inject_input_image(wf, input_image_name)
    if mask_image_name:
        ok = _inject_mask_image(wf, mask_image_name)
        if not ok:
            log.warning("Mask mode requested but no mask inputs found in workflow=%s (mask will be ignored).", wf_name)
    _inject_denoise(wf, denoise=denoise)
    _inject_prompt(wf, prompt, negative_prompt=negative)

    pid = await client.queue_prompt(wf)
    if not pid:
        err = (client.last_error or "ComfyUI отклонил workflow").strip()[:800]
        raise RuntimeError(err)
    log.info("Prompt queued: %s (workflow=%s)", pid, wf_name)

    timeout_val = int(getattr(settings or {}, "comfy_timeout", 300)) if settings else 300
    result = await client.wait_for_result(pid, timeout=timeout_val)
    if not result:
        raise RuntimeError(client.last_error or "Timeout: ComfyUI не вернул output")

    filename = str(result["filename"])
    out_bytes = bytes(result["bytes"])
    mime = str(result.get("mime") or "application/octet-stream")

    log.info("Image result: filename=%s size=%s mime=%s node=%s", filename, len(out_bytes), mime, result.get("node_id"))
    await _send_result_to_telegram(message, out_bytes=out_bytes, filename=filename, mime=mime)


# =========================================================================
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
    """Получаем фото и сохраняем локально для дальнейшего использования."""
    try:
        ph = message.photo[-1]
        tg_file = await message.bot.get_file(ph.file_id)
        buf = BytesIO()
        await message.bot.download_file(tg_file.file_path, destination=buf)
        photo_bytes = buf.getvalue()

        # Сохраняем фото во временную папку
        tmp_file = save_telegram_photo(photo_bytes, settings.tmp_dir, prefix="tg_photo")
        
        # Копируем в ComfyUI input (сразу, чтобы было готово)
        comfy_filename = ensure_comfy_input_image(tmp_file, settings.comfy_input_dir)

        # Сохраняем в state
        await state.update_data(
            input_image_local_path=str(tmp_file),
            input_image_comfy_name=comfy_filename,
            last_photo_comfy=comfy_filename,
            pending_photo_action=None,
            mask_photo_comfy=None,
        )
        await state.set_state(GenStates.waiting_prompt)

        # Показать действия с кнопками
        await message.answer(
            "🖼 Фото получено. Что сделать?",
            reply_markup=_photo_actions_kb(lang),
        )
    except Exception as e:
        log.exception(f"Photo receive failed: {e}")
        await message.answer(
            "❌ Не смогу принять фото. Попробуй ещё раз.",
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
    
    # --- photo edit flow (FSMContext keys) ---
    pending = st.get("pending_photo_action")
    if pending in ("edit_prompt", "edit_mask_prompt"):
        last_photo = st.get("last_photo_comfy")
        mask_photo = st.get("mask_photo_comfy") if pending == "edit_mask_prompt" else None
        if not last_photo:
            await state.update_data(pending_photo_action=None, mask_photo_comfy=None)
            await message.answer("Нет фото для редактирования. Отправь фото заново.")
            return

        client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)
        loader = WorkflowLoader(settings.workflows_dir)

        wf_name = st.get("pending_photo_workflow") or WORKFLOW_IMAGE_DEFAULT
        denoise = st.get("pending_photo_denoise")
        if pending == "edit_mask_prompt":
            wf_name = WORKFLOW_IMAGE_DEFAULT
            if denoise is None:
                denoise = 0.65

        user_prompt = raw
        prompt = f"{user_prompt}. Keep the same subject identity and scene layout, realistic, natural light, coherent details."
        prompt = _translate_ru_to_en_if_needed(prompt)
        negative = "blurry, lowres, deformed, artifacts, bad anatomy, cartoon, anime, text, watermark"

        await message.answer("🛠️ Редактирую…")
        try:
            await _run_image_job(
                message=message,
                client=client,
                loader=loader,
                workflow_name=wf_name,
                input_image_name=last_photo,
                mask_image_name=mask_photo,
                prompt=prompt,
                negative=negative,
                denoise=denoise,
                settings=settings,
            )
        except Exception as e:
            log.exception(f"Photo edit failed: {e}")
            await message.answer(f"❌ Ошибка: {e}")
        finally:
            await client.close()

        await state.update_data(pending_photo_action=None, mask_photo_comfy=None, pending_photo_workflow=None, pending_photo_denoise=None)
        await message.answer("🏠 Главное меню:", reply_markup=get_main_menu_keyboard(lang))
        return

    st = await state.get_data()
    generation_mode = st.get("generation_mode", "dev")
    force_video = bool(st.get("force_video"))
    state_quality = bool(st.get("video_quality"))

    # Разбор префикса с учётом режима + quality mode
    low_raw = raw.lower().strip()
    quality_mode = state_quality
    if low_raw.startswith("videoq:"):
        quality_mode = True
        raw = "video:" + raw[len("videoq:"):]
    elif low_raw.startswith("videoq "):
        quality_mode = True
        raw = "video:" + raw[len("videoq "):]

    workflow_name, prompt = _parse_prefix(raw, default_mode=generation_mode)
    if force_video and not low_raw.startswith(("video:", "vid:", "videoq:", "videoq ")):
        workflow_name = "video_hunyuan15_720p_api"

    if not prompt:
        await message.answer("✍️ Введите промт одним сообщением.", reply_markup=get_back_keyboard(lang))
        return

    prompt = _translate_ru_to_en_if_needed(prompt)

    # Логика выбора workflow при наличии фото (входного изображения)
    input_image_comfy_name = st.get("input_image_comfy_name")
    if input_image_comfy_name:
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
        # Если указан edit: — используем image_default или FLUX img2img (если доступен)

    await state.set_state(GenStates.running)
    status_msg = await message.answer("⏳ Обработка...", parse_mode="HTML")

    client: Optional[ComfyUIClient] = None
    try:
        loader = WorkflowLoader(settings.workflows_dir)
        wf = loader.load(workflow_name)

        log.info(f"Workflow loaded: {workflow_name}, nodes count: {len(wf)}")

        # Тюнинг параметров по умолчанию
        if workflow_name == "video_hunyuan15_720p_api":
            # HunyuanVideo 1.5 I2V with VRAM-aware presets + auto-fallback
            log.info("HunyuanVideo 1.5 I2V API workflow detected - applying VRAM-aware presets")
            
            # 0) Определяем входное изображение: из state или генерация
            input_image_comfy_name = st.get("input_image_comfy_name")
            
            # Получаем system_stats для выбора стартового пресета
            if client is None:
                client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)
            system_stats = None
            try:
                system_stats = await client.system_stats()
            except Exception as e:
                log.warning(f"Failed to get system_stats: {e}")
            
            # ВыбираемPreset
            start_idx = _pick_hunyuan_preset_index(system_stats)
            if quality_mode and start_idx < 1:
                start_idx = 1
            preset = HUNYUAN_PRESETS[start_idx]
            log.info(f"Selected Hunyuan preset: {preset['name']} ({preset['width']}x{preset['height']})")
            
            if not input_image_comfy_name:
                # Нет фото от пользователя - автогенерация стартового кадра
                await status_msg.edit_text(
                    f"⏳ Генерирую стартовый кадр {preset['width']}x{preset['height']}...", 
                    parse_mode="HTML"
                )
                
                try:
                    input_image_comfy_name = await _generate_start_image(
                        client=client,
                        loader=loader,
                        prompt=prompt,
                        settings=settings,
                        tmp_dir=Path(settings.tmp_dir),
                        comfy_input_dir=Path(settings.comfy_input_dir),
                        target_width=preset["width"],
                        target_height=preset["height"],
                    )
                    await status_msg.edit_text("✓ Стартовый кадр готов — запускаю видео...", parse_mode="HTML")
                except Exception as e:
                    log.exception(f"Start image generation failed: {e}")
                    raise RuntimeError(f"Не удалось создать стартовый кадр для I2V:\n{e}")
            else:
                # Проверяем валидность полученного фото
                if not validate_input_image(input_image_comfy_name, settings.comfy_input_dir):
                    raise RuntimeError(
                        f"Входное изображение '{input_image_comfy_name}' не найдено или невалидно.\n"
                        f"Проверьте папку {settings.comfy_input_dir}"
                    )
                log.info(f"Using user-provided image: {input_image_comfy_name}")
            
            # Важная проверка: если filename пустой - fail
            if not input_image_comfy_name or not input_image_comfy_name.strip():
                raise RuntimeError(
                    "Нужна стартовая картинка для I2V.\n"
                    "Пришли фото или дождись автогенерации кадра."
                )
            
            # Инжектим входное изображение в workflow
            _inject_hunyuan_input_image(wf, input_image_comfy_name)
            
            # Инжект промптов (один раз, до попыток)
            _inject_hunyuan_i2v_prompts(wf, prompt)
            
            # Попытки от "самого жирного" подходящего к более лёгким
            attempt_indices = list(range(start_idx, -1, -1))
            
            last_err = None
            result = None
            prompt_id = None
            
            for i, pi in enumerate(attempt_indices, start=1):
                preset = HUNYUAN_PRESETS[pi]
                log.info(f"Hunyuan preset attempt {i}/{len(attempt_indices)}: {preset['name']}")
                
                # Инжектим параметры для текущего пресета
                _inject_hunyuan_i2v_settings(
                    wf,
                    width=preset["width"],
                    height=preset["height"],
                    num_frames=preset["num_frames"],
                    fps=preset["fps"],
                    steps=preset["steps"],
                    cfg=preset["cfg"],
                    batch_size=preset["batch_size"],
                    weight_dtype=preset["weight_dtype"],
                )
                _inject_hunyuan_noise_seed(wf)
                
                log.info("HunyuanVideo API: skipping checkpoint/UNET auto-select (using workflow defaults)")
                
                # Пробуем отправить в ComfyUI
                try:
                    prompt_id = await client.queue_prompt(wf)
                    if not prompt_id:
                        err = (client.last_error or "ComfyUI отклонил workflow").strip()[:800]
                        log.error(f"ComfyUI rejected workflow: {err}")
                        raise RuntimeError(err)
                    
                    log.info(f"Prompt queued: {prompt_id}")
                    
                    # Ждём результата с динамическим timeout
                    timeout_s = min(1800, max(900, 300 + int(preset["num_frames"] * preset["steps"])) )
                    result = await client.wait_for_result(prompt_id, timeout=timeout_s)
                    if result is not None:
                        log.info(f"✓ HunyuanVideo успешно сгенерировал с пресетом {preset['name']}")
                        break
                    
                    # Если result None - проверяем причину
                    last_err = client.last_error or "unknown error"
                    log.warning(f"Hunyuan attempt failed ({preset['name']}): {last_err}")
                    
                    # Если OOM или early fail - пробуем следующий пресет
                    if _is_oom_error(last_err) or "not in queue" in last_err.lower() or "without outputs" in last_err.lower():
                        if i < len(attempt_indices):
                            log.info(f"Will retry with lighter preset...")
                            continue
                        else:
                            # Последняя попытка провалилась
                            raise RuntimeError(last_err)
                    else:
                        # Другая ошибка - не пробуем fallback
                        raise RuntimeError(last_err)
                
                except RuntimeError:
                    raise
                except Exception as e:
                    log.exception(f"Unexpected error during Hunyuan generation: {e}")
                    raise RuntimeError(str(e))
            
            if result is None:
                err = last_err or client.last_error or "HunyuanVideo: все попытки провалились"
                if _is_oom_error(err):
                    err = (
                        "❌ ComfyUI завершился без результата (OOM - нехватка VRAM).\n\n"
                        "💡 Рекомендации:\n"
                        "• Перезапустите ComfyUI с --lowvram\n"
                        "• Закройте другие GPU-приложения\n"
                        "• Попробуйте позже\n\n"
                        f"Детали: {err}"
                    )
                raise RuntimeError(err)
        
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

            if client is None:
                client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)

            # Если есть фото от пользователя — используем для других workflow
            input_image_comfy_name = st.get("input_image_comfy_name")
            if input_image_comfy_name:
                # Проверка и инжект для старых workflow (sdxl, image_edit)
                if validate_input_image(input_image_comfy_name, settings.comfy_input_dir):
                    ok = _inject_image_filename(wf, input_image_comfy_name)
                    if ok:
                        log.info(f"Input image injected for {workflow_name}: {input_image_comfy_name}")
                    else:
                        log.warning(f"Workflow {workflow_name} не поддерживает входное изображение")

            # Auto-select: checkpoint и UNET
            ckpt_inputs = _find_inputs(wf, "ckpt_name")
            if ckpt_inputs:
                available = await client.get_checkpoint_names()
                if not available:
                    raise RuntimeError("ComfyUI: нет checkpoints в models/checkpoints")
                current = _get_current_value(wf, "ckpt_name")
                chosen = _choose_checkpoint(available, workflow_name, current)
                if chosen:
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
                # Проверяем last_error для более информативного сообщения
                error_msg = client.last_error or "Timeout: ComfyUI не вернул output"
                error_msg = f"❌ {error_msg}\n\nПроверьте логи ComfyUI или очередь задач."
                log.error(f"Generation failed: {error_msg}")
                raise RuntimeError(error_msg)
        
        # Общая обработка результата (для всех workflow)
        if not result:
            raise RuntimeError("ComfyUI не вернул результат.")

        result_bytes = bytes(result["bytes"])
        result_filename = str(result.get("filename") or "output.bin")
        result_mime = str(result.get("mime") or "application/octet-stream")
        output_node = result.get("node_id") or "unknown"
        output_type = result.get("output_type") or "unknown"

        log.info(
            "Result ready: node=%s type=%s filename=%s size=%s bytes mime=%s",
            output_node,
            output_type,
            result_filename,
            len(result_bytes),
            result_mime,
        )

        # Удаляем статус-сообщение, если можем
        try:
            await status_msg.delete()
        except Exception:
            pass

        max_send_retries = 2
        send_success = False

        for attempt in range(max_send_retries):
            try:
                is_video = result_mime.startswith("video/") or result_filename.lower().endswith(
                    (".mp4", ".webm", ".mov", ".avi")
                )
                input_file = BufferedInputFile(result_bytes, filename=result_filename)

                if is_video:
                    try:
                        await message.answer_video(
                            input_file,
                            caption="✅ Готово!",
                            supports_streaming=True,
                            reply_markup=get_main_menu_keyboard(lang),
                        )
                        send_success = True
                        log.info("Telegram send: video (%s)", result_filename)
                        break
                    except TelegramBadRequest:
                        await message.answer_document(
                            input_file,
                            caption="✅ Готово!",
                            reply_markup=get_main_menu_keyboard(lang),
                        )
                        send_success = True
                        log.info("Telegram send: document (%s)", result_filename)
                        break
                else:
                    await message.answer_photo(
                        input_file,
                        caption="✅ Готово!",
                        reply_markup=get_main_menu_keyboard(lang),
                    )
                    send_success = True
                    log.info("Telegram send: photo (%s)", result_filename)
                    break
            except Exception as send_err:
                log.warning("Send attempt %s failed: %s", attempt + 1, send_err)
                if attempt < max_send_retries - 1:
                    await asyncio.sleep(2)

        if not send_success:
            fallback_path = Path(settings.tmp_dir) / result_filename
            try:
                fallback_path.write_bytes(result_bytes)
            except Exception:
                fallback_path = Path(result_filename)
            await message.answer(
                "❌ Не удалось отправить результат в Telegram.\n"
                f"Файл сохранён: {fallback_path}",
                reply_markup=get_main_menu_keyboard(lang),
            )

    finally:
        if client is not None:
            await client.close()
        try:
            # Очищаем все данные о загруженных изображениях
            await state.update_data(
                input_image_local_path=None,
                input_image_comfy_name=None,
                generation_mode=None,
                force_video=None,
                video_quality=None
            )
        except Exception:
            pass
        await state.clear()


@router.callback_query(F.data.in_({PHOTO_ACTION_ENHANCE, PHOTO_ACTION_EDIT_PROMPT, PHOTO_ACTION_EDIT_MASK}))
async def cb_photo_actions(callback: CallbackQuery, state: FSMContext, settings) -> None:
    from bot.keyboards.main_menu import get_main_menu_keyboard
    from utils.helpers import get_lang
    
    lang = get_lang(callback.message)
    data = await state.get_data()
    last_photo = data.get("last_photo_comfy")
    if not last_photo:
        await callback.answer("Нет фото для обработки. Сначала отправь фото.")
        return

    action = callback.data
    await callback.answer()

    loader = callback.bot.get("workflow_loader")
    if loader is None:
        loader = WorkflowLoader(settings.workflows_dir)

    wf_name = WORKFLOW_IMAGE_DEFAULT
    if _workflow_exists(loader, WORKFLOW_FLUX_DEV_IMG2IMG):
        wf_name = WORKFLOW_FLUX_DEV_IMG2IMG
    elif _workflow_exists(loader, WORKFLOW_FLUX_SCHNELL_IMG2IMG):
        wf_name = WORKFLOW_FLUX_SCHNELL_IMG2IMG

    if action == PHOTO_ACTION_ENHANCE:
        client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)
        prompt = "enhance photo, keep subject and composition, more details, sharp focus, realistic, high quality"
        negative = "blurry, lowres, deformed, artifacts, bad anatomy, cartoon, anime, oversaturated"
        await callback.message.answer("✨ Улучшаю фото…")
        try:
            await _run_image_job(
                message=callback.message,
                client=client,
                loader=loader,
                workflow_name=wf_name,
                input_image_name=last_photo,
                prompt=prompt,
                negative=negative,
                denoise=0.25,
                settings=settings,
            )
        except Exception as e:
            log.exception(f"Enhance failed: {e}")
            await callback.message.answer(f"❌ Ошибка: {e}")
        finally:
            await client.close()
        return

    if action == PHOTO_ACTION_EDIT_PROMPT:
        await state.update_data(
            pending_photo_action="edit_prompt",
            mask_photo_comfy=None,
            pending_photo_workflow=wf_name,
            pending_photo_denoise=0.55,
        )
        await callback.message.answer("✏️ Пришли промпт для редактирования (что изменить/добавить).")
        return

    if action == PHOTO_ACTION_EDIT_MASK:
        await state.update_data(
            pending_photo_action="edit_mask_wait_mask",
            mask_photo_comfy=None,
            pending_photo_workflow=WORKFLOW_IMAGE_DEFAULT,
            pending_photo_denoise=0.65,
        )
        await callback.message.answer("🎭 Пришли маску (ч/б: белым — менять, чёрным — оставить).")
        return


@router.message(F.photo)
async def msg_photo_mask_router(message: Message, state: FSMContext, settings) -> None:
    """
    Если пользователь в режиме mask-edit и прислал фото — это маска.
    """
    st = await state.get_data()
    if st.get("pending_photo_action") != "edit_mask_wait_mask":
        return

    from utils.helpers import get_lang
    
    lang = get_lang(message)
    mask_name = await save_telegram_photo(message, settings.tmp_dir, prefix="mask")
    
    # Копируем маску в ComfyUI input
    mask_comfy = ensure_comfy_input_image(mask_name, settings.comfy_input_dir)
    
    await state.update_data(mask_photo_comfy=mask_comfy, pending_photo_action="edit_mask_prompt")
    await message.answer("✅ Маска получена. Теперь пришли промпт (что изменить в белых областях).")



