# -*- coding: utf-8 -*-
"""
Очередь задач с воркерами, retry-логикой, timeouts и cancel.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class Job:
    kind: str
    chat_id: int
    user_id: int
    payload: Dict[str, Any]

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    timeout_s: int = 600
    max_retries: int = 2
    backoff_base_s: float = 2.0
    backoff_max_s: float = 30.0

    status: JobStatus = JobStatus.QUEUED
    attempt: int = 0
    last_error: str = ""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    # callbacks
    on_status: Optional[Callable[[Job, JobStatus, str], Awaitable[None]]] = None
    on_done: Optional[Callable[[Job, Any], Awaitable[None]]] = None
    on_error: Optional[Callable[[Job, Exception], Awaitable[None]]] = None


@dataclass(slots=True)
class JobQueueConfig:
    concurrency: int = 2
    maxsize: int = 200


class JobQueue:
    def __init__(
        self,
        worker_fn: Callable[[Job], Awaitable[Any]],
        config: Optional[JobQueueConfig] = None,
    ) -> None:
        self._worker_fn = worker_fn
        self._cfg = config or JobQueueConfig()
        self._q: asyncio.Queue[Job] = asyncio.Queue(maxsize=self._cfg.maxsize)
        self._tasks: list[asyncio.Task] = []
        self._jobs: dict[str, Job] = {}
        self._stopping = asyncio.Event()

    @property
    def size(self) -> int:
        return self._q.qsize()

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping.clear()
        for i in range(self._cfg.concurrency):
            self._tasks.append(asyncio.create_task(self._worker_loop(i), name=f"job-worker-{i}"))

    async def stop(self) -> None:
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def enqueue(self, job: Job) -> str:
        self._jobs[job.id] = job
        await self._set_status(job, JobStatus.QUEUED, "В очереди")
        await self._q.put(job)
        return job.id

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        await self._set_status(job, JobStatus.CANCELED, "Отменено")
        return True

    async def _set_status(self, job: Job, status: JobStatus, msg: str) -> None:
        job.status = status
        if job.on_status:
            try:
                await job.on_status(job, status, msg)
            except Exception:
                # статус-коллбек не должен валить воркер
                pass

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, asyncio.CancelledError):
            return False
        # по умолчанию ретраим почти всё "сетевое/временное"
        return isinstance(exc, (TimeoutError, ConnectionError, OSError, asyncio.TimeoutError)) or True

    async def _sleep_backoff(self, attempt: int, base: float, max_s: float) -> None:
        # экспонента + джиттер
        raw = min(max_s, base * (2 ** max(0, attempt - 1)))
        jitter = raw * random.uniform(0.15, 0.35)
        await asyncio.sleep(raw + jitter)

    async def _worker_loop(self, worker_idx: int) -> None:
        while not self._stopping.is_set():
            job: Job
            try:
                job = await self._q.get()
            except asyncio.CancelledError:
                break

            try:
                if job.cancel_event.is_set():
                    await self._set_status(job, JobStatus.CANCELED, "Отменено")
                    continue

                await self._run_job(job)

            finally:
                self._q.task_done()

    async def _run_job(self, job: Job) -> None:
        for attempt in range(1, job.max_retries + 2):  # 1..(retries+1)
            job.attempt = attempt

            if job.cancel_event.is_set():
                await self._set_status(job, JobStatus.CANCELED, "Отменено")
                return

            try:
                await self._set_status(job, JobStatus.RUNNING, f"Обработка (попытка {attempt})")

                async with asyncio.timeout(job.timeout_s):
                    result = await self._worker_fn(job)

                await self._set_status(job, JobStatus.DONE, "Готово")
                if job.on_done:
                    try:
                        await job.on_done(job, result)
                    except Exception:
                        pass
                return

            except asyncio.CancelledError:
                await self._set_status(job, JobStatus.CANCELED, "Отменено")
                return

            except Exception as e:
                job.last_error = f"{type(e).__name__}: {e}"
                if attempt <= job.max_retries and self._is_retryable(e):
                    await self._set_status(job, JobStatus.RETRYING, f"Ошибка, повтор... ({job.last_error})")
                    await self._sleep_backoff(attempt, job.backoff_base_s, job.backoff_max_s)
                    continue

                await self._set_status(job, JobStatus.FAILED, f"Ошибка: {job.last_error}")
                if job.on_error:
                    try:
                        await job.on_error(job, e)
                    except Exception:
                        pass
                return
