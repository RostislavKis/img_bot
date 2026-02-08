from __future__ import annotations

from pathlib import Path

import aiosqlite

from utils.logger import get_logger

log = get_logger(__name__)

async def init_database(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'ru',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                llm_enabled INTEGER DEFAULT 0,
                llm_provider TEXT DEFAULT 'disabled',
                llm_model TEXT DEFAULT 'llama2',
                selected_workflow TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generation_settings (
                user_id INTEGER PRIMARY KEY,
                quality TEXT DEFAULT 'balanced',
                aspect TEXT DEFAULT '1:1',
                seed_mode TEXT DEFAULT 'random',
                seed_value INTEGER DEFAULT 0,
                steps INTEGER DEFAULT 20,
                cfg REAL DEFAULT 7.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generation_tasks (
                task_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                workflow_name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                result_file TEXT,
                error_message TEXT,
                comfy_prompt_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        await db.commit()
    log.info(f"БД инициализирована: {db_path}")
