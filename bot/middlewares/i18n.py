from __future__ import annotations

from aiogram import BaseMiddleware

from i18n.loader import LocaleManager
from storage.repository import SQLiteRepository

class I18nMiddleware(BaseMiddleware):
    def __init__(self, repo: SQLiteRepository, locales: LocaleManager, default_language: str):
        self.repo = repo
        self.locales = locales
        self.default_language = default_language

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        user_id = getattr(user, "id", None)
        lang = self.default_language
        if user_id is not None:
            try:
                lang = await self.repo.get_user_language(int(user_id), self.default_language)
            except Exception:
                lang = self.default_language
        data["repo"] = self.repo
        data["locales"] = self.locales
        data["lang"] = lang
        data["t"] = lambda key, default="": self.locales.get_text(lang, key, default)
        return await handler(event, data)
