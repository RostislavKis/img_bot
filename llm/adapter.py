# -*- coding: utf-8 -*-
"""РђРґР°РїС‚РµСЂ РґР»СЏ Р»РѕРєР°Р»СЊРЅС‹С… LLM (Ollama, LM Studio)."""
from __future__ import annotations
from typing import Optional
import httpx
from utils.logger import get_logger

log = get_logger("llm.adapter")


class LLMAdapter:
    """РђРґР°РїС‚РµСЂ РґР»СЏ СЂР°Р±РѕС‚С‹ СЃ Р»РѕРєР°Р»СЊРЅС‹РјРё LLM С‡РµСЂРµР· HTTP."""
    
    def __init__(self, provider: str, endpoint: str, model: str):
        """РРЅРёС†РёР°Р»РёР·РёСЂСѓРµС‚ Р°РґР°РїС‚РµСЂ."""
        self.provider = (provider or "disabled").lower().strip()
        self.endpoint = (endpoint or "").rstrip("/")
        if self.endpoint.endswith("/v1"):
            self.endpoint = self.endpoint[:-3]
        self.model = model or ""
        self.client = httpx.AsyncClient(timeout=30)
    
    async def improve_prompt(self, prompt: str) -> Optional[str]:
        """РЈР»СѓС‡С€Р°РµС‚ РїСЂРѕРјРїС‚ С‡РµСЂРµР· LLM."""
        if self.provider in ("disabled", "") or not self.endpoint or not self.model:
            return None
        
        try:
            if self.provider == "ollama":
                return await self._ollama_improve(prompt)
            if self.provider == "lmstudio":
                return await self._lmstudio_improve(prompt)
            
            return None
        except Exception as e:
            log.warning(f"LLM improve error: {e}")
        
        return None
    
    async def _ollama_improve(self, prompt: str) -> Optional[str]:
        """Ollama API СѓР»СѓС‡С€РµРЅРёРµ РїСЂРѕРјРїС‚Р°."""
        try:
            r = await self.client.post(
                f"{self.endpoint}/api/generate",
                json={
                    "model": self.model,
                    "prompt": f"РЈР»СѓС‡С€Рё СЌС‚РѕС‚ РїСЂРѕРјРїС‚ РґР»СЏ РіРµРЅРµСЂР°С†РёРё РёР·РѕР±СЂР°Р¶РµРЅРёСЏ, СЃРѕС…СЂР°РЅСЏСЏ СЃРјС‹СЃР»: {prompt}",
                    "stream": False
                }
            )
            
            if r.status_code != 200:
                return None
            data = r.json()
            out = (data.get("response") or "").strip()
            return out or None
        except Exception as e:
            log.warning(f"Ollama РѕС€РёР±РєР°: {e}")
        
        return None
    
    async def _lmstudio_improve(self, prompt: str) -> Optional[str]:
        """LM Studio OpenAI-compatible API СѓР»СѓС‡С€РµРЅРёРµ РїСЂРѕРјРїС‚Р°."""
        try:
            r = await self.client.post(
                f"{self.endpoint}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "РўС‹ СЃРїРµС†РёР°Р»РёСЃС‚ РїРѕ РіРµРЅРµСЂР°С†РёРё РёР·РѕР±СЂР°Р¶РµРЅРёР№. РЈР»СѓС‡С€Рё РїСЂРѕРјРїС‚, СЃРѕС…СЂР°РЅСЏСЏ РµРіРѕ СЃРјС‹СЃР» Рё РЅР°Р·РЅР°С‡РµРЅРёРµ."
                        },
                        {
                            "role": "user",
                            "content": f"РЈР»СѓС‡С€Рё РїСЂРѕРјРїС‚: {prompt}"
                        }
                    ],
                    "temperature": 0.7,
                    "max_tokens": 200
                }
            )
            
            if r.status_code != 200:
                return None
            data = r.json()
            try:
                out = data["choices"][0]["message"]["content"].strip()
                return out or None
            except Exception:
                return None
        except Exception as e:
            log.warning(f"LM Studio РѕС€РёР±РєР°: {e}")
        
        return None
    
    async def close(self) -> None:
        """Р—Р°РєСЂС‹РІР°РµС‚ СЃРѕРµРґРёРЅРµРЅРёРµ."""
        await self.client.aclose()
