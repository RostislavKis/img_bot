"""Утилиты для работы с файлами."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)


def ensure_comfy_input_image(local_file: str | Path, comfy_input_dir: str | Path) -> str:
    """
    Копирует локальный файл в папку ComfyUI input и возвращает basename.
    
    Args:
        local_file: путь к локальному файлу (например C:/dev/img_bot/data/tmp/image.png)
        comfy_input_dir: путь к папке input ComfyUI (например D:/ComfyUI/input)
    
    Returns:
        basename файла (например "image.png"), который можно передать в workflow LoadImage
    """
    local_path = Path(local_file)
    if not local_path.exists():
        raise FileNotFoundError(f"Локальный файл не найден: {local_file}")
    
    input_dir = Path(comfy_input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    
    dest_file = input_dir / local_path.name
    shutil.copy2(local_path, dest_file)
    
    log.info(f"Файл скопирован в ComfyUI input: {local_path.name}")
    return local_path.name


def save_telegram_photo(photo_bytes: bytes, tmp_dir: str | Path, prefix: str = "tg_photo") -> Path:
    """
    Сохраняет фото из Telegram во временную папку.
    
    Args:
        photo_bytes: байты изображения
        tmp_dir: временная папка проекта
        prefix: префикс имени файла
    
    Returns:
        Path к сохранённому файлу
    """
    tmp_path = Path(tmp_dir)
    tmp_path.mkdir(parents=True, exist_ok=True)
    
    # Генерируем уникальное имя
    import uuid
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.png"
    file_path = tmp_path / filename
    
    file_path.write_bytes(photo_bytes)
    log.info(f"Telegram photo saved: {file_path}")
    return file_path


def validate_input_image(filename: str, comfy_input_dir: str | Path) -> bool:
    """
    Проверяет, что файл существует в ComfyUI input и не является плейсхолдером.
    
    Args:
        filename: имя файла (basename)
        comfy_input_dir: путь к папке input ComfyUI
    
    Returns:
        True если файл валидный, False если это плейсхолдер/не существует
    """
    # Проверка на плейсхолдеры
    if not filename or filename.lower() in ("blank.png", "empty.png", "placeholder.png"):
        log.warning(f"Обнаружен плейсхолдер: {filename}")
        return False
    
    file_path = Path(comfy_input_dir) / filename
    if not file_path.exists():
        log.warning(f"Файл не найден в ComfyUI input: {file_path}")
        return False
    
    # Проверяем размер (минимум 1KB)
    if file_path.stat().st_size < 1024:
        log.warning(f"Файл слишком маленький: {file_path}")
        return False
    
    return True
