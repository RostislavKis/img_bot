# -*- coding: utf-8 -*-
"""
Демо handler для T-005 pipeline.
Команды: /gen <prompt>, /video <prompt>, /cancel
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

router = Router()


@router.message(Command("gen"))
async def cmd_gen(message: Message, command: CommandObject) -> None:
    prompt = (command.args or "").strip()
    if not prompt:
        await message.answer("Использование: /gen <текст промпта>")
        return

    pipeline = message.bot.get("pipeline")  # см. подключение в main.py
    if pipeline is None:
        await message.answer("Pipeline не инициализирован (проверь main.py).")
        return

    await pipeline.enqueue_from_message(
        message,
        kind="image",
        payload={"prompt": prompt},
        status_text="🧠 Принято. Очередь…",
    )


@router.message(Command("video"))
async def cmd_video(message: Message, command: CommandObject) -> None:
    prompt = (command.args or "").strip()
    if not prompt:
        await message.answer("Использование: /video <текст промпта>")
        return

    pipeline = message.bot.get("pipeline")
    if pipeline is None:
        await message.answer("Pipeline не инициализирован (проверь main.py).")
        return

    await pipeline.enqueue_from_message(
        message,
        kind="video",
        payload={"prompt": prompt},
        status_text="🎬 Принято. Очередь…",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    pipeline = message.bot.get("pipeline")
    if pipeline is None:
        await message.answer("Pipeline не инициализирован (проверь main.py).")
        return

    ok = await pipeline.cancel_last(message.from_user.id if message.from_user else 0)
    await message.answer("✅ Отменил." if ok else "Нет активной задачи для отмены.")
