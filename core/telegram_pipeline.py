# -*- coding: utf-8 -*-
"""
Telegram → ComfyUI пайплайн: очередь задач, выполнение через comfy/client.py,
отправка результата в Telegram (видео/гиф/изображение/документ).
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError, TelegramBadRequest
from aiogram.types import FSInputFile, Message

from core.job_queue import Job, JobQueue, JobQueueConfig, JobStatus


_VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv"}
_GIF_EXT = {".gif"}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip() or "output"


def _guess_kind_from_path(p: pathlib.Path) -> str:
    ext = p.suffix.lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _GIF_EXT:
        return "gif"
    if ext in _IMG_EXT:
        return "image"
    return "file"


@dataclass(slots=True)
class PipelineConfig:
    concurrency: int = _env_int("PIPELINE_CONCURRENCY", 2)
    queue_maxsize: int = _env_int("PIPELINE_QUEUE_MAXSIZE", 200)

    # базовые таймауты (можно переопределять на уровне job)
    timeout_image_s: int = _env_int("PIPELINE_TIMEOUT_IMAGE_S", 600)
    timeout_video_s: int = _env_int("PIPELINE_TIMEOUT_VIDEO_S", 1800)

    retries: int = _env_int("PIPELINE_RETRIES", 2)

    # если comfy/client.py сохраняет файлы локально — это просто "папка где они окажутся".
    # если он отдаёт путь — мы его используем.
    output_dir: pathlib.Path = pathlib.Path(os.getenv("PIPELINE_OUTPUT_DIR", "storage/outputs")).resolve()


class TelegramComfyPipeline:
    def __init__(self, bot: Bot, cfg: Optional[PipelineConfig] = None) -> None:
        self.bot = bot
        self.cfg = cfg or PipelineConfig()
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

        self._queue = JobQueue(self._worker, JobQueueConfig(concurrency=self.cfg.concurrency, maxsize=self.cfg.queue_maxsize))
        self._user_last_job: dict[int, str] = {}  # user_id -> job_id

    async def start(self) -> None:
        await self._queue.start()

    async def stop(self) -> None:
        await self._queue.stop()

    def get_last_job_id(self, user_id: int) -> Optional[str]:
        return self._user_last_job.get(user_id)

    async def cancel_last(self, user_id: int) -> bool:
        job_id = self._user_last_job.get(user_id)
        if not job_id:
            return False
        return await self._queue.cancel(job_id)

    async def enqueue_from_message(
        self,
        message: Message,
        *,
        kind: str,
        payload: Dict[str, Any],
        status_text: str = "Принято. Ставлю в очередь…",
    ) -> str:
        status_msg = await message.answer(status_text)

        timeout_s = self.cfg.timeout_video_s if kind.lower() == "video" else self.cfg.timeout_image_s

        job = Job(
            kind=kind,
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            payload={
                **payload,
                "_status_message_id": status_msg.message_id,
            },
            timeout_s=timeout_s,
            max_retries=self.cfg.retries,
        )

        job.on_status = self._on_status
        job.on_done = self._on_done
        job.on_error = self._on_error

        self._user_last_job[job.user_id] = job.id
        return await self._queue.enqueue(job)

    async def _on_status(self, job: Job, status: JobStatus, text: str) -> None:
        msg_id = int(job.payload.get("_status_message_id", 0) or 0)
        if not msg_id:
            return
        try:
            await self.bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=msg_id,
                text=f"{text}\n\nСтатус: {status.value}\nОчередь: {self._queue.size}",
            )
        except TelegramBadRequest:
            # например "message is not modified" или нельзя редактировать старое сообщение
            pass
        except TelegramNetworkError:
            pass

    async def _on_done(self, job: Job, result: Any) -> None:
        # result ожидаем либо: путь (str/Path), либо список путей, либо dict с ключом path/paths
        paths: list[pathlib.Path] = []

        if isinstance(result, (str, pathlib.Path)):
            paths = [pathlib.Path(result)]
        elif isinstance(result, list):
            paths = [pathlib.Path(x) for x in result if isinstance(x, (str, pathlib.Path))]
        elif isinstance(result, dict):
            if "path" in result:
                paths = [pathlib.Path(result["path"])]
            elif "paths" in result and isinstance(result["paths"], list):
                paths = [pathlib.Path(x) for x in result["paths"]]

        if not paths:
            await self._send_text(job.chat_id, "✅ Готово, но файл результата не найден (проверь comfy/client.py resolver).")
            return

        # отправляем все, но первый — как основной
        for i, p in enumerate(paths, start=1):
            try:
                await self._send_file(job.chat_id, p, caption=("✅ Результат" if i == 1 else None))
            except TelegramRetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 0.5)
                await self._send_file(job.chat_id, p, caption=("✅ Результат" if i == 1 else None))
            except Exception as e:
                await self._send_text(job.chat_id, f"❌ Не смог отправить файл: {type(e).__name__}: {e}")

    async def _on_error(self, job: Job, exc: Exception) -> None:
        await self._send_text(job.chat_id, f"❌ Ошибка генерации: {type(exc).__name__}: {exc}")

    async def _send_text(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id, text)
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
            await self.bot.send_message(chat_id, text)
        except Exception:
            pass

    async def _send_file(self, chat_id: int, path: pathlib.Path, caption: Optional[str] = None) -> None:
        p = path
        if not p.is_absolute():
            p = (pathlib.Path.cwd() / p).resolve()

        if not p.exists() or not p.is_file():
            raise FileNotFoundError(str(p))

        kind = _guess_kind_from_path(p)
        input_file = FSInputFile(str(p), filename=_safe_filename(p.name))

        if kind == "video":
            await self.bot.send_video(chat_id, input_file, caption=caption)
            return
        if kind == "gif":
            await self.bot.send_animation(chat_id, input_file, caption=caption)
            return
        if kind == "image":
            await self.bot.send_photo(chat_id, input_file, caption=caption)
            return

        await self.bot.send_document(chat_id, input_file, caption=caption)

    async def _worker(self, job: Job) -> Any:
        """
        Здесь связка с comfy/client.py.
        Мы НЕ навязываем сигнатуру: пытаемся вызвать распространённые методы.
        """
        # 1) импорт comfy.client
        from comfy import client as comfy_client_mod  # type: ignore

        # 2) если в comfy.client есть функция run_job(payload)->path
        if hasattr(comfy_client_mod, "run_job") and callable(getattr(comfy_client_mod, "run_job")):
            return await comfy_client_mod.run_job(job.kind, job.payload)  # type: ignore

        # 3) если есть ComfyClient класс
        if hasattr(comfy_client_mod, "ComfyClient"):
            ComfyClient = getattr(comfy_client_mod, "ComfyClient")
            cc = ComfyClient()  # если у вас требуются параметры — добавьте их здесь

            # пробуем методы по приоритету
            for meth_name in ("run", "execute", "generate", "generate_image", "generate_video"):
                if not hasattr(cc, meth_name):
                    continue
                meth = getattr(cc, meth_name)
                if not callable(meth):
                    continue

                # варианты вызова (максимально мягко)
                if meth_name in ("generate_image", "generate_video"):
                    if job.kind.lower() == "video" and meth_name != "generate_video":
                        continue
                    if job.kind.lower() != "video" and meth_name == "generate_video":
                        continue
                    return await meth(**job.payload)  # type: ignore

                # универсально: (kind, payload) или (**payload) или (payload)
                try:
                    return await meth(job.kind, job.payload)  # type: ignore
                except TypeError:
                    try:
                        return await meth(job.payload)  # type: ignore
                    except TypeError:
                        return await meth(**job.payload)  # type: ignore

        raise RuntimeError(
            "Не смог найти точку входа в comfy/client.py. "
            "Ожидается: функция run_job(kind, payload) ИЛИ класс ComfyClient с методами run/execute/generate/... "
            "Подстрой _worker() под ваш comfy/client.py."
        )
