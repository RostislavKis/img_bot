# -*- coding: utf-8 -*-
"""РћС‡РµСЂРµРґСЊ Р·Р°РґР°С‡ РіРµРЅРµСЂР°С†РёРё СЃ РїСЂРѕРіСЂРµСЃСЃРѕРј."""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Optional
from core.models import GenerationMode, GenerationTask, TaskStatus
from utils.logger import get_logger
logger = get_logger()
class TaskQueue:
    """РћС‡РµСЂРµРґСЊ Р·Р°РґР°С‡ СЃ РѕРіСЂР°РЅРёС‡РµРЅРёРµРј РїР°СЂР°Р»Р»РµР»СЊРЅРѕСЃС‚Рё Рё РїРѕРґРґРµСЂР¶РєРѕР№ РѕС‚РјРµРЅС‹."""
    def __init__(self, max_concurrent: int = 1):
        self.max_concurrent = max_concurrent
        self.queue: asyncio.Queue[GenerationTask] = asyncio.Queue()
        self.active_tasks: dict[str, GenerationTask] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
    async def add_task(self, user_id: int, workflow_name: str, prompt: str, mode: GenerationMode, metadata: dict | None = None) -> str:
        task_id = str(uuid.uuid4())
        task = GenerationTask(task_id=task_id, user_id=user_id, workflow_name=workflow_name, prompt=prompt, mode=mode, status=TaskStatus.PENDING, metadata=metadata or {})
        self.active_tasks[task_id] = task
        await self.queue.put(task)
        logger.info(f"Р—Р°РґР°С‡Р° РґРѕР±Р°РІР»РµРЅР° РІ РѕС‡РµСЂРµРґСЊ: {task_id} (user_id={user_id})")
        return task_id
    async def process_queue(self, worker_fn: Callable[[GenerationTask], Any]):
        while True:
            task: GenerationTask = await self.queue.get()
            try:
                if task.status == TaskStatus.CANCELLED:
                    logger.info(f"РџСЂРѕРїСѓСЃРє РѕС‚РјРµРЅС‘РЅРЅРѕР№ Р·Р°РґР°С‡Рё: {task.task_id}")
                    continue
                async with self.semaphore:
                    task.status = TaskStatus.QUEUED
                    task.updated_at = datetime.now()
                    task.status = TaskStatus.PROCESSING
                    task.updated_at = datetime.now()
                    await worker_fn(task)
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.updated_at = datetime.now()
                logger.error(f"РћС€РёР±РєР° РІ Р·Р°РґР°С‡Рµ {task.task_id}: {e}")
            finally:
                self.queue.task_done()
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        task = self.active_tasks.get(task_id)
        return task.status if task else None
    async def cancel_task(self, task_id: str) -> bool:
        task = self.active_tasks.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
            task.status = TaskStatus.CANCELLED
            task.updated_at = datetime.now()
            logger.info(f"Р—Р°РґР°С‡Р° РѕС‚РјРµРЅРµРЅР°: {task_id}")
            return True
        return False
