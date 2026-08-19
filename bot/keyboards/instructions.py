from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_instructions_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text="Vless для работы (5 устройств)", callback_data="instr_vless"))
    b.add(InlineKeyboardButton(text="AmneziaWG", callback_data="instr_awg"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    b.adjust(1)
    return b.as_markup()


def _platform_menu(prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="📱 Android", callback_data=f"{prefix}_android"))
    b.add(InlineKeyboardButton(text="🍏 iOS", callback_data=f"{prefix}_ios"))
    b.add(InlineKeyboardButton(text="💻 Windows", callback_data=f"{prefix}_windows"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_instructions_main"))
    b.adjust(1)
    return b.as_markup()


def get_vless_instructions_menu() -> InlineKeyboardMarkup:
    return _platform_menu("instr_vless")


def get_awg_instructions_menu() -> InlineKeyboardMarkup:
    return _platform_menu("instr_awg")
