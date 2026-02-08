from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

class AuthMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: list[int]):
        self.allowed_user_ids = allowed_user_ids

    async def __call__(self, handler, event, data):
        if not self.allowed_user_ids:
            return await handler(event, data)
        user = data.get("event_from_user")
        uid = getattr(user, "id", None)
        if uid in self.allowed_user_ids:
            return await handler(event, data)
        bot = data.get("bot")
        if isinstance(event, Message):
            await bot.send_message(event.chat.id, "⛔ Доступ запрещён.")
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔ Доступ запрещён.", show_alert=True)
        return
