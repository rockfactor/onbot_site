"""Мелкие утилиты, не относящиеся к конкретному слою."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot, types

from config import settings

logger = logging.getLogger("ownnetbot")


def get_user_info(user: types.User) -> tuple[int, Optional[str], Optional[str], Optional[str]]:
    """
    Данные пользователя для записи в БД.

    В отличие от старой версии возвращаем None вместо строк
    «Не указан» — в PostgreSQL для этого есть NULL.
    """
    return user.id, user.username, user.first_name, user.last_name


def format_user(user_id: int, username: Optional[str],
                first_name: Optional[str] = None,
                last_name: Optional[str] = None) -> str:
    """Строка с описанием пользователя для сообщений админу."""
    parts = [f"👤 ID: {user_id}"]
    if username:
        parts.append(f"(@{username})")
    name = " ".join(p for p in (first_name, last_name) if p)
    if name:
        parts.append(f"| {name}")
    return " ".join(parts)


def format_date(value: Optional[datetime]) -> str:
    """Дата в привычном виде; None и мусор не роняют сообщение."""
    if not value:
        return "срок не указан"
    try:
        return value.strftime("%d.%m.%Y")
    except (AttributeError, ValueError):
        return str(value)


async def check_channel_subscription(bot: Bot, user_id: int) -> bool:
    """Проверка подписки на канал. При ошибке API пропускаем пользователя."""
    if not settings.CHANNEL_USERNAME:
        return True
    try:
        member = await bot.get_chat_member(f"@{settings.CHANNEL_USERNAME}", user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("Не удалось проверить подписку %s: %s", user_id, e)
        return False


def is_admin(user_id: int) -> bool:
    return user_id == settings.ADMIN_ID
