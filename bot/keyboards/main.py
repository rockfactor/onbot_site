from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings


def get_main_menu(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy_subscription"))
    b.add(InlineKeyboardButton(text="📖 Мои подписки", callback_data="my_subscriptions"))
    b.add(InlineKeyboardButton(text="📘 Инструкции", callback_data="instructions"))
    b.add(InlineKeyboardButton(text="ℹ️ О нас", callback_data="about"))
    b.add(InlineKeyboardButton(
        text="🛠 Тех. поддержка", url=f"https://t.me/{settings.SUPPORT_USERNAME}"))
    if user_id == settings.ADMIN_ID:
        b.add(InlineKeyboardButton(text="📊 Экспорт заказов", callback_data="export_orders"))
        b.add(InlineKeyboardButton(text="♻️ Обновить тексты", callback_data="reload_texts"))
        b.adjust(2, 2, 1, 2)
    else:
        b.adjust(2, 2, 1)
    return b.as_markup()


def get_back_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return b.as_markup()


def get_channel_gate() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text="📢 Подписаться", url=f"https://t.me/{settings.CHANNEL_USERNAME}"))
    b.add(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription"))
    b.adjust(1)
    return b.as_markup()
