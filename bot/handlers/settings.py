from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from bot.states import SettingsStates
from bot.keyboards.main_menu import (
    get_back_keyboard,
    get_main_menu_keyboard,
    get_settings_menu_keyboard,
    get_quality_keyboard,
    get_aspect_keyboard,
    get_seed_mode_keyboard,
    get_steps_keyboard,
    get_cfg_keyboard,
)
from storage.repository import SQLiteRepository

router = Router()


def _safe_not_modified(e: Exception) -> bool:
    return "message is not modified" in str(e)


def _quality_to_steps_cfg(quality: str) -> tuple[int, float]:
    """Преобразует качество в steps и cfg."""
    mapping = {
        "fast": (4, 1.0),
        "balanced": (20, 7.5),
        "high": (28, 7.5),
    }
    return mapping.get(quality, (20, 7.5))


def _format_settings(settings: dict, lang: str = "ru") -> str:
    """Форматирует настройки для вывода."""
    if lang == "ru":
        quality_names = {"fast": "⚡ Быстро", "balanced": "⚖️ Баланс", "high": "🎨 Высокое"}
        seed_names = {"random": "🎲 Случайный", "fixed": "📌 Фиксированный"}
        msg = (
            "⚙️ <b>ТЕКУЩИЕ НАСТРОЙКИ</b>\n\n"
            f"🎨 Качество: {quality_names.get(settings['quality'], settings['quality'])}\n"
            f"📐 Соотношение: {settings['aspect']}\n"
            f"🎲 Seed: {seed_names.get(settings['seed_mode'], settings['seed_mode'])}\n"
        )
        if settings['seed_mode'] == 'fixed' and settings['seed_value'] > 0:
            msg += f"   Значение: {settings['seed_value']}\n"
        msg += (
            f"📊 Шаги (steps): {settings['steps']}\n"
            f"🔆 CFG/Guidance: {settings['cfg']}\n"
        )
    else:
        quality_names = {"fast": "⚡ Fast", "balanced": "⚖️ Balanced", "high": "🎨 High"}
        seed_names = {"random": "🎲 Random", "fixed": "📌 Fixed"}
        msg = (
            "⚙️ <b>CURRENT SETTINGS</b>\n\n"
            f"🎨 Quality: {quality_names.get(settings['quality'], settings['quality'])}\n"
            f"📐 Aspect Ratio: {settings['aspect']}\n"
            f"🎲 Seed: {seed_names.get(settings['seed_mode'], settings['seed_mode'])}\n"
        )
        if settings['seed_mode'] == 'fixed' and settings['seed_value'] > 0:
            msg += f"   Value: {settings['seed_value']}\n"
        msg += (
            f"📊 Steps: {settings['steps']}\n"
            f"🔆 CFG/Guidance: {settings['cfg']}\n"
        )
    return msg


@router.callback_query(F.data == "action_settings")
async def cb_settings(call: CallbackQuery, repo: SQLiteRepository, lang: str, state: FSMContext):
    """Главное меню настроек."""
    await call.answer()
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    
    try:
        await call.message.edit_text(
            msg,
            parse_mode="HTML",
            reply_markup=get_settings_menu_keyboard(lang)
        )
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_settings_menu_keyboard(lang))


@router.callback_query(F.data == "set_quality")
async def cb_set_quality(call: CallbackQuery, state: FSMContext, lang: str):
    """Выбор качества."""
    await call.answer()
    msg = "🎨 <b>Выберите качество:</b>" if lang == "ru" else "🎨 <b>Choose quality:</b>"
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_quality_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_quality_keyboard(lang))
    await state.set_state(SettingsStates.quality)


@router.callback_query(F.data.startswith("quality_"))
async def cb_quality_selected(call: CallbackQuery, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Сохраняет выбранное качество."""
    quality = call.data.split("_")[1]
    await repo.update_generation_setting(call.from_user.id, "quality", quality)
    
    steps, cfg = _quality_to_steps_cfg(quality)
    await repo.update_generation_setting(call.from_user.id, "steps", steps)
    await repo.update_generation_setting(call.from_user.id, "cfg", cfg)
    
    await call.answer("✅ Качество сохранено!" if lang == "ru" else "✅ Quality saved!")
    await state.clear()
    
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))


@router.callback_query(F.data == "set_aspect")
async def cb_set_aspect(call: CallbackQuery, state: FSMContext, lang: str):
    """Выбор соотношения сторон."""
    await call.answer()
    msg = "📐 <b>Выберите соотношение:</b>" if lang == "ru" else "📐 <b>Choose aspect ratio:</b>"
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_aspect_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_aspect_keyboard(lang))
    await state.set_state(SettingsStates.aspect)


@router.callback_query(F.data.startswith("aspect_"))
async def cb_aspect_selected(call: CallbackQuery, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Сохраняет выбранное соотношение."""
    aspect = call.data.split("_", 1)[1]
    await repo.update_generation_setting(call.from_user.id, "aspect", aspect)
    
    await call.answer("✅ Соотношение сохранено!" if lang == "ru" else "✅ Aspect ratio saved!")
    await state.clear()
    
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))


@router.callback_query(F.data == "set_seed")
async def cb_set_seed(call: CallbackQuery, state: FSMContext, lang: str):
    """Выбор режима seed."""
    await call.answer()
    msg = "🎲 <b>Выберите режим seed:</b>" if lang == "ru" else "🎲 <b>Choose seed mode:</b>"
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_seed_mode_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_seed_mode_keyboard(lang))
    await state.set_state(SettingsStates.seed_mode)


@router.callback_query(F.data == "seed_random")
async def cb_seed_random(call: CallbackQuery, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Выбран случайный seed."""
    await repo.update_generation_setting(call.from_user.id, "seed_mode", "random")
    await repo.update_generation_setting(call.from_user.id, "seed_value", 0)
    
    await call.answer("✅ Seed установлен на случайный!" if lang == "ru" else "✅ Seed set to random!")
    await state.clear()
    
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))


@router.callback_query(F.data == "seed_fixed")
async def cb_seed_fixed(call: CallbackQuery, state: FSMContext, lang: str):
    """Выбран фиксированный seed - просим ввод числа."""
    await call.answer()
    msg = "📌 <b>Введи число для seed:</b>\n(или 0 для случайного)" if lang == "ru" else "📌 <b>Enter seed number:</b>\n(or 0 for random)"
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    await state.set_state(SettingsStates.seed_value)


@router.message(SettingsStates.seed_value)
async def msg_seed_value(message: Message, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Получает и сохраняет значение seed."""
    try:
        seed_val = int(message.text or "0")
        if seed_val < 0:
            seed_val = 0
        
        await repo.update_generation_setting(message.from_user.id, "seed_mode", "fixed")
        await repo.update_generation_setting(message.from_user.id, "seed_value", seed_val)
        
        msg = f"✅ Seed установлен: {seed_val}" if lang == "ru" else f"✅ Seed set to: {seed_val}"
        await message.answer(msg)
        
        await state.clear()
        settings = await repo.get_generation_settings(message.from_user.id)
        msg_settings = _format_settings(settings, lang)
        await message.answer(msg_settings, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except ValueError:
        msg = "❌ Введи целое число!" if lang == "ru" else "❌ Enter a whole number!"
        await message.answer(msg)


@router.callback_query(F.data == "set_steps")
async def cb_set_steps(call: CallbackQuery, state: FSMContext, lang: str):
    """Выбор количества шагов."""
    await call.answer()
    msg = "📊 <b>Выберите количество шагов:</b>" if lang == "ru" else "📊 <b>Choose steps:</b>"
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_steps_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_steps_keyboard(lang))
    await state.set_state(SettingsStates.steps)


@router.callback_query(F.data.startswith("steps_"))
async def cb_steps_selected(call: CallbackQuery, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Сохраняет выбранное количество шагов."""
    steps = int(call.data.split("_")[1])
    await repo.update_generation_setting(call.from_user.id, "steps", steps)
    
    await call.answer("✅ Шаги сохранены!" if lang == "ru" else "✅ Steps saved!")
    await state.clear()
    
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))


@router.callback_query(F.data == "set_cfg")
async def cb_set_cfg(call: CallbackQuery, state: FSMContext, lang: str):
    """Выбор CFG."""
    await call.answer()
    msg = "🔆 <b>Выберите CFG (guidance):</b>" if lang == "ru" else "🔆 <b>Choose CFG (guidance):</b>"
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_cfg_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_cfg_keyboard(lang))
    await state.set_state(SettingsStates.cfg)


@router.callback_query(F.data.startswith("cfg_"))
async def cb_cfg_selected(call: CallbackQuery, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Сохраняет выбранный CFG."""
    cfg = float(call.data.split("_")[1])
    await repo.update_generation_setting(call.from_user.id, "cfg", cfg)
    
    await call.answer("✅ CFG сохранён!" if lang == "ru" else "✅ CFG saved!")
    await state.clear()
    
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))


@router.callback_query(F.data == "set_reset")
async def cb_reset_settings(call: CallbackQuery, repo: SQLiteRepository, state: FSMContext, lang: str):
    """Сбрасывает настройки на значения по умолчанию."""
    await repo.reset_generation_settings(call.from_user.id)
    
    await call.answer("✅ Настройки сброшены!" if lang == "ru" else "✅ Settings reset!")
    await state.clear()
    
    settings = await repo.get_generation_settings(call.from_user.id)
    msg = _format_settings(settings, lang)
    try:
        await call.message.edit_text(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(msg, parse_mode="HTML", reply_markup=get_back_keyboard(lang))
