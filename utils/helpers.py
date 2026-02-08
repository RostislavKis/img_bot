# -*- coding: utf-8 -*-
"""Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ С„СѓРЅРєС†РёРё Рё СѓС‚РёР»РёС‚С‹."""
import json
from pathlib import Path
from typing import Any, Dict


def load_json(file_path: Path) -> Dict[str, Any]:
    """Р—Р°РіСЂСѓР¶Р°РµС‚ JSON С„Р°Р№Р»."""
    if not file_path.exists():
        return {}
    
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data: Dict[str, Any]) -> bool:
    """РЎРѕС…СЂР°РЅСЏРµС‚ РґР°РЅРЅС‹Рµ РІ JSON С„Р°Р№Р»."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def format_time_hms(seconds: int) -> str:
    """Р¤РѕСЂРјР°С‚РёСЂСѓРµС‚ СЃРµРєСѓРЅРґС‹ РІ С„РѕСЂРјР°С‚ HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def truncate_text(text: str, max_len: int = 50) -> str:
    """РћР±СЂРµР·Р°РµС‚ С‚РµРєСЃС‚ Рё РґРѕР±Р°РІР»СЏРµС‚ ... РµСЃР»Рё РЅСѓР¶РЅРѕ."""
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."
