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
from core.telegram_pipeline import TelegramComfyPipeline, PipelineConfig
from bot.handlers.t005_pipeline_demo import router as t005_demo_router

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
        BotCommand(command="i2v", description="I2V режим (фото → видео)"),
        BotCommand(command="videoq", description="Видео quality (480p)")
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
    
    # Инициализируем ComfyUI client и workflow loader
    comfy_client = ComfyUIClient(settings.comfy_url, settings.comfy_timeout)
    workflow_loader = WorkflowLoader(settings.workflows_dir)
    
    # Пробрасываем в бот для доступа из handlers (например, /status)
    bot.comfy_client = comfy_client
    bot.workflow_loader = workflow_loader
    
    # Инициализируем Dispatcher ПЕРЕД использовании
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
    dp.include_router(t005_demo_router)
    
    # Инициализируем pipeline для очереди задач
    pipeline = TelegramComfyPipeline(bot, PipelineConfig())
    dp["pipeline"] = pipeline
    bot.pipeline = pipeline
    
    # Startup/shutdown хуки для pipeline
    async def _on_startup(*_):
        await pipeline.start()
    
    async def _on_shutdown(*_):
        await pipeline.stop()
    
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)
    
    log.info("Bot polling start")
    try:
        await dp.start_polling(bot, settings=settings)
    finally:
        await comfy_client.close()
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

# Подсказки по текстовым командам:
# image: <prompt>      - генерация картинки
# enhance: <ignored>   - улучшение последнего фото (или через кнопку)
# edit: <prompt>       - редактирование последнего фото по промпту (или через кнопку)
# video: <prompt>      - генерация видео
#
# Для фото удобнее: отправь фото -> выбери действие кнопкой.
