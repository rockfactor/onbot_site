"""Инструкции по установке клиентов Vless и AmneziaWG."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.types import FSInputFile

from bot.keyboards.instructions import (
    get_awg_instructions_menu, get_instructions_main_menu,
    get_vless_instructions_menu,
)

router = Router()
logger = logging.getLogger("ownnetbot")

IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

VLESS_STEPS = ("После установки:\n"
               "1️⃣ Скопируйте ссылку подписки.\n"
               "2️⃣ Нажмите «+» → «Вставить из буфера».\n"
               "3️⃣ Включите соединение.")

AWG_STEPS = ("После установки:\n"
             "1️⃣ Нажмите «+» в углу экрана.\n"
             "2️⃣ Выберите «Импорт из файла или архива», укажите имя соединения.\n"
             "3️⃣ Включите соединение переключателем.")

VLESS_LINKS = {
    "android": "📱 Android:\nhttps://play.google.com/store/apps/details?id=com.happproxy",
    "ios": "🍏 iOS:\nhttps://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
    "windows": ("💻 Windows:\nhttps://github.com/Happ-proxy/happ-desktop/releases/"
                "latest/download/setup-Happ.x86.exe"),
}

AWG_LINKS = {
    "android": "📱 Android:\nhttps://play.google.com/store/apps/details?id=org.amnezia.awg",
    "ios": "🍏 iOS:\nhttps://apps.apple.com/app/amneziawg/id6478942365",
    "windows": ("💻 Windows:\n"
                "https://github.com/amnezia-vpn/amneziawg-windows-client/releases"),
}

VLESS_IMAGES = {"android": "android_steps.jpg", "ios": "ios_steps.jpg",
                "windows": "windows_steps.jpg"}
AWG_IMAGES = {"android": "awg_android.jpg", "ios": "awg_ios.jpg",
              "windows": "awg_windows.jpg"}


async def _send_photo(bot: Bot, chat_id: int, filename: str, caption: str) -> None:
    """Картинка со скриншотами. Её отсутствие не должно ломать инструкцию."""
    path = IMAGES_DIR / filename
    if not path.exists():
        logger.warning("Изображение не найдено: %s", path)
        return
    try:
        await bot.send_photo(chat_id, FSInputFile(path), caption=caption)
    except Exception as e:
        logger.warning("Не удалось отправить %s: %s", filename, e)


async def _edit_or_send(event: types.CallbackQuery, text: str, **kwargs) -> None:
    try:
        await event.message.edit_text(text, **kwargs)
    except Exception:
        await event.message.answer(text, **kwargs)


@router.callback_query(F.data.in_({"instructions", "back_to_instructions_main"}))
async def show_instructions_main(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, "📘 Выберите тип инструкции:",
                        reply_markup=get_instructions_main_menu())


@router.callback_query(F.data == "instr_vless")
async def show_vless_menu(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, "Vless — выберите платформу:",
                        reply_markup=get_vless_instructions_menu())


@router.callback_query(F.data == "instr_awg")
async def show_awg_menu(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, "AmneziaWG — выберите платформу:",
                        reply_markup=get_awg_instructions_menu())


@router.callback_query(F.data.startswith("instr_vless_"))
async def vless_platform(callback: types.CallbackQuery, bot: Bot) -> None:
    platform = callback.data.rsplit("_", 1)[1]
    if platform not in VLESS_LINKS:
        await callback.answer("❌ Неизвестная платформа", show_alert=True)
        return
    await _send_photo(bot, callback.from_user.id, VLESS_IMAGES[platform], VLESS_STEPS)
    await callback.message.answer(VLESS_LINKS[platform],
                                  reply_markup=get_vless_instructions_menu(),
                                  disable_web_page_preview=True)


@router.callback_query(F.data.startswith("instr_awg_"))
async def awg_platform(callback: types.CallbackQuery, bot: Bot) -> None:
    platform = callback.data.rsplit("_", 1)[1]
    if platform not in AWG_LINKS:
        await callback.answer("❌ Неизвестная платформа", show_alert=True)
        return
    await _send_photo(bot, callback.from_user.id, AWG_IMAGES[platform],
                      f"AmneziaWG\n\n{AWG_STEPS}")
    await callback.message.answer(AWG_LINKS[platform],
                                  reply_markup=get_awg_instructions_menu(),
                                  disable_web_page_preview=True)
