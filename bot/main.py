"""
Точка входа бота.

Режим выбирается автоматически:
    WEBHOOK_HOST задан  → webhook (прод, за nginx)
    WEBHOOK_HOST пуст   → polling (локальная разработка)

Запуск:  python -m bot.main
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.handlers import admin, instructions, start, subscription
from bot.middlewares.auto_answer import AutoAnswerCallbackMiddleware
from bot.services.scheduler import check_expired_subscriptions, notify_upcoming_expiry
from bot.utils.text_loader import reload_texts
from config import settings
from db.pool import close_pool, healthcheck, init_pool

logger = logging.getLogger("ownnetbot")


def setup_logging() -> None:
    """
    Логи уходят в stdout — их подхватывает journald.
    Файловый обработчик не нужен: ротацией занимается systemd,
    см. deploy/vps1-app/README.md.
    """
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.middleware(AutoAnswerCallbackMiddleware())
    dp.include_router(start.router)
    dp.include_router(subscription.router)
    dp.include_router(instructions.router)
    dp.include_router(admin.router)
    return dp


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(check_expired_subscriptions, "interval", hours=1, args=[bot])
    scheduler.add_job(notify_upcoming_expiry, "cron", hour=7, minute=0, args=[bot])
    return scheduler


async def on_startup(bot: Bot) -> None:
    await init_pool()
    if not await healthcheck():
        raise RuntimeError(
            "PostgreSQL недоступен. Проверьте DB_HOST/DB_PASSWORD в .env "
            "и доступность VPS-2 по приватной сети."
        )
    reload_texts()

    if settings.WEBHOOK_HOST:
        # webhook_url отдаётся в punycode: Bot API не принимает
        # кириллические домены, а основной домен проекта — на кириллице
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
        logger.info("✅ Webhook установлен: %s", settings.webhook_url)
        if settings.webhook_url != settings.webhook_url_display:
            logger.info("   (отображается как %s)", settings.webhook_url_display)
    logger.info("✅ Бот запущен в режиме %s",
                "webhook" if settings.WEBHOOK_HOST else "polling")


async def on_shutdown(bot: Bot) -> None:
    if settings.WEBHOOK_HOST:
        await bot.delete_webhook()
    await close_pool()
    logger.info("🛑 Бот остановлен")


def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(link_preview_is_disabled=True),
    )


async def run_polling() -> None:
    bot = create_bot()
    dp = build_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    scheduler = build_scheduler(bot)
    scheduler.start()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


def run_webhook() -> None:
    """
    aiohttp слушает только 127.0.0.1 — наружу его выставляет nginx,
    он же терминирует TLS.
    """
    bot = create_bot()
    dp = build_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    scheduler = build_scheduler(bot)

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.WEBHOOK_SECRET or None,
    ).register(app, path=settings.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    async def _start_scheduler(_: web.Application) -> None:
        scheduler.start()

    async def _stop_scheduler(_: web.Application) -> None:
        scheduler.shutdown(wait=False)

    app.on_startup.append(_start_scheduler)
    app.on_cleanup.append(_stop_scheduler)

    web.run_app(app, host=settings.WEBAPP_HOST, port=settings.WEBAPP_PORT)


def main() -> None:
    setup_logging()
    if settings.WEBHOOK_HOST:
        run_webhook()
    else:
        try:
            asyncio.run(run_polling())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Остановка по сигналу")


if __name__ == "__main__":
    main()
