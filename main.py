from __future__ import annotations

import argparse
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import load_settings
from utils.logger import configure_logging, get_logger
from storage.database import init_database
from storage.repository import SQLiteRepository
from i18n.loader import LocaleManager
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.i18n import I18nMiddleware
from bot.handlers import start_router, help_router, generate_router
from comfy.client import ComfyUIClient
from comfy.workflow_loader import WorkflowLoader

async def smoke(settings) -> int:
    log = get_logger("smoke")
    await init_database(settings.db_path)
    loader = WorkflowLoader(settings.workflows_dir)
    wf = loader.get_available_workflows()
    log.info(f"Workflows found: {len(wf)}")
    client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)
    ok = await client.check_health()
    await client.close()
    state = "OK" if ok else "NOT OK"
    log.info(f"ComfyUI health: {state}")
    log.info("Smoke done.")
    return 0

async def _set_commands(bot: Bot) -> None:
    cmds = [
        BotCommand(command="start", description="Запуск / Start"),
        BotCommand(command="menu", description="Меню"),
        BotCommand(command="language", description="Язык / Language"),
        BotCommand(command="help", description="Справка"),
    ]
    try:
        await bot.set_my_commands(cmds)
    except Exception:
        pass

async def run_bot(settings) -> int:
    log = get_logger("main")
    token = (settings.bot_token or "").strip()
    if (not token) or ("YOUR_BOT_TOKEN" in token) or ("REPLACE" in token):
        log.error("BOT_TOKEN не задан или плейсхолдер. Впиши реальный токен в .env.local")
        return 2
    await init_database(settings.db_path)
    repo = SQLiteRepository(settings.db_path)
    locales = LocaleManager()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    await _set_commands(bot)
    dp = Dispatcher(storage=MemoryStorage())
    auth = AuthMiddleware(settings.allowed_user_ids)
    i18n = I18nMiddleware(repo=repo, locales=locales, default_language=settings.default_language)
    dp.message.middleware(auth)
    dp.callback_query.middleware(auth)
    dp.message.middleware(i18n)
    dp.callback_query.middleware(i18n)
    dp.include_router(start_router)
    dp.include_router(generate_router)
    dp.include_router(help_router)
    log.info("Bot polling start")
    try:
        await dp.start_polling(bot, settings=settings)
    finally:
        await bot.session.close()
    return 0

def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    return p.parse_args()

async def main() -> int:
    settings = load_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    log = get_logger("main")
    log.info("IMG_BOT start")
    log.info(f"ComfyUI URL: {settings.comfy_url}")
    log.info(f"Allowed users: {settings.allowed_user_ids}")
    log.info(f"BOT_TOKEN loaded: {bool((settings.bot_token or '').strip())}")
    args = _parse_args()
    if args.smoke:
        return await smoke(settings)
    return await run_bot(settings)

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
