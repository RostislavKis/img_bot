# -*- coding: utf-8 -*-
"""Р’Р°Р»РёРґР°С‚РѕСЂС‹ РґР»СЏ РІРІРѕРґР° РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Рё РґР°РЅРЅС‹С…."""
import re
from pathlib import Path


def validate_prompt(text: str, max_length: int = 1000) -> tuple[bool, str]:
    """РџСЂРѕРІРµСЂСЏРµС‚ РїСЂРѕРјРїС‚ РЅР° РІР°Р»РёРґРЅРѕСЃС‚СЊ."""
    if not text or not text.strip():
        return False, "РџСЂРѕРјРїС‚ РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ РїСѓСЃС‚"
    
    if len(text) > max_length:
        return False, f"РџСЂРѕРјРїС‚ СЃР»РёС€РєРѕРј РґР»РёРЅРЅС‹Р№ (РјР°РєСЃ {max_length} СЃРёРјРІРѕР»РѕРІ)"
    
    return True, ""


def validate_image_file(file_path: Path) -> tuple[bool, str]:
    """РџСЂРѕРІРµСЂСЏРµС‚ РёР·РѕР±СЂР°Р¶РµРЅРёРµ РЅР° РІР°Р»РёРґРЅРѕСЃС‚СЊ."""
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    
    if not file_path.exists():
        return False, "Р¤Р°Р№Р» РЅРµ РЅР°Р№РґРµРЅ"
    
    if file_path.suffix.lower() not in allowed_extensions:
        return False, f"РќРµРґРѕРїСѓСЃС‚РёРјС‹Р№ С„РѕСЂРјР°С‚: {file_path.suffix}"
    
    max_size_mb = 50
    if file_path.stat().st_size > max_size_mb * 1024 * 1024:
        return False, f"Р¤Р°Р№Р» СЃР»РёС€РєРѕРј Р±РѕР»СЊС€РѕР№ (РјР°РєСЃ {max_size_mb} РњР‘)"
    
    return True, ""


def validate_workflow_name(name: str) -> tuple[bool, str]:
    """РџСЂРѕРІРµСЂСЏРµС‚ РёРјСЏ workflow РЅР° РІР°Р»РёРґРЅРѕСЃС‚СЊ."""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", name):
        return False, "РРјСЏ workflow РјРѕР¶РµС‚ СЃРѕРґРµСЂР¶Р°С‚СЊ С‚РѕР»СЊРєРѕ Р±СѓРєРІС‹, С†РёС„СЂС‹, РїРѕРґС‡С‘СЂРєРёРІР°РЅРёРµ Рё РґРµС„РёСЃ"
    
    return True, ""
