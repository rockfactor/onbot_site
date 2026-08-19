"""
Клавиатуры выбора тарифа.

Подписи кнопок формируются из bot/prices.py — тех же данных,
по которым считается сумма заказа.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.prices import (
    AMNEZIA_PRICES, DEVICE_LABELS, MONTH_LABELS, TEST_DAYS_AWG,
    TEST_DAYS_VLESS, VLESS_PRICES,
)


def get_subscription_type_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text="Vless для работы (5 устройств)", callback_data="sub_type_work"))
    b.add(InlineKeyboardButton(text="Amnezia WG", callback_data="sub_type_bypass"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    b.adjust(1)
    return b.as_markup()


def get_vless_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text=f"Тест на {TEST_DAYS_VLESS} дня — бесплатно",
        callback_data="sub_work_test"))
    for months, price in sorted(VLESS_PRICES.items()):
        b.add(InlineKeyboardButton(
            text=f"{MONTH_LABELS[months]} — {price} руб.",
            callback_data=f"sub_work_plan_{months}"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription_type"))
    b.adjust(1)
    return b.as_markup()


def get_amnezia_devices_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text=f"🧪 Тест на {TEST_DAYS_AWG} день — бесплатно",
        callback_data="sub_bypass_test"))
    for devices in sorted(AMNEZIA_PRICES):
        b.add(InlineKeyboardButton(
            text=DEVICE_LABELS[devices],
            callback_data=f"sub_bypass_devices_{devices}"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription_type"))
    b.adjust(1)
    return b.as_markup()


def get_amnezia_plans_menu(devices: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for months, price in sorted(AMNEZIA_PRICES[devices].items()):
        b.add(InlineKeyboardButton(
            text=f"{MONTH_LABELS[months]} — {price} руб.",
            callback_data=f"sub_bypass_plan_{devices}_{months}"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_amnezia_devices"))
    b.adjust(1)
    return b.as_markup()


# ── Админские клавиатуры ─────────────────────────────────────────────────────

def get_admin_approve_keyboard(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Выдать", callback_data=f"approve_{order_id}"))
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


def get_admin_renew_keyboard(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🔁 Продлить", callback_data=f"renew_{order_id}"))
    b.add(InlineKeyboardButton(text="✅ Выдать заново", callback_data=f"approve_{order_id}"))
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    b.adjust(1)
    return b.as_markup()


def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()
