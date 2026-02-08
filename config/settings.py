from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


BASE_DIR = _project_root()
ENV_LOCAL = BASE_DIR / ".env.local"
ENV = BASE_DIR / ".env"


def _load_env_files() -> None:
    for env_path in (ENV_LOCAL, ENV):
        if not env_path.exists():
            continue
        try:
            text = env_path.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, value = s.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip().strip("\"").strip("'")
            if value:
                os.environ[key] = value


_load_env_files()


class Settings(BaseSettings):
    """Настройки приложения (читаются из .env.local и .env)."""

    model_config = SettingsConfigDict(
        env_file=(
            str(ENV_LOCAL),
            str(ENV),
        ),
        env_file_encoding="utf-8-sig",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    bot_token: str = Field(..., alias="BOT_TOKEN")
    allowed_user_ids: list[int] = Field(default_factory=list, alias="ALLOWED_USER_IDS")
    default_language: str = Field("ru", alias="DEFAULT_LANGUAGE")
    debug: bool = Field(False, alias="DEBUG")

    # ComfyUI
    comfy_url: str = Field("http://127.0.0.1:8188", alias="COMFY_URL")
    comfy_timeout: int = Field(600, alias="COMFY_TIMEOUT")
    comfy_output_dir: Path = Field(
        Path(r"D:\ComfyUI\output"),
        alias="COMFY_OUTPUT_DIR",
    )
    workflows_dir: Path = Field(BASE_DIR / "workflows", alias="WORKFLOWS_DIR")

    # Storage / logs
    db_path: Path = Field(BASE_DIR / "data" / "bot.db", alias="DB_PATH")
    logs_dir: Path = Field(BASE_DIR / "logs", alias="LOGS_DIR")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Queue
    max_concurrent_tasks: int = Field(1, alias="MAX_CONCURRENT_TASKS")

    # LLM (optional)
    llm_provider: str = Field("disabled", alias="LLM_PROVIDER")
    llm_endpoint: str = Field("http://127.0.0.1:11434", alias="LLM_ENDPOINT")
    llm_model: str = Field("llama2", alias="LLM_MODEL")

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_allowed_user_ids(cls, v: Any) -> list[int]:
        if v is None:
            return []
        if isinstance(v, list):
            out: list[int] = []
            for x in v:
                try:
                    out.append(int(x))
                except Exception:
                    continue
            return out
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            out: list[int] = []
            for part in s.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    out.append(int(part))
                except Exception:
                    continue
            return out
        return []


def load_settings() -> Settings:
    return Settings()






