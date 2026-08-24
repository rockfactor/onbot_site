"""
Все запросы к PostgreSQL в одном месте.

Хендлеры не содержат SQL — они вызывают функции отсюда. Это упрощает
переход на новую схему и позволяет менять запросы, не трогая логику бота.

Схема описана в alembic/versions/001_initial_schema.py.
Все временные колонки — TIMESTAMPTZ, поэтому здесь и в вызывающем коде
используется только timezone-aware datetime (datetime.now(timezone.utc)).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import asyncpg

from db.pool import acquire, execute, fetch, fetchrow, fetchval


def utcnow() -> datetime:
    """Текущее время с таймзоной — единственный допустимый способ в проекте."""
    return datetime.now(timezone.utc)


# ── users ────────────────────────────────────────────────────────────────────

async def ensure_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> bool:
    """
    Создать пользователя, если его ещё нет, и обновить профиль, если есть.
    Возвращает True, если это первый запуск (нужно показать welcome).

    Один запрос вместо SELECT + INSERT: исключает гонку при быстрых
    повторных /start.
    """
    row = await fetchrow(
        """
        INSERT INTO users (user_id, username, first_name, last_name, first_start)
        VALUES ($1, $2, $3, $4, TRUE)
        ON CONFLICT (user_id) DO UPDATE
            SET username   = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name  = EXCLUDED.last_name
        RETURNING first_start
        """,
        user_id, username, first_name, last_name,
    )
    return bool(row["first_start"])


async def mark_started(user_id: int) -> None:
    """Погасить флаг первого запуска после показа приветствия."""
    await execute("UPDATE users SET first_start = FALSE WHERE user_id = $1", user_id)


# ── used_tests ───────────────────────────────────────────────────────────────

async def has_used_test(user_id: int, test_type: str) -> bool:
    return await fetchval(
        "SELECT EXISTS(SELECT 1 FROM used_tests WHERE user_id = $1 AND test_type = $2)",
        user_id, test_type,
    )


async def mark_test_used(user_id: int, username: Optional[str], test_type: str) -> None:
    await execute(
        """
        INSERT INTO used_tests (user_id, username, test_type)
        VALUES ($1, $2, $3)
        ON CONFLICT ON CONSTRAINT uq_used_tests_user_type DO NOTHING
        """,
        user_id, username, test_type,
    )


# ── orders ───────────────────────────────────────────────────────────────────

async def create_order(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    subscription_type: str,
    amount: int,
) -> int:
    """Создать заказ и вернуть его id."""
    return await fetchval(
        """
        INSERT INTO orders (user_id, username, first_name, last_name,
                            subscription_type, amount)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        user_id, username, first_name, last_name, subscription_type, amount,
    )


async def get_order(order_id: int) -> Optional[asyncpg.Record]:
    return await fetchrow(
        """
        SELECT id, user_id, username, first_name, last_name,
               subscription_type, amount, status
        FROM orders WHERE id = $1
        """,
        order_id,
    )


async def list_orders() -> list[asyncpg.Record]:
    """Для выгрузки в Excel."""
    return await fetch("SELECT * FROM orders ORDER BY created_at DESC")


# ── user_subscriptions ───────────────────────────────────────────────────────

async def get_active_subscription(user_id: int, sub_type: str) -> Optional[asyncpg.Record]:
    return await fetchrow(
        """
        SELECT id, expires_at FROM user_subscriptions
        WHERE user_id = $1 AND subscription_type = $2 AND is_active
        ORDER BY expires_at DESC NULLS LAST
        LIMIT 1
        """,
        user_id, sub_type,
    )


async def get_renewable_subscription(
    user_id: int, sub_type: str, grace_days: int = 3
) -> Optional[asyncpg.Record]:
    """
    Активная подписка либо недавно истёкшая — чтобы админ мог продлить,
    а не выдавать заново.
    """
    cutoff = utcnow() - timedelta(days=grace_days)
    return await fetchrow(
        """
        SELECT id, expires_at, is_active FROM user_subscriptions
        WHERE user_id = $1 AND subscription_type = $2
          AND (is_active OR expires_at >= $3)
        ORDER BY expires_at DESC NULLS LAST
        LIMIT 1
        """,
        user_id, sub_type, cutoff,
    )


async def list_user_subscriptions(user_id: int) -> list[asyncpg.Record]:
    return await fetch(
        """
        SELECT subscription_type, subscription_link, config_file_id,
               expires_at, is_active
        FROM user_subscriptions
        WHERE user_id = $1
        ORDER BY is_active DESC, expires_at DESC NULLS LAST
        """,
        user_id,
    )


async def activate_subscription(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    sub_type: str,
    days: int,
    order_id: int,
    link: Optional[str] = None,
    config_file_id: Optional[str] = None,
) -> tuple[str, datetime]:
    """
    Выдать или продлить подписку и закрыть заказ — одной транзакцией.

    Возвращает ('активирована'|'продлена', новая дата окончания).
    Если активная подписка есть, срок наращивается от большей из двух дат:
    текущей и старой даты окончания, — чтобы продление не съедало остаток.
    """
    now = utcnow()
    async with acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                """
                SELECT id, expires_at FROM user_subscriptions
                WHERE user_id = $1 AND subscription_type = $2 AND is_active
                ORDER BY expires_at DESC NULLS LAST
                LIMIT 1
                FOR UPDATE
                """,
                user_id, sub_type,
            )

            if existing:
                base = existing["expires_at"] or now
                if base < now:
                    base = now
                new_expires = base + timedelta(days=days)
                await conn.execute(
                    """
                    UPDATE user_subscriptions
                    SET expires_at = $1,
                        notified_expiry = FALSE,
                        is_active = TRUE,
                        subscription_link = COALESCE($2, subscription_link),
                        config_file_id    = COALESCE($3, config_file_id)
                    WHERE id = $4
                    """,
                    new_expires, link, config_file_id, existing["id"],
                )
                action = "продлена"
            else:
                new_expires = now + timedelta(days=days)
                await conn.execute(
                    """
                    INSERT INTO user_subscriptions
                        (user_id, username, first_name, last_name,
                         subscription_type, subscription_link, config_file_id,
                         expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    user_id, username, first_name, last_name,
                    sub_type, link, config_file_id, new_expires,
                )
                action = "активирована"

            await conn.execute(
                """
                UPDATE orders
                SET status = 'approved',
                    subscription_link = COALESCE($1, subscription_link),
                    config_file_id    = COALESCE($2, config_file_id)
                WHERE id = $3
                """,
                link, config_file_id, order_id,
            )

    return action, new_expires


async def renew_subscription(
    user_id: int, sub_type: str, days: int, order_id: int
) -> Optional[datetime]:
    """
    Продлить существующую подписку без выдачи нового конфига.
    Возвращает новую дату окончания или None, если подписки нет.
    """
    now = utcnow()
    async with acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                """
                SELECT id, expires_at FROM user_subscriptions
                WHERE user_id = $1 AND subscription_type = $2
                ORDER BY expires_at DESC NULLS LAST
                LIMIT 1
                FOR UPDATE
                """,
                user_id, sub_type,
            )
            if not existing:
                return None

            base = existing["expires_at"] or now
            if base < now:
                base = now
            new_expires = base + timedelta(days=days)

            await conn.execute(
                """
                UPDATE user_subscriptions
                SET expires_at = $1, is_active = TRUE, notified_expiry = FALSE
                WHERE id = $2
                """,
                new_expires, existing["id"],
            )
            await conn.execute(
                "UPDATE orders SET status = 'approved' WHERE id = $1", order_id
            )
    return new_expires


# ── планировщик ──────────────────────────────────────────────────────────────

async def deactivate_expired() -> list[asyncpg.Record]:
    """
    Погасить истёкшие подписки одним запросом и вернуть их,
    чтобы разослать уведомления.
    """
    return await fetch(
        """
        UPDATE user_subscriptions
        SET is_active = FALSE
        WHERE is_active AND expires_at IS NOT NULL AND expires_at < NOW()
        RETURNING id, user_id, subscription_type
        """
    )


async def list_upcoming_expiry(days: int = 3) -> list[asyncpg.Record]:
    """Подписки, истекающие в ближайшие N дней, по которым ещё не уведомляли."""
    return await fetch(
        """
        SELECT id, user_id, subscription_type, expires_at
        FROM user_subscriptions
        WHERE is_active
          AND NOT notified_expiry
          AND expires_at IS NOT NULL
          AND expires_at > NOW()
          AND expires_at <= NOW() + ($1 || ' days')::interval
        """,
        str(days),
    )


async def mark_expiry_notified(sub_ids: Sequence[int]) -> None:
    if not sub_ids:
        return
    await execute(
        "UPDATE user_subscriptions SET notified_expiry = TRUE WHERE id = ANY($1::bigint[])",
        list(sub_ids),
    )


# ── vpn_nodes ────────────────────────────────────────────────────────────────
# Схема: alembic/versions/002_vpn_nodes.py.
# Здесь только чтение и переключение флагов: строки нод заводятся руками
# при вводе ноды в эксплуатацию, это редкая административная операция,
# а не часть выдачи.

async def get_node(node_id: int) -> Optional[asyncpg.Record]:
    return await fetchrow("SELECT * FROM vpn_nodes WHERE id = $1", node_id)


async def get_node_by_name(name: str) -> Optional[asyncpg.Record]:
    return await fetchrow("SELECT * FROM vpn_nodes WHERE name = $1", name)


async def list_nodes(product: Optional[str] = None) -> list[asyncpg.Record]:
    """Все ноды, при необходимости — только одной продуктовой линейки."""
    if product is None:
        return await fetch("SELECT * FROM vpn_nodes ORDER BY product, priority, id")
    return await fetch(
        "SELECT * FROM vpn_nodes WHERE product = $1 ORDER BY priority, id",
        product,
    )


async def pick_node(product: str) -> Optional[asyncpg.Record]:
    """
    Выбрать ноду для новой выдачи.

    Пока это просто «живая нода с наименьшим priority». Полноценный роутер
    (least-connections, geo) появится, когда нод станет больше одной, —
    сейчас у него нет входных данных: счётчика клиентов на ноде ещё нет,
    он придёт вместе со связкой подписок с нодами.

    Условие accepts_new отличает ротацию обфускации от вывода ноды: при
    ротации нода перестаёт принимать новых, но продолжает обслуживать
    выданных, пока у них не истекут подписки.
    """
    return await fetchrow(
        """
        SELECT * FROM vpn_nodes
        WHERE product = $1 AND is_active AND accepts_new
        ORDER BY priority, id
        LIMIT 1
        """,
        product,
    )


async def set_node_flags(
    node_id: int,
    *,
    is_active: Optional[bool] = None,
    accepts_new: Optional[bool] = None,
) -> None:
    """Переключить флаги ноды. Незаданные значения остаются прежними."""
    if is_active is None and accepts_new is None:
        return
    await execute(
        """
        UPDATE vpn_nodes
           SET is_active   = COALESCE($2, is_active),
               accepts_new = COALESCE($3, accepts_new),
               updated_at  = NOW()
         WHERE id = $1
        """,
        node_id, is_active, accepts_new,
    )
