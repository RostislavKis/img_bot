# -*- coding: utf-8 -*-
"""Р—Р°РіСЂСѓР·С‡РёРє Р»РѕРєР°Р»РёР·Р°С†РёР№ РёР· JSON С„Р°Р№Р»РѕРІ."""
from pathlib import Path
from typing import Dict, Any
import json


class LocaleManager:
    """РЈРїСЂР°РІР»СЏРµС‚ Р»РѕРєР°Р»РёР·Р°С†РёСЏРјРё (RU/EN)."""
    
    def __init__(self, locales_dir: Path = None):
        """РРЅРёС†РёР°Р»РёР·РёСЂСѓРµС‚ РјРµРЅРµРґР¶РµСЂ Р»РѕРєР°Р»РёР·Р°С†РёР№."""
        if locales_dir is None:
            locales_dir = Path(__file__).parent / "locales"
        
        self.locales_dir = locales_dir
        self.cache: Dict[str, Dict[str, str]] = {}
        self._load_locales()
    
    def _load_locales(self):
        """Р—Р°РіСЂСѓР¶Р°РµС‚ РІСЃРµ JSON С„Р°Р№Р»С‹ РёР· РїР°РїРєРё locales."""
        if not self.locales_dir.exists():
            self.locales_dir.mkdir(parents=True, exist_ok=True)
        
        for lang_file in self.locales_dir.glob("*.json"):
            lang_code = lang_file.stem
            try:
                with open(lang_file, "r", encoding="utf-8") as f:
                    self.cache[lang_code] = json.load(f)
            except Exception as e:
                print(f"РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё {lang_file}: {e}")
    
    def get_text(self, lang: str, key: str, default: str = "") -> str:
        """РџРѕР»СѓС‡Р°РµС‚ РїРµСЂРµРІРµРґС‘РЅРЅС‹Р№ С‚РµРєСЃС‚."""
        if lang not in self.cache:
            lang = "en"
        
        return self.cache.get(lang, {}).get(key, default)
    
    def get_available_languages(self) -> list:
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє РґРѕСЃС‚СѓРїРЅС‹С… СЏР·С‹РєРѕРІ."""
        return list(self.cache.keys())
