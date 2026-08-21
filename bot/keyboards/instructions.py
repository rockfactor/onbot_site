"""Клавиатуры инструкций. Единственный клиент — INCY (Vless + Amnezia WG)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings

# "family" — семейство интерфейса. У мобильной и десктопной версий INCY разный
# порядок шагов и разные скриншоты, внутри семейства всё одинаково.
# Добавить платформу = добавить запись в словарь, без новых функций и хендлеров.
INCY_PLATFORMS: dict[str, dict[str, str]] = {
    "android": {
        "label": "📱 Android",
        "family": "mobile",
        "store_label": "Google Play",
        "download": "https://play.google.com/store/apps/details?id=llc.itdev.incy",
    },
    "ios": {
        "label": "🍏 iPhone / iPad",
        "family": "mobile",
        "store_label": "App Store",
        "download": "https://apps.apple.com/us/app/incy/id6756943388",
    },
    "windows": {
        "label": "💻 Windows",
        "family": "desktop",
        "store_label": "GitHub (portable .zip)",
        "download": ("https://github.com/INCY-DEV/incy-platforms/releases/"
                     "latest/download/incy-windows-portable.zip"),
    },
    "macos": {
        "label": "🍎 macOS",
        "family": "desktop",
        "store_label": "GitHub (.dmg — Apple Silicon и Intel)",
        "download": "https://github.com/INCY-DEV/incy-platforms/releases/latest",
    },
    "linux": {
        "label": "🐧 Linux",
        "family": "desktop",
        "store_label": "GitHub (.deb / .rpm / portable)",
        "download": "https://github.com/INCY-DEV/incy-platforms/releases/latest",
    },
}

# Ключ протокола используется и в callback_data, и в имени файла-скриншота.
INCY_PROTOCOLS: dict[str, dict[str, str]] = {
    "vless": {
        "label": "🔹 Vless — у меня ссылка",
        "title": "🔹 Vless — добавление по ссылке",
    },
    "awg": {
        "label": "🔸 Amnezia WG — у меня файл .conf",
        "title": "🔸 Amnezia WG — добавление файла .conf",
    },
}


def get_instructions_main_menu() -> InlineKeyboardMarkup:
    """Уровень 1: выбор платформы."""
    b = InlineKeyboardBuilder()
    for key, platform in INCY_PLATFORMS.items():
        b.add(InlineKeyboardButton(
            text=platform["label"], callback_data=f"instr_incy_{key}"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def get_protocol_menu(platform_key: str) -> InlineKeyboardMarkup:
    """Уровень 2: выбор протокола внутри выбранной платформы."""
    b = InlineKeyboardBuilder()
    for key, protocol in INCY_PROTOCOLS.items():
        b.add(InlineKeyboardButton(
            text=protocol["label"],
            callback_data=f"instr_incy_{platform_key}_{key}"))
    b.add(InlineKeyboardButton(
        text="◀️ Другая платформа", callback_data="instructions"))
    b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    b.adjust(1)
    return b.as_markup()


def get_steps_back_menu(platform_key: str) -> InlineKeyboardMarkup:
    """Уровень 3: возврат из пошаговой инструкции."""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text="◀️ Назад", callback_data=f"instr_incy_{platform_key}"))
    b.add(InlineKeyboardButton(
        text="🛠 Тех. поддержка", url=f"https://t.me/{settings.SUPPORT_USERNAME}"))
    b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    b.adjust(1)
    return b.as_markup()
