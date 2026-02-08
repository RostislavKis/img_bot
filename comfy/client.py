from __future__ import annotations

import asyncio
import mimetypes
import uuid
from typing import Any, Dict, Optional, List, Iterable

import httpx

from utils.logger import get_logger

log = get_logger(__name__)


class ComfyUIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        self.client_id = uuid.uuid4().hex
        self.last_error: Optional[str] = None

    async def system_stats(self) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"{self.base_url}/system_stats")
            if r.status_code == 200:
                return r.json()
            log.warning(f"ComfyUI system_stats status={r.status_code} body={r.text[:200]}")
        except Exception as e:
            log.warning(f"ComfyUI system_stats failed: {e}")
        return {}

    async def check_health(self) -> bool:
        return bool(await self.system_stats())

    async def object_info(self) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"{self.base_url}/object_info")
            if r.status_code == 200:
                return r.json()
            log.warning(f"ComfyUI object_info status={r.status_code} body={r.text[:200]}")
        except Exception as e:
            log.warning(f"ComfyUI object_info failed: {e}")
        return {}

    def _parse_choices(self, obj_info: Dict[str, Any], node_name: str, field: str) -> List[str]:
        node = obj_info.get(node_name)
        if not isinstance(node, dict):
            return []
        inp = node.get("input")
        if not isinstance(inp, dict):
            return []
        req = inp.get("required")
        if not isinstance(req, dict):
            return []
        cfg = req.get(field)
        # обычно: [[choices...], {meta...}]
        if isinstance(cfg, list) and len(cfg) >= 1 and isinstance(cfg[0], list):
            out: List[str] = []
            for x in cfg[0]:
                s = str(x).strip()
                if s:
                    out.append(s)
            return out
        return []

    async def get_checkpoint_names(self) -> List[str]:
        obj = await self.object_info()
        if not isinstance(obj, dict):
            return []
        names = self._parse_choices(obj, "CheckpointLoaderSimple", "ckpt_name")
        return sorted({n for n in names if n})

    async def get_unet_names(self) -> List[str]:
        obj = await self.object_info()
        if not isinstance(obj, dict):
            return []
        names = self._parse_choices(obj, "UNETLoader", "unet_name")
        return sorted({n for n in names if n})

    def _summarize_prompt_error(self, body: str) -> str:
        try:
            import json
            j = json.loads(body)
            if isinstance(j, dict):
                if "node_errors" in j and isinstance(j["node_errors"], dict):
                    parts = []
                    for node_id, info in j["node_errors"].items():
                        if not isinstance(info, dict):
                            continue
                        errs = info.get("errors")
                        if not isinstance(errs, list):
                            continue
                        for e in errs[:3]:
                            if isinstance(e, dict):
                                details = str(e.get("details") or "")
                                msg = str(e.get("message") or "")
                                if details or msg:
                                    parts.append(f"node {node_id}: {details or msg}")
                    if parts:
                        return "; ".join(parts)[:350]
                err = j.get("error")
                if isinstance(err, dict):
                    m = str(err.get("message") or "")
                    t = str(err.get("type") or "")
                    s = (t + ": " + m).strip(": ").strip()
                    if s:
                        return s[:350]
        except Exception:
            pass
        return (body or "")[:350]

    async def queue_prompt(self, workflow_prompt: Dict[str, Any]) -> str:
        self.last_error = None
        payload = {"prompt": workflow_prompt, "client_id": self.client_id}
        try:
            r = await self.client.post(f"{self.base_url}/prompt", json=payload)
            if r.status_code != 200:
                body = r.text or ""
                self.last_error = self._summarize_prompt_error(body)
                log.warning(f"ComfyUI /prompt status={r.status_code} body={body[:400]}")
                return ""
            data = r.json()
            return str(data.get("prompt_id") or "")
        except Exception as e:
            self.last_error = str(e)
            log.warning(f"ComfyUI queue_prompt failed: {e}")
            return ""

    async def history(self, prompt_id: str) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"{self.base_url}/history/{prompt_id}")
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.warning(f"ComfyUI history failed: {e}")
        return {}

    async def view_bytes(self, filename: str, subfolder: str = "", file_type: str = "output") -> bytes:
        r = await self.client.get(
            f"{self.base_url}/view",
            params={"filename": filename, "subfolder": subfolder, "type": file_type},
        )
        r.raise_for_status()
        return r.content

    def _walk(self, obj: Any, depth: int = 0) -> Iterable[Any]:
        if depth > 6:
            return
        yield obj
        if isinstance(obj, dict):
            for v in obj.values():
                yield from self._walk(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj[:200]:
                yield from self._walk(v, depth + 1)

    def _get_file_priority(self, filename: str) -> int:
        """
        Возвращает приоритет файла по расширению.
        Меньше = выше приоритет.
        """
        ext = (filename or "").lower()
        if ext.endswith((".mp4", ".webm", ".mov", ".avi", ".mkv")):
            return 0  # Видео — TOP
        if ext.endswith(".gif"):
            return 1  # GIF — высокий приоритет
        if ext.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return 2  # Картинки — ниже
        return 3  # Остальное

    def _extract_first_file(self, history_payload: Dict[str, Any], prompt_id: str) -> Optional[Dict[str, str]]:
        """
        Извлекает файл из history с приоритизацией видео/гиф.
        
        Структура: outputs[node_id][key] = [{filename, subfolder, type}, ...]
        где key может быть: videos, gifs, animations, animated, files, images
        
        Приоритет:
        1. По расширению: видео > гиф > картинки
        2. По ключу: videos > gifs > animations > animated > files > images
        """
        entry = history_payload.get(prompt_id)
        if not isinstance(entry, dict):
            return None

        outputs = entry.get("outputs")
        if not isinstance(outputs, dict):
            return None

        # Логируем найденные node_id
        output_node_ids = list(outputs.keys())
        log.debug(f"Outputs node_ids: {output_node_ids}")

        # Приоритезированный список ключей для поиска
        priority_keys = ["video", "videos", "gifs", "animations", "animated", "files", "images"]
        
        candidates: List[Dict[str, Any]] = []

        # Проходим по всем node_id и их outputs
        for node_id, node_out in outputs.items():
            if not isinstance(node_out, dict):
                continue
            
            # Проходим по приоритезированным ключам
            for key_idx, key in enumerate(priority_keys):
                if key not in node_out:
                    continue
                
                val = node_out[key]
                # val должен быть list словарей
                if not isinstance(val, list):
                    continue
                
                for item in val:
                    if isinstance(item, dict) and item.get("filename"):
                        filename = str(item.get("filename"))
                        subfolder = str(item.get("subfolder") or "")
                        file_type = str(item.get("type") or "output")
                        
                        # Priority по расширению
                        ext_priority = self._get_file_priority(filename)
                        # Secondary priority по порядку ключей (меньше = раньше в приоритете)
                        key_priority = key_idx
                        
                        candidates.append({
                            "filename": filename,
                            "subfolder": subfolder,
                            "type": file_type,
                            "ext_priority": ext_priority,
                            "key_priority": key_priority,
                            "node_id": str(node_id),
                            "key": key,
                        })

        # Выбираем лучший кандидат
        if candidates:
            # Сортируем по ext_priority (по расширению), потом по key_priority (по ключу)
            candidates.sort(key=lambda x: (x["ext_priority"], x["key_priority"]))
            best = candidates[0]
            mime = mimetypes.guess_type(best["filename"])[0] or "application/octet-stream"
            log.debug(f"Selected output: node={best['node_id']} key={best['key']} file={best['filename']} mime={mime}")
            return {
                "filename": best["filename"],
                "subfolder": best["subfolder"],
                "type": best["type"],
            }

        # Fallback: ищем первый файл через _walk
        log.debug("No priority matches found, falling back to first file in outputs")
        for obj in self._walk(outputs):
            if isinstance(obj, dict) and obj.get("filename"):
                return {
                    "filename": str(obj.get("filename")),
                    "subfolder": str(obj.get("subfolder") or ""),
                    "type": str(obj.get("type") or "output"),
                }

        return None

    async def wait_for_result(self, prompt_id: str, timeout: int = 600, poll_sec: float = 1.0) -> Optional[Dict[str, Any]]:
        deadline = asyncio.get_event_loop().time() + float(timeout)
        last_err: Optional[str] = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                h = await self.history(prompt_id)
                f = self._extract_first_file(h, prompt_id)
                if f:
                    b = await self.view_bytes(f["filename"], f["subfolder"], f["type"])
                    mime = mimetypes.guess_type(f["filename"])[0] or "application/octet-stream"
                    return {"filename": f["filename"], "bytes": b, "mime": mime}
            except Exception as e:
                last_err = str(e)
            await asyncio.sleep(poll_sec)
        if last_err:
            log.warning(f"wait_for_result timeout, last error: {last_err}")
        return None

    async def upload_image(self, data: bytes, filename: str, subfolder: str = "", overwrite: bool = True) -> Dict[str, str]:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {"image": (filename, data, mime)}
        params = {
            "type": "input",
            "subfolder": subfolder,
            "overwrite": "true" if overwrite else "false",
        }

        for endpoint in ("/upload/image", "/api/upload/image"):
            try:
                r = await self.client.post(f"{self.base_url}{endpoint}", params=params, files=files)
                if r.status_code == 200:
                    j = r.json()
                    if isinstance(j, dict):
                        name = str(j.get("name") or j.get("filename") or j.get("file") or "").strip()
                        sub = str(j.get("subfolder") or "").strip()
                        typ = str(j.get("type") or "input").strip()
                        if name:
                            return {"name": name, "subfolder": sub, "type": typ}
                    return {"name": filename, "subfolder": subfolder, "type": "input"}
                else:
                    log.warning(f"upload_image {endpoint} status={r.status_code} body={r.text[:200]}")
            except Exception as e:
                log.warning(f"upload_image {endpoint} failed: {e}")

        raise RuntimeError("ComfyUI upload_image failed (нет /upload/image или ошибка запроса)")

    async def close(self) -> None:
        await self.client.aclose()
