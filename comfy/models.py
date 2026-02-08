# -*- coding: utf-8 -*-
"""РњРѕРґРµР»Рё РґР°РЅРЅС‹С… РґР»СЏ ComfyUI API."""
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class ComfyUITask:
    """Р—Р°РґР°С‡Р° РґР»СЏ ComfyUI API."""
    prompt_id: str
    prompt: Dict[str, Any]
    status: str = "unknown"
    value: float = 0.0
    max: float = 100.0


@dataclass
class NodeData:
    """Р”Р°РЅРЅС‹Рµ СѓР·Р»Р° ComfyUI workflow."""
    class_type: str
    inputs: Dict[str, Any]
