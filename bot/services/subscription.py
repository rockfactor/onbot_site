"""
Бизнес-логика заказов и подписок.

Bot передаётся первым параметром (DI aiogram 3), а не берётся
из глобальной переменной — так функции тестируемы и не зависят
от порядка инициализации.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot

from bot.keyboards.subscription import (
    get_admin_approve_keyboard, get_admin_renew_keyboard,
)
from bot.prices import days_for, is_amnezia, is_test_type, test_kind
from bot.utils.helpers import format_date, format_user
from config import settings
from db import queries

logger = logging.getLogger("ownnetbot")


async def notify_admin_about_order(
    bot: Bot,
    order_id: int,
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    sub_type: str,
    amount: int,
    is_test: bool = False,
) -> None:
    """Сообщить админу о новом заказе с подходящей клавиатурой действий."""
    emoji = "🧪" if is_test else "💰"
    user_info = format_user(user_id, username, first_name, last_name)

    existing = await queries.get_renewable_subscription(user_id, sub_type)
    if existing:
        expires = format_date(existing["expires_at"])
        if existing["is_active"]:
            instruction = f"\n🔁 Активная подписка до {expires}. Можно продлить."
        else:
            instruction = f"\n🔁 Истекла недавно ({expires}). Можно продлить."
        keyboard = get_admin_renew_keyboard(order_id)
    else:
        instruction = (
            "\n📎 Отправьте файл конфигурации (.conf)" if is_amnezia(sub_type)
            else "\n🔗 Отправьте ссылку подписки (https://...)"
        )
        keyboard = get_admin_approve_keyboard(order_id)

    text = (
        f"{emoji} Новый заказ #{order_id}\n{user_info}\n"
        f"📦 {sub_type}\n💸 {amount} руб.{instruction}"
    )
    try:
        await bot.send_message(settings.ADMIN_ID, text, reply_markup=keyboard)
    except Exception:
        logger.exception("Не удалось уведомить админа о заказе %s", order_id)


async def activate_and_notify(
    bot: Bot,
    order_id: int,
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    sub_type: str,
    link: Optional[str] = None,
    config_file_id: Optional[str] = None,
) -> tuple[str, str, bool]:
    """
    Выдать подписку и отправить её пользователю.

    Возвращает (действие, дата окончания, дошло ли сообщение).
    Запись в БД происходит до отправки: если Telegram недоступен,
    подписка всё равно активна, а админ увидит предупреждение.
    """
    days = days_for(sub_type)

    if is_test_type(sub_type):
        await queries.mark_test_used(user_id, username, test_kind(sub_type))

    action, new_expires = await queries.activate_subscription(
        user_id=user_id, username=username, first_name=first_name,
        last_name=last_name, sub_type=sub_type, days=days,
        order_id=order_id, link=link, config_file_id=config_file_id,
    )
    expires_display = format_date(new_expires)
    icon = "🔁" if action == "продлена" else "🎉"

    delivered = False
    try:
        if config_file_id:
            await bot.send_document(
                user_id, config_file_id,
                caption=(f"{icon} Подписка *{sub_type}* {action} до {expires_display}.\n"
                         f"📎 Файл конфигурации:"),
                parse_mode="Markdown",
            )
        else:
            await bot.send_message(
                user_id,
                f"{icon} Подписка *{sub_type}* {action} до {expires_display}.\n🔗 {link}",
                parse_mode="Markdown",
            )
        delivered = True
    except Exception:
        logger.exception("Не удалось доставить подписку пользователю %s", user_id)

    logger.info("Заказ #%s обработан для %s (@%s)", order_id, user_id, username)
    return action, expires_display, delivered


async def renew_and_notify(
    bot: Bot,
    order_id: int,
    user_id: int,
    sub_type: str,
) -> tuple[Optional[str], bool]:
    """
    Продлить подписку без выдачи нового конфига.

    Возвращает (дата окончания или None, дошло ли сообщение).
    None означает, что продлевать нечего — нужна выдача заново.
    """
    days = days_for(sub_type)
    new_expires = await queries.renew_subscription(user_id, sub_type, days, order_id)
    if new_expires is None:
        return None, False

    expires_display = format_date(new_expires)
    delivered = False
    try:
        await bot.send_message(
            user_id,
            f"🔁 Подписка *{sub_type}* продлена на {days} дн. "
            f"— до {expires_display}.",
            parse_mode="Markdown",
        )
        delivered = True
    except Exception:
        logger.exception("Не удалось уведомить %s о продлении", user_id)

    logger.info("Заказ #%s продлён для %s", order_id, user_id)
    return expires_display, delivered
