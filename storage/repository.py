from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import aiosqlite

from utils.logger import get_logger

log = get_logger(__name__)

class SQLiteRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    async def ensure_user(self, user_id: int, default_language: str = "ru") -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cur = await db.execute("INSERT OR IGNORE INTO users(user_id, language) VALUES(?, ?)", (user_id, default_language))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def get_user_language(self, user_id: int, fallback: str = "ru") -> str:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if row and row[0]:
                return str(row[0])
            return fallback

    async def set_user_language(self, user_id: int, language: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("""
                INSERT INTO users(user_id, language, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET language=excluded.language, updated_at=CURRENT_TIMESTAMP
            """, (user_id, language))
            await db.commit()

    async def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT llm_enabled, llm_provider, llm_model, selected_workflow FROM user_settings WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if not row:
                return {"llm_enabled": False, "llm_provider": "disabled", "llm_model": "llama2", "selected_workflow": None}
            return {"llm_enabled": bool(row[0]), "llm_provider": row[1], "llm_model": row[2], "selected_workflow": row[3]}

    async def update_user_setting(self, user_id: int, key: str, value: Any) -> None:
        allowed = {"llm_enabled", "llm_provider", "llm_model", "selected_workflow"}
        if key not in allowed:
            raise ValueError("Invalid setting key")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (user_id,))
            await db.execute(f"UPDATE user_settings SET {key} = ? WHERE user_id = ?", (value, user_id))
            await db.commit()
            log.info(f"User {user_id} setting updated: {key}")

    async def get_generation_settings(self, user_id: int) -> Dict[str, Any]:
        """Получает настройки генерации пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT quality, aspect, seed_mode, seed_value, steps, cfg FROM generation_settings WHERE user_id = ?",
                (user_id,)
            )
            row = await cur.fetchone()
            if not row:
                return {
                    "quality": "balanced",
                    "aspect": "1:1",
                    "seed_mode": "random",
                    "seed_value": 0,
                    "steps": 20,
                    "cfg": 7.5
                }
            return {
                "quality": row[0],
                "aspect": row[1],
                "seed_mode": row[2],
                "seed_value": row[3],
                "steps": row[4],
                "cfg": row[5]
            }

    async def update_generation_setting(self, user_id: int, key: str, value: Any) -> None:
        """Обновляет одну настройку генерации."""
        allowed = {"quality", "aspect", "seed_mode", "seed_value", "steps", "cfg"}
        if key not in allowed:
            raise ValueError(f"Invalid setting key: {key}")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("INSERT OR IGNORE INTO generation_settings(user_id) VALUES(?)", (user_id,))
            await db.execute(
                f"UPDATE generation_settings SET {key} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (value, user_id)
            )
            await db.commit()
            log.info(f"User {user_id} generation setting updated: {key}={value}")

    async def reset_generation_settings(self, user_id: int) -> None:
        """Сбрасывает настройки генерации на значения по умолчанию."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("DELETE FROM generation_settings WHERE user_id = ?", (user_id,))
            await db.commit()
            log.info(f"User {user_id} generation settings reset")
