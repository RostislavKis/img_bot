from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

from loguru import logger

_CONFIGURED = False

def configure_logging(logs_dir: Path, level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    if os.name == "nt":
        try:
            subprocess.run("chcp 65001 >nul", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level=level, backtrace=False, diagnose=False, format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[module]} | {message}")
    logger.add(logs_dir / "bot.log", level=level, rotation="10 MB", retention="7 days", encoding="utf-8", backtrace=False, diagnose=False, format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[module]} | {message}")
    _CONFIGURED = True

def get_logger(module: str):
    return logger.bind(module=module)
