from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

class GenStates(StatesGroup):
    waiting_prompt = State()
    running = State()
    
class MenuStates(StatesGroup):
    main_menu = State()
    
class SettingsStates(StatesGroup):
    quality = State()
    aspect = State()
    seed_mode = State()
    seed_value = State()
    steps = State()
    cfg = State()

class EditStates(StatesGroup):
    waiting_photo = State()
    waiting_prompt = State()
    running = State()
