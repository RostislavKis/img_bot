from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.keyboards.main_menu import get_back_keyboard

router = Router()


def _safe_not_modified(e: Exception) -> bool:
    return "message is not modified" in str(e)


HELP_TEXT_RU = """🧠 <b>СПРАВКА ПО ГЕНЕРАЦИИ</b>

<b>📸 КАРТИНКА (DEV) — качество</b>
• Команда: нажми кнопку "📸 Картинка" или напиши <code>dev:</code> перед промптом
• Время: ~2 минуты | Размер: 1024×1024 | Модель: FLUX DEV FP8
• Для: портреты, арт, детали, реализм

<b>⚡ БЫСТРО (Schnell) — скорость</b>
• Команда: нажми кнопку "⚡ Быстро" или напиши <code>fast:</code>
• Время: ~30 сек | Размер: 1024×1024 | Модель: FLUX Schnell FP8
• Для: наброски, много вариантов, быстро

<b>🎬 ВИДЕО (AnimateDiff)</b>
• Команда: нажми кнопку "🎬 Видео" или напиши <code>video:</code>
• 16 фреймов GIF, ~1-2 минуты, размер 512×512

<b>✏️ РЕДАКТИРОВАНИЕ (inpainting)</b>
• Процесс: 1) Отправь фото  2) Напиши что изменить
• Примеры: <code>Измени фон на пляж</code>, <code>Добавь очки</code>

<b>✨ УЛУЧШИТЬ ФОТО (upscale)</b>
• Процесс: 1) Отправь фото  2) Бот улучшит качество

<b>💡 КАК ПИСАТЬ ХОРОШИЙ ПРОМПТ</b>

<b>✅ ПРАВИЛЬНО:</b>
<code>Красивая девушка, портрет, студийный свет, фотография 4K, детали</code>
<code>Дракон парит над облаками, эпическое, фэнтези арт, детали</code>

<b>❌ НЕПРАВИЛЬНО:</b>
<code>картинка</code> (слишком общее)
<code>красивое</code> (не конкретно)

<b>🎨 СТИЛИ:</b>
• Реализм: фотография, реалистично, 4K, детали
• Арт: иллюстрация, живопись, эскиз
• Аниме: манга, в стиле Ghibli, яркие цвета
• Фэнтези: магия, эпическое, мистическое

<b>⚠️ ИСКЛЮЧЕНИЕ (negative):</b>
<code>Девушка, без очков, без татуировок</code>
<code>Озеро, без людей, без зданий</code>

<b>⚙️ ПАРАМЕТРЫ:</b>
• Качество: ⚡ быстро / ⚖️ баланс / 🎨 высокое
• Соотношение: 1:1, 4:5, 16:9, 9:16
• Seed: 🎲 случайный / 📌 фиксированный
• Шаги: 4 / 20 / 28
• CFG: 🔅 низкая / 🔆 средняя / 🔆 высокая

<b>⌨️ ПРЕФИКСЫ:</b>
• <code>dev:</code> → высокое качество
• <code>fast:</code> → быстро
• <code>xl:</code> → фотореализм
• <code>video:</code> → видео
• <code>edit:</code> → редактирование

<b>❓ FAQ</b>
<b>Как повторить результат?</b> → Используй фиксированный seed
<b>Почему не нравится?</b> → Добавь больше деталей: стиль, свет, композицию
<b>Какой режим выбрать?</b> → ⚡ для набросков, 📸 для качества, 🎬 для видео

💡 <b>Экспериментируй! Каждый раз будет новый результат. Удачи!</b>
"""


HELP_TEXT_EN = """🧠 <b>GENERATION GUIDE</b>

<b>📸 IMAGE (DEV) — Quality</b>
• Click "📸 Image" or write <code>dev:</code>
• ~2 min | 1024×1024 | FLUX DEV FP8
• For: portraits, art, detailed, realistic

<b>⚡ FAST (Schnell)</b>
• Click "⚡ Quick" or write <code>fast:</code>
• ~30 sec | 1024×1024 | FLUX Schnell FP8
• For: sketches, variations, quick

<b>🎬 VIDEO (AnimateDiff)</b>
• Click "🎬 Video" or write <code>video:</code>
• 16 frame GIF, ~1-2 min, 512×512

<b>✏️ EDIT PHOTO (inpainting)</b>
• Process: 1) Send photo  2) Write what to change
• Examples: <code>Change background to beach</code>

<b>✨ UPSCALE PHOTO</b>
• Process: 1) Send photo  2) Bot improves it

<b>💡 HOW TO WRITE GOOD PROMPTS</b>

<b>✅ CORRECT:</b>
<code>Beautiful girl, portrait, studio lighting, 4K photo, detailed</code>
<code>Dragon flying over clouds, epic, fantasy art, detailed</code>

<b>❌ WRONG:</b>
<code>picture</code> (too vague)
<code>beautiful</code> (not specific)

<b>🎨 STYLES:</b>
• Realism: photograph, realistic, 4K, detailed
• Art: illustration, painting, sketch
• Anime: manga, Studio Ghibli style, bright colors
• Fantasy: magic, epic, mystical

<b>⚠️ NEGATIVE PROMPTS:</b>
<code>Girl, without glasses, without tattoos</code>
<code>Lake, without people, without buildings</code>

<b>⚙️ SETTINGS:</b>
• Quality: ⚡ fast / ⚖️ balanced / 🎨 high
• Aspect: 1:1, 4:5, 16:9, 9:16
• Seed: 🎲 random / 📌 fixed
• Steps: 4 / 20 / 28
• CFG: 🔅 low / 🔆 medium / 🔆 high

<b>⌨️ PREFIXES:</b>
• <code>dev:</code> → high quality
• <code>fast:</code> → quick
• <code>xl:</code> → photorealism
• <code>video:</code> → video
• <code>edit:</code> → edit

<b>❓ FAQ</b>
<b>Repeat result?</b> → Use fixed seed
<b>Doesn't look good?</b> → Add more details: style, lighting, composition
<b>Which mode?</b> → ⚡ sketches, 📸 quality, 🎬 video

💡 <b>Experiment! Different each time. Good luck!</b>
"""


@router.callback_query(F.data == "action_help")
async def cb_help(call: CallbackQuery, lang: str):
    """Full generation help guide."""
    await call.answer()
    
    help_text = HELP_TEXT_RU if lang == "ru" else HELP_TEXT_EN
    
    try:
        await call.message.edit_text(
            help_text,
            parse_mode="HTML",
            reply_markup=get_back_keyboard(lang)
        )
    except TelegramBadRequest as e:
        if not _safe_not_modified(e):
            await call.message.answer(
                help_text,
                parse_mode="HTML",
                reply_markup=get_back_keyboard(lang)
            )
