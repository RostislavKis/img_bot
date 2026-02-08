from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
    ]])


def get_main_menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        photo_text = "📸 Картинка"
        fast_text = "⚡ Быстро"
        video_text = "🎬 Видео"
        edit_text = "✏️ Редактировать"
        upscale_text = "✨ Улучшить"
        help_text = "📖 Справка"
        settings_text = "⚙️ Настройки"
    else:
        photo_text = "📸 Image"
        fast_text = "⚡ Quick"
        video_text = "🎬 Video"
        edit_text = "✏️ Edit"
        upscale_text = "✨ Upscale"
        help_text = "📖 Help"
        settings_text = "⚙️ Settings"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=photo_text, callback_data="action_generate_dev"),
            InlineKeyboardButton(text=fast_text, callback_data="action_generate_schnell"),
        ],
        [
            InlineKeyboardButton(text=video_text, callback_data="action_generate_video"),
            InlineKeyboardButton(text=edit_text, callback_data="action_generate_edit"),
        ],
        [
            InlineKeyboardButton(text=upscale_text, callback_data="action_generate_upscale"),
        ],
        [InlineKeyboardButton(text=help_text, callback_data="action_help")],
        [InlineKeyboardButton(text=settings_text, callback_data="action_settings")],
    ])


def get_back_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    back_text = "⬅️ Назад" if lang == "ru" else "⬅️ Back"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_text, callback_data="action_back")]])


def get_quality_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        fast = "⚡ Быстро"
        balanced = "⚖️ Баланс"
        high = "🎨 Высокое"
    else:
        fast = "⚡ Fast"
        balanced = "⚖️ Balanced"
        high = "🎨 High"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=fast, callback_data="quality_fast")],
        [InlineKeyboardButton(text=balanced, callback_data="quality_balanced")],
        [InlineKeyboardButton(text=high, callback_data="quality_high")],
        [get_back_keyboard(lang).inline_keyboard[0][0]],
    ])


def get_aspect_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1:1", callback_data="aspect_1:1")],
        [InlineKeyboardButton(text="4:5 (портрет)", callback_data="aspect_4:5")],
        [InlineKeyboardButton(text="16:9 (панорама)", callback_data="aspect_16:9")],
        [InlineKeyboardButton(text="9:16 (видео)", callback_data="aspect_9:16")],
        [get_back_keyboard(lang).inline_keyboard[0][0]],
    ])


def get_seed_mode_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        random = "🎲 Случайный"
        fixed = "📌 Зафиксированный"
    else:
        random = "🎲 Random"
        fixed = "📌 Fixed"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=random, callback_data="seed_random")],
        [InlineKeyboardButton(text=fixed, callback_data="seed_fixed")],
        [get_back_keyboard(lang).inline_keyboard[0][0]],
    ])


def get_steps_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        fast = "⚡ 4 шага"
        balanced = "⚖️ 20 шагов"
        high = "🎨 28 шагов"
    else:
        fast = "⚡ 4 steps"
        balanced = "⚖️ 20 steps"
        high = "🎨 28 steps"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=fast, callback_data="steps_4")],
        [InlineKeyboardButton(text=balanced, callback_data="steps_20")],
        [InlineKeyboardButton(text=high, callback_data="steps_28")],
        [get_back_keyboard(lang).inline_keyboard[0][0]],
    ])


def get_cfg_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        low = "🔅 Низкая (1.0)"
        medium = "🔆 Средняя (7.5)"
        high = "🔆 Высокая (15.0)"
    else:
        low = "🔅 Low (1.0)"
        medium = "🔆 Medium (7.5)"
        high = "🔆 High (15.0)"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=low, callback_data="cfg_1.0")],
        [InlineKeyboardButton(text=medium, callback_data="cfg_7.5")],
        [InlineKeyboardButton(text=high, callback_data="cfg_15.0")],
        [get_back_keyboard(lang).inline_keyboard[0][0]],
    ])


def get_settings_menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "ru":
        quality = "🎨 Качество"
        aspect = "📐 Соотношение"
        seed = "🎲 Seed"
        steps = "📊 Шаги"
        cfg = "🔆 CFG"
        reset = "🔄 Сбросить"
    else:
        quality = "🎨 Quality"
        aspect = "📐 Aspect"
        seed = "🎲 Seed"
        steps = "📊 Steps"
        cfg = "🔆 CFG"
        reset = "🔄 Reset"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=quality, callback_data="set_quality")],
        [InlineKeyboardButton(text=aspect, callback_data="set_aspect")],
        [InlineKeyboardButton(text=seed, callback_data="set_seed")],
        [InlineKeyboardButton(text=steps, callback_data="set_steps")],
        [InlineKeyboardButton(text=cfg, callback_data="set_cfg")],
        [InlineKeyboardButton(text=reset, callback_data="set_reset")],
        [get_back_keyboard(lang).inline_keyboard[0][0]],
    ])
