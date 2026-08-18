"""
Пул соединений asyncpg — единственная точка доступа к PostgreSQL.

Используется и ботом (bot/), и API (api/) на VPS-1. База живёт на VPS-2
и доступна только по приватной сети.

Жизненный цикл:
    on_startup:  await init_pool()
    в хендлерах: await fetch(...) / async with acquire() as conn: ...
    on_shutdown: await close_pool()

Плейсхолдеры — нумерованные ($1, $2), а не '?' как в SQLite.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import asyncpg

from config import settings

logger = logging.getLogger("ownnetbot.db")

_pool: Optional[asyncpg.Pool] = None
_lock = asyncio.Lock()


# ── Жизненный цикл ───────────────────────────────────────────────────────────

async def init_pool() -> asyncpg.Pool:
    """Создать пул. Идемпотентно: повторный вызов вернёт существующий пул."""
    global _pool
    async with _lock:
        if _pool is not None:
            return _pool
        _pool = await asyncpg.create_pool(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            min_size=settings.DB_POOL_MIN,
            max_size=settings.DB_POOL_MAX,
            command_timeout=settings.DB_COMMAND_TIMEOUT,
            timeout=settings.DB_CONNECT_TIMEOUT,
            server_settings={"application_name": "ownnetbot"},
        )
        logger.info(
            "✅ Пул PostgreSQL создан: %s:%s/%s (min=%s, max=%s)",
            settings.DB_HOST, settings.DB_PORT, settings.DB_NAME,
            settings.DB_POOL_MIN, settings.DB_POOL_MAX,
        )
        return _pool


async def get_pool() -> asyncpg.Pool:
    """Вернуть пул, создав его при необходимости (ленивая инициализация)."""
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Закрыть пул. Вызывается в on_shutdown."""
    global _pool
    async with _lock:
        if _pool is not None:
            await _pool.close()
            _pool = None
            logger.info("🛑 Пул PostgreSQL закрыт")


async def healthcheck() -> bool:
    """Проверка живости БД — для /health эндпоинта и диагностики при старте."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1
    except Exception:
        logger.exception("Healthcheck PostgreSQL не прошёл")
        return False


# ── Контекстные менеджеры ────────────────────────────────────────────────────

@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """
    Взять соединение из пула.

        async with acquire() as conn:
            rows = await conn.fetch("SELECT ...")
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """
    Соединение внутри транзакции — для операций, которые должны быть атомарными
    (например: создать заказ + отметить использованный тест).

        async with transaction() as conn:
            await conn.execute(...)
            await conn.execute(...)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


# ── Короткие хелперы для одиночных запросов ──────────────────────────────────

async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    """Список строк."""
    pool = await get_pool()
    return await pool.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> Optional[asyncpg.Record]:
    """Одна строка или None."""
    pool = await get_pool()
    return await pool.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    """Одно значение (первая колонка первой строки) или None."""
    pool = await get_pool()
    return await pool.fetchval(query, *args)


async def execute(query: str, *args: Any) -> str:
    """INSERT/UPDATE/DELETE. Возвращает статус вида 'UPDATE 1'."""
    pool = await get_pool()
    return await pool.execute(query, *args)


async def executemany(query: str, args_list: list[tuple]) -> None:
    """Пакетное выполнение одного запроса с разными параметрами."""
    pool = await get_pool()
    await pool.executemany(query, args_list)
