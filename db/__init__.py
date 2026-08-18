"""
Слой доступа к данным OwnNetBot.

    from db import fetch, fetchrow, execute, transaction

Модули:
    pool.py          — пул asyncpg, хелперы запросов (актуальный слой)
    sqlite_legacy.py — старый init_db для SQLite, удаляется после миграции
"""
from db.pool import (
    acquire,
    close_pool,
    execute,
    executemany,
    fetch,
    fetchrow,
    fetchval,
    get_pool,
    healthcheck,
    init_pool,
    transaction,
)

__all__ = [
    "acquire",
    "close_pool",
    "execute",
    "executemany",
    "fetch",
    "fetchrow",
    "fetchval",
    "get_pool",
    "healthcheck",
    "init_pool",
    "transaction",
]
