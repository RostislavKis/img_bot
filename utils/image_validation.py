"""Валидация качества изображений."""

from __future__ import annotations

import io
from typing import Tuple

try:
    from PIL import Image
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from utils.logger import get_logger

log = get_logger(__name__)


def detect_gray_frame(image_bytes: bytes, threshold: float = 10.0) -> Tuple[bool, float]:
    """
    Проверяет, является ли изображение "серым" или почти однотонным.
    
    Args:
        image_bytes: байты изображения (PNG/JPEG)
        threshold: порог stddev (если меньше - считается серым)
    
    Returns:
        (is_gray, stddev) - True если изображение слишком однотонное
    
    Примеры:
        - Полностью серое изображение: stddev ~ 0-2
        - Нормальное изображение: stddev > 20
        - Граница: 10
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow/numpy required for gray-frame detection")
    
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # Конвертируем в grayscale
        gray = img.convert('L')
        
        # Получаем массив пикселей
        pixels = np.array(gray, dtype=np.float32)
        
        # Считаем stddev яркости
        stddev = float(np.std(pixels))
        
        is_gray = stddev < threshold
        
        if is_gray:
            log.warning(f"Detected gray/blank frame: stddev={stddev:.2f} (threshold={threshold})")
        else:
            log.info(f"Frame quality OK: stddev={stddev:.2f}")
        
        return (is_gray, stddev)
        
    except Exception as e:
        log.exception(f"Failed to analyze image: {e}")
        return (False, 0.0)


def validate_aspect_ratio(
    image_bytes: bytes, 
    expected_width: int, 
    expected_height: int,
    tolerance: float = 0.05
) -> bool:
    """
    Проверяет, что aspect ratio изображения соответствует ожидаемому.
    
    Args:
        image_bytes: байты изображения
        expected_width: ожидаемая ширина
        expected_height: ожидаемая высота
        tolerance: допустимая погрешность (5% по умолчанию)
    
    Returns:
        True если aspect ratio правильный
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow/numpy required for aspect ratio validation")
    
    try:
        img = Image.open(io.BytesIO(image_bytes))
        actual_ratio = img.width / img.height
        expected_ratio = expected_width / expected_height
        
        diff = abs(actual_ratio - expected_ratio) / expected_ratio
        
        if diff > tolerance:
            log.warning(
                f"Aspect ratio mismatch: {img.width}x{img.height} "
                f"(actual={actual_ratio:.3f}) vs expected {expected_width}x{expected_height} "
                f"(expected={expected_ratio:.3f}), diff={diff*100:.1f}%"
            )
            return False
        
        return True
        
    except Exception as e:
        log.exception(f"Failed to validate aspect ratio: {e}")
        return True  # Не блокируем если не можем проверить
