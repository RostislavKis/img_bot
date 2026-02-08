from __future__ import annotations

import asyncio
import mimetypes
import uuid
import time
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
        """Скачивает файл через /view с ретраями и логированием."""
        params = {"filename": filename, "subfolder": subfolder, "type": file_type}
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = await self.client.get(f"{self.base_url}/view", params=params)
                r.raise_for_status()
                content = r.content
                log.info(
                    "Downloaded /view: filename=%s type=%s size=%s bytes",
                    filename,
                    file_type,
                    len(content),
                )
                return content
            except Exception as e:
                last_err = e
                log.warning(
                    "view_bytes attempt %s failed: filename=%s type=%s error=%s",
                    attempt + 1,
                    filename,
                    file_type,
                    e,
                )
                await asyncio.sleep(1.0)
        if last_err:
            raise last_err
        return b""

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

    def _extract_first_file(self, history: dict) -> Optional[dict]:
        """
        Вытаскивает первый найденный output файл из /history.
        """
        if not history:
            return None

        outputs = history.get("outputs") or {}
        if not isinstance(outputs, dict):
            return None

        candidates: List[dict] = []
        for node_id, out in outputs.items():
            if not isinstance(out, dict):
                continue
            for key in ("videos", "gifs", "images", "files"):
                items = out.get(key)
                if not isinstance(items, list):
                    continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    fn = it.get("filename")
                    sub = it.get("subfolder") or ""
                    ftype = it.get("type") or "output"
                    sz = it.get("size") or 0
                    if fn:
                        candidates.append({
                            "node_id": str(node_id),
                            "filename": fn,
                            "subfolder": sub,
                            "type": ftype,
                            "size": int(sz) if isinstance(sz, (int, float)) else 0,
                        })

        # Сортируем по размеру (больше = выше в списке), далее по приоритету расширения
        candidates.sort(key=lambda x: (-x["size"], self._get_file_priority(x["filename"])))

        # Возвращаем самый приоритетный файл
        if candidates:
            best = candidates[0]
            return {
                "node_id": best["node_id"],
                "filename": best["filename"],
                "subfolder": best["subfolder"],
                "type": best["type"],
            }

        return None

    def resolve_outputs(self, history: dict) -> Optional[dict]:
        """
        Гарантирует получение первого бинарного output из любого узла.
        Возвращает {filename, node_id, type}.
        """
        try:
            outputs = history.get("outputs", {})
            if not outputs:
                return None
            for node_id, node in outputs.items():
                if not isinstance(node, dict):
                    continue
                for key, items in node.items():
                    if isinstance(items, list) and items:
                        item = items[0] if isinstance(items[0], dict) else None
                        if item and "filename" in item:
                            return {
                                "node_id": str(node_id),
                                "filename": str(item.get("filename")),
                                "type": str(item.get("type") or "output"),
                            }
        except Exception as e:
            self.log.warning(f"resolve_outputs_simple failed: {e}")
        return None

    async def get_queue_status(self) -> Dict[str, Any]:
        """Получает статус очереди ComfyUI."""
        try:
            r = await self.client.get(f"{self.base_url}/queue")
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.warning(f"ComfyUI get_queue failed: {e}")
        return {}

    async def resolve_outputs(
        self,
        history_item: Dict[str, Any],
        prompt_id: str,
        retries: int = 3,
        delay_sec: float = 1.5,
    ) -> Optional[Dict[str, str]]:
        """
        Пытается найти outputs в history с повторными попытками.
        Возвращает словарь с filename/subfolder/type/node_id/key.
        """
        for attempt in range(retries + 1):
            f = self._extract_first_file(history_item)
            if f:
                return f
            if attempt < retries:
                await asyncio.sleep(delay_sec)
        return None

    async def wait_for_result(
        self, 
        prompt_id: str, 
        timeout: int = 600, 
        poll_sec: float = 1.0,
        history_retry: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Ждёт результата от ComfyUI с robust output resolver.
        
        Args:
            prompt_id: ID промпта
            timeout: общий timeout (секунды)
            poll_sec: интервал проверки (секунды)
            history_retry: сколько раз повторять /history если пустой после completion
        
        Returns:
            {"filename": ..., "bytes": ..., "mime": ...} или None
        """
        deadline = asyncio.get_event_loop().time() + float(timeout)
        last_err: Optional[str] = None
        check_count = 0
        empty_history_retries = 0
        
        while asyncio.get_event_loop().time() < deadline:
            check_count += 1
            try:
                # Проверяем history
                h = await self.history(prompt_id)

                # Если есть outputs - пробуем достать файл
                if h.get(prompt_id) and isinstance(h[prompt_id], dict):
                    outputs = h[prompt_id].get("outputs", {})
                    if outputs:
                        f = await self.resolve_outputs(h, prompt_id, retries=2, delay_sec=1.0)
                        if f:
                            b = await self.view_bytes(f["filename"], f["subfolder"], f["type"])
                            if b:
                                mime = mimetypes.guess_type(f["filename"])[0] or "application/octet-stream"
                                log.info(
                                    f"✓ Result ready after {check_count} checks: "
                                    f"filename={f['filename']}, size={len(b)} bytes, "
                                    f"output_node={f.get('node_id', 'unknown')}"
                                )
                                return {
                                    "filename": f["filename"],
                                    "bytes": b,
                                    "mime": mime,
                                    "node_id": f.get("node_id"),
                                    "output_type": f.get("key"),
                                }
                            else:
                                log.warning(f"File found but download failed: {f['filename']}")
                
                # Early detection: если history пустой И queue пустой = prompt failed/completed
                if check_count > 3:  # После 3 проверок начинаем проверять queue
                    queue_status = await self.get_queue_status()
                    
                    # Проверяем что prompt_id нигде нет
                    queue_running = queue_status.get("queue_running", [])
                    queue_pending = queue_status.get("queue_pending", [])
                    
                    prompt_in_queue = False
                    for item in queue_running + queue_pending:
                        if isinstance(item, list) and len(item) >= 2:
                            pid = str(item[1] if len(item) > 1 else "")
                            if pid == prompt_id:
                                prompt_in_queue = True
                                break
                    
                    # Если prompt не в очереди
                    if not prompt_in_queue:
                        # ROBUST: если history пустой - retry несколько раз
                        if not h.get(prompt_id):
                            if empty_history_retries < history_retry:
                                empty_history_retries += 1
                                log.info(
                                    f"Prompt {prompt_id} not in queue but history empty "
                                    f"(retry {empty_history_retries}/{history_retry})"
                                )
                                await asyncio.sleep(2.0)  # Долго ждём перед retry
                                continue
                            else:
                                # После N retries считаем что провалился
                                log.error(
                                    f"Prompt {prompt_id} completed without outputs after {empty_history_retries} retries "
                                    f"(likely OOM/error)"
                                )
                                self.last_error = (
                                    "ComfyUI completed prompt without outputs (likely OOM). "
                                    "Check ComfyUI logs or reduce resolution/frames/steps."
                                )
                                return None
                        
                        # History есть, но outputs пустые
                        else:
                            prompt_status = h[prompt_id].get("status", {})
                            status_str = prompt_status.get("status_str", "unknown")
                            log.warning(
                                f"Prompt {prompt_id} completed with status='{status_str}' "
                                f"but no outputs found"
                            )
                            self.last_error = f"Prompt completed with status '{status_str}' but no outputs"
                            return None
                    
                    if check_count % 10 == 0:  # Каждые 10 проверок логируем статус
                        log.debug(
                            f"Waiting for {prompt_id}: in_queue={prompt_in_queue}, "
                            f"checks={check_count}, empty_retries={empty_history_retries}"
                        )
                
            except Exception as e:
                last_err = str(e)
                log.warning(f"wait_for_result check {check_count} error: {e}")
            
            await asyncio.sleep(poll_sec)
        
        # Timeout
        if last_err:
            log.warning(f"wait_for_result timeout after {check_count} checks, last error: {last_err}")
        else:
            log.warning(f"wait_for_result timeout after {check_count} checks, no output received")
        
        self.last_error = f"Timeout after {timeout}s (no output from ComfyUI)"
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

    async def download_file(self, filename: str, subfolder: str = "", file_type: str = "output") -> bytes:
        """
        Скачивает файл через /view с ретраями.
        """
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                return await self._download_file_once(filename, subfolder=subfolder, file_type=file_type)
            except Exception as e:
                last_err = e
                self.log.warning("download /view failed attempt=%s filename=%s: %s", attempt, filename, e)
                await asyncio.sleep(0.5 * attempt)
        if last_err:
            raise last_err
        raise RuntimeError("download_file failed")
