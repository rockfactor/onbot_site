"""
Фоновые задачи APScheduler.

Бэкап БД здесь отсутствует намеренно: PostgreSQL живёт на VPS-2,
и pg_dump по расписанию настраивается там же через cron — см.
deploy/vps2-db/README.md. Бот не должен отвечать за бэкап чужого сервера.
"""
from __future__ import annotations

import logging

from aiogram import Bot

from bot.utils.helpers import format_date
from db import queries

logger = logging.getLogger("ownnetbot")


async def check_expired_subscriptions(bot: Bot) -> None:
    """Погасить истёкшие подписки и уведомить владельцев."""
    try:
        expired = await queries.deactivate_expired()
    except Exception:
        logger.exception("Ошибка при деактивации истёкших подписок")
        return

    for row in expired:
        try:
            await bot.send_message(
                row["user_id"],
                f"⏰ Срок подписки «{row['subscription_type']}» истёк.\n"
                f"Продлите её, чтобы продолжить пользоваться сервисом.",
            )
        except Exception as e:
            logger.warning("Не удалось уведомить %s об истечении: %s", row["user_id"], e)

    if expired:
        logger.info("Деактивировано подписок: %d", len(expired))


async def notify_upcoming_expiry(bot: Bot) -> None:
    """Предупредить за 3 дня до окончания подписки."""
    try:
        rows = await queries.list_upcoming_expiry(days=3)
    except Exception:
        logger.exception("Ошибка при выборке истекающих подписок")
        return

    notified: list[int] = []
    for row in rows:
        try:
            await bot.send_message(
                row["user_id"],
                f"⏰ Подписка *{row['subscription_type']}* истекает "
                f"*{format_date(row['expires_at'])}*.\nПродлите сервис заранее.",
                parse_mode="Markdown",
            )
            notified.append(row["id"])
        except Exception as e:
            logger.warning("Не удалось предупредить %s: %s", row["user_id"], e)

    if notified:
        await queries.mark_expiry_notified(notified)
        logger.info("Отправлено предупреждений об истечении: %d", len(notified))
