from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_menu import get_language_keyboard, get_main_menu_keyboard
from storage.repository import SQLiteRepository

router = Router()

def _safe_not_modified(e: Exception) -> bool:
    return "message is not modified" in str(e)

@router.message(Command("start"))
async def cmd_start(message: Message, repo: SQLiteRepository, settings, t, lang):
    user_id = message.from_user.id
    is_new = await repo.ensure_user(user_id, settings.default_language)
    if is_new:
        await message.answer(t("welcome", "🤖 Добро пожаловать!"))
        await message.answer(t("select_language", "Выберите язык:"), reply_markup=get_language_keyboard())
        return
    await message.answer(t("main_menu", "🏠 Главное меню:"), reply_markup=get_main_menu_keyboard(lang))

@router.message(Command("menu"))
async def cmd_menu(message: Message, t, lang, state: FSMContext):
    await state.clear()
    await message.answer(t("main_menu", "🏠 Главное меню:"), reply_markup=get_main_menu_keyboard(lang))

@router.message(Command("language"))
async def cmd_language(message: Message, t):
    await message.answer(t("select_language", "Выберите язык:"), reply_markup=get_language_keyboard())

@router.callback_query(F.data.startswith("lang_"))
async def cb_language(call: CallbackQuery, repo: SQLiteRepository, locales, state: FSMContext):
    code = call.data.split("_", 1)[1]
    if code not in ("ru", "en"):
        await call.answer()
        return
    await repo.set_user_language(call.from_user.id, code)
    await state.clear()
    await call.answer(locales.get_text(code, "choose_language_done", "OK"))
    try:
        await call.message.edit_text(locales.get_text(code, "main_menu", "Menu:"), reply_markup=get_main_menu_keyboard(code))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            raise

@router.callback_query(F.data == "action_back")
async def cb_back(call: CallbackQuery, state: FSMContext, lang):
    await call.answer()
    await state.clear()
    msg = "🏠 Главное меню:" if lang == "ru" else "🏠 Main menu:"
    try:
        await call.message.edit_text(msg, reply_markup=get_main_menu_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, reply_markup=get_main_menu_keyboard(lang))

@router.callback_query(F.data == "action_settings")
async def cb_settings(call: CallbackQuery, lang):
    await call.answer()
    if lang == "ru":
        msg = (
            "⚙️ <b>НАСТРОЙКИ</b>\n\n"
            "📋 <b>Текущие параметры:</b>\n"
            "• Язык: " + ("🇷🇺 Русский" if lang == "ru" else "🇬🇧 English") + "\n"
            "• Модель по умолчанию: FLUX Schnell FP8 (⚡ быстро)\n"
            "• Размер: 1024×1024\n"
            "• Таймаут: 60 сек\n\n"
            "ℹ️ Дополнительные настройки доступны через команду /menu"
        )
    else:
        msg = (
            "⚙️ <b>SETTINGS</b>\n\n"
            "📋 <b>Current parameters:</b>\n"
            "• Language: " + ("🇷🇺 Russian" if lang == "ru" else "🇬🇧 English") + "\n"
            "• Default model: FLUX Schnell FP8 (⚡ quick)\n"
            "• Size: 1024×1024\n"
            "• Timeout: 60 sec\n\n"
            "ℹ️ More settings available via /menu"
        )
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_main_menu_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_main_menu_keyboard(lang))
