#!/usr/bin/env python3
"""
Запускать из корня репозитория:
    python3 setup_structure.py

Создаёт новую структуру модулей, не трогает bot.py и данные БД.
"""
import os, sys

def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {path}")

# ── Директории и пустые __init__.py ──────────────────────────────────────────
for d in ["bot/handlers","bot/keyboards","bot/middlewares","bot/services","bot/utils",
          "db","vpn_api","payments","s3","auth"]:
    os.makedirs(d, exist_ok=True)
    init = f"{d}/__init__.py"
    if not os.path.exists(init):
        open(init, "w").close()

print("📁 Директории готовы\n📝 Создаём файлы:")

# ─────────────────────────────────────────────────────────────────────────────
write("config.py", """\
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN:        str
    ADMIN_ID:         int
    CHANNEL_USERNAME: str = "own_netbot"
    SUPPORT_USERNAME: str = "rockfactor"
    SBER_URL: Optional[str] = None

    # PostgreSQL (этап 1)
    DB_HOST:     str = "localhost"
    DB_PORT:     int = 5432
    DB_NAME:     str = "vpnbot"
    DB_USER:     str = "vpnbot_user"
    DB_PASSWORD: str = ""

    # Webhook (этап 1)
    WEBHOOK_URL:    str = ""
    WEBHOOK_SECRET: str = ""
    WEBHOOK_PATH:   str = "/webhook/bot"

    # JWT (этап 3)
    JWT_SECRET: str = ""

    # ЮКасса (этап 2)
    YOOKASSA_SHOP_ID:    str = ""
    YOOKASSA_SECRET_KEY: str = ""

    # S3 (этап 2)
    S3_ENDPOINT:   str = ""
    S3_BUCKET:     str = "vpn-configs"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # VPN панели (этапы 2-4)
    AWG_API_URL:        str = ""
    AWG_API_KEY:        str = ""
    PASARGUARD_API_URL: str = ""
    PASARGUARD_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
""")

write(".env.example", """\
BOT_TOKEN=
ADMIN_ID=
CHANNEL_USERNAME=own_netbot
SUPPORT_USERNAME=rockfactor
SBER_URL=
DB_HOST=10.0.0.2
DB_PORT=5432
DB_NAME=vpnbot
DB_USER=vpnbot_user
DB_PASSWORD=
WEBHOOK_URL=https://your-domain.ru/webhook/bot
WEBHOOK_SECRET=
WEBHOOK_PATH=/webhook/bot
JWT_SECRET=
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
S3_ENDPOINT=
S3_BUCKET=vpn-configs
S3_ACCESS_KEY=
S3_SECRET_KEY=
AWG_API_URL=
AWG_API_KEY=
PASARGUARD_API_URL=
PASARGUARD_API_KEY=
""")

write("requirements.txt", """\
aiogram==3.10.0
aiosqlite==0.20.0
apscheduler==3.10.4
openpyxl==3.1.2
python-dotenv==1.0.0
pydantic-settings==2.3.4
asyncpg==0.29.0
alembic==1.13.2
fastapi==0.111.0
uvicorn[standard]==0.29.0
aioboto3==12.3.0
aiohttp==3.9.5
passlib[bcrypt]==1.7.4
pyjwt==2.8.0
""")

write("bot/states.py", """\
from aiogram.fsm.state import State, StatesGroup


class AdminState(StatesGroup):
    waiting_for_subscription_link = State()
    waiting_for_amnezia_config    = State()
""")

write("bot/middlewares/auto_answer.py", """\
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class AutoAnswerCallbackMiddleware(BaseMiddleware):
    \"\"\"Автоматически отвечает на callback-запросы, если хендлер не сделал это сам.\"\"\"

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass
        return result
""")

write("bot/utils/helpers.py", """\
import logging
import aiosqlite
from aiogram import types, Bot
from config import settings

logger = logging.getLogger("ownnetbot")

AMNEZIA_PRICES: dict[int, dict[int, int]] = {
    1: {1: 187,  2: 340,  3: 505,  6: 898,  12: 1571},
    3: {1: 449,  2: 842,  3: 1178, 6: 2020, 12: 3366},
    5: {1: 655,  2: 1216, 3: 1683, 6: 2805, 12: 4488},
}


def get_user_info(user: types.User) -> tuple:
    return (
        user.id,
        user.username  or "Не указан",
        user.first_name or "Не указано",
        user.last_name  or "Не указано",
    )


def is_amnezia_subscription(sub_type: str) -> bool:
    return "Amnezia WG" in sub_type


def get_days_for_subscription(sub_type: str) -> int:
    if "Тест" in sub_type:
        return 1 if "Amnezia WG" in sub_type else 3
    if "12 месяцев" in sub_type: return 365
    if "6 месяцев"  in sub_type: return 180
    if "3 месяца"   in sub_type: return 90
    if "2 месяца"   in sub_type: return 60
    return 30


async def has_used_test(user_id: int, test_type: str) -> bool:
    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute(
            "SELECT 1 FROM used_tests WHERE user_id=? AND test_type=?",
            (user_id, test_type),
        ) as cur:
            return await cur.fetchone() is not None


async def mark_test_used(user_id: int, username: str, test_type: str) -> None:
    async with aiosqlite.connect("orders2.db") as conn:
        try:
            await conn.execute(
                "INSERT INTO used_tests (user_id, username, test_type) VALUES (?,?,?)",
                (user_id, username, test_type),
            )
            await conn.commit()
        except aiosqlite.IntegrityError:
            pass


async def check_channel_subscription(bot: Bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(f"@{settings.CHANNEL_USERNAME}", user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Ошибка проверки подписки {user_id}: {e}")
        return False
""")

write("bot/utils/text_loader.py", """\
import logging
logger = logging.getLogger("ownnetbot")
_WELCOME: str | None = None
_ABOUT:   str | None = None


def load_about_text() -> str:
    global _ABOUT
    try:
        with open("about.txt", "r", encoding="utf-8") as f:
            _ABOUT = f.read().strip()
        return _ABOUT
    except FileNotFoundError:
        return "ℹ️ Файл about.txt не найден."
    except Exception:
        logger.exception("Ошибка чтения about.txt")
        return "❌ Ошибка чтения файла about.txt"


def get_about_text() -> str:
    global _ABOUT
    if _ABOUT is None:
        _ABOUT = load_about_text()
    return _ABOUT


def load_welcome_text(user_name: str) -> str:
    global _WELCOME
    try:
        if _WELCOME is None:
            try:
                with open("welcome.txt", "r", encoding="utf-8") as f:
                    _WELCOME = f.read().strip()
            except FileNotFoundError:
                _WELCOME = None
        if _WELCOME:
            return _WELCOME.replace("{имя пользователя}", user_name)
        return f"🙋 Привет, {user_name}!\\n⚠️ Файл welcome.txt не найден."
    except Exception:
        logger.exception("Ошибка чтения welcome.txt")
        return "❌ Ошибка чтения файла welcome.txt"


def reload_texts() -> None:
    global _ABOUT, _WELCOME
    _ABOUT = load_about_text()
    try:
        with open("welcome.txt", "r", encoding="utf-8") as f:
            _WELCOME = f.read().strip()
    except FileNotFoundError:
        _WELCOME = None
    except Exception:
        logger.exception("Ошибка перезагрузки welcome.txt")
    logger.info("♻️ Тексты перезагружены")
""")

write("bot/keyboards/main.py", """\
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import settings


def get_main_menu(user_id: int):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy_subscription"))
    b.add(InlineKeyboardButton(text="📖 Мои подписки",   callback_data="my_subscriptions"))
    b.add(InlineKeyboardButton(text="📘 Инструкции",     callback_data="instructions"))
    b.add(InlineKeyboardButton(text="ℹ️ О нас",          callback_data="about"))
    b.add(InlineKeyboardButton(text="🛠 Тех. поддержка", url=f"https://t.me/{settings.SUPPORT_USERNAME}"))
    if user_id == settings.ADMIN_ID:
        b.add(InlineKeyboardButton(text="📊 Экспорт заказов", callback_data="export_orders"))
        b.add(InlineKeyboardButton(text="♻️ Обновить тексты", callback_data="reload_texts"))
        b.adjust(2, 2, 1, 2)
    else:
        b.adjust(2, 2, 1)
    return b.as_markup()


def get_back_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return b.as_markup()
""")

write("bot/keyboards/subscription.py", """\
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.utils.helpers import AMNEZIA_PRICES


def get_subscription_type_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Vless для работы (5 устройств)", callback_data="sub_type_work"))
    b.add(InlineKeyboardButton(text="Amnezia WG", callback_data="sub_type_bypass"))
    b.add(InlineKeyboardButton(text="◀️ Назад",   callback_data="back_to_main"))
    b.adjust(1); return b.as_markup()


def get_subscription_work_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Тест на 3 дня - бесплатно", callback_data="sub_work_test"))
    b.add(InlineKeyboardButton(text="1 месяц - 550 руб.",        callback_data="sub_work_1month"))
    b.add(InlineKeyboardButton(text="3 месяца - 1320 руб.",      callback_data="sub_work_3month"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription_type"))
    b.adjust(1); return b.as_markup()


def get_amnezia_devices_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🧪 Тест на 1 день - бесплатно", callback_data="sub_bypass_test"))
    b.add(InlineKeyboardButton(text="1 устройство", callback_data="sub_bypass_devices_1"))
    b.add(InlineKeyboardButton(text="3 устройства", callback_data="sub_bypass_devices_3"))
    b.add(InlineKeyboardButton(text="5 устройств",  callback_data="sub_bypass_devices_5"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription_type"))
    b.adjust(1); return b.as_markup()


def get_amnezia_plans_menu(devices: int):
    b = InlineKeyboardBuilder()
    labels = {1:"1 месяц",2:"2 месяца",3:"3 месяца",6:"6 месяцев",12:"12 месяцев"}
    for months, price in sorted(AMNEZIA_PRICES[devices].items()):
        b.add(InlineKeyboardButton(
            text=f"{labels[months]} - {price} руб.",
            callback_data=f"sub_bypass_plan_{devices}_{months}",
        ))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_amnezia_devices"))
    b.adjust(1); return b.as_markup()


def get_admin_approve_keyboard(order_id: int):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Выдать/Продлить", callback_data=f"approve_{order_id}"))
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


def get_admin_renew_keyboard(order_id: int):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🔁 Продлить",      callback_data=f"renew_{order_id}"))
    b.add(InlineKeyboardButton(text="✅ Выдать заново", callback_data=f"approve_{order_id}"))
    b.add(InlineKeyboardButton(text="❌ Отмена",        callback_data="admin_cancel"))
    b.adjust(1); return b.as_markup()


def get_admin_cancel_keyboard():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()
""")

write("bot/keyboards/instructions.py", """\
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_instructions_main_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Vless для работы (5 устройств)", callback_data="instr_vless"))
    b.add(InlineKeyboardButton(text="AmneziaWG", callback_data="instr_awg"))
    b.add(InlineKeyboardButton(text="◀️ Назад",  callback_data="back_to_main"))
    b.adjust(1); return b.as_markup()


def get_vless_instructions_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="📱 Android", callback_data="instr_vless_android"))
    b.add(InlineKeyboardButton(text="🍏 iOS",     callback_data="instr_vless_ios"))
    b.add(InlineKeyboardButton(text="💻 Windows", callback_data="instr_vless_windows"))
    b.add(InlineKeyboardButton(text="◀️ Назад",  callback_data="back_to_instructions_main"))
    b.adjust(1); return b.as_markup()


def get_awg_instructions_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="📱 Android", callback_data="instr_awg_android"))
    b.add(InlineKeyboardButton(text="🍏 iOS",     callback_data="instr_awg_ios"))
    b.add(InlineKeyboardButton(text="💻 Windows", callback_data="instr_awg_windows"))
    b.add(InlineKeyboardButton(text="◀️ Назад",  callback_data="back_to_instructions_main"))
    b.adjust(1); return b.as_markup()
""")

write("bot/services/subscription.py", """\
import aiosqlite, logging
from datetime import datetime, timedelta
from aiogram import Bot
from bot.keyboards.subscription import get_admin_approve_keyboard, get_admin_renew_keyboard
from bot.utils.helpers import get_days_for_subscription, is_amnezia_subscription, mark_test_used
from config import settings
logger = logging.getLogger("ownnetbot")


async def _get_existing_subscription(user_id: int, sub_type: str):
    async with aiosqlite.connect("orders2.db") as conn:
        if is_amnezia_subscription(sub_type):
            async with conn.execute(
                "SELECT id, expires_at FROM user_subscriptions"
                " WHERE user_id=? AND subscription_type=? AND is_active=1"
                " ORDER BY expires_at DESC LIMIT 1", (user_id, sub_type)) as cur:
                return await cur.fetchone()
        else:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=3)).isoformat()
            async with conn.execute(
                "SELECT id, expires_at FROM user_subscriptions"
                " WHERE user_id=? AND subscription_type=?"
                "   AND (is_active=1 OR (is_active=0 AND expires_at >= ?))"
                " ORDER BY expires_at DESC LIMIT 1", (user_id, sub_type, cutoff)) as cur:
                return await cur.fetchone()


async def notify_admin_about_order(bot: Bot, order_id, user_id, username,
                                    first_name, last_name, sub_type, amount, is_test=False):
    emoji = "🧪" if is_test else "💰"
    user_info = f"👤 ID: {user_id}"
    if username and username != "Не указан": user_info += f" (@{username})"
    if first_name and first_name != "Не указано": user_info += f" | {first_name}"
    if last_name  and last_name  != "Не указано": user_info += f" {last_name}"
    existing = await _get_existing_subscription(user_id, sub_type)
    if existing:
        try: expires_str = datetime.fromisoformat(existing[1]).strftime("%d.%m.%Y")
        except: expires_str = existing[1]
        instruction = (f"\\n🔁 Активная подписка (до {expires_str}). Нажмите 🔁 Продлить."
                      if is_amnezia_subscription(sub_type)
                      else f"\\n🔁 Истекла недавно (до {expires_str}). Нажмите 🔁 Продлить.")
        keyboard = get_admin_renew_keyboard(order_id)
    else:
        instruction = ("\\n📎 Отправьте файл конфигурации (.conf)" if is_amnezia_subscription(sub_type)
                      else "\\n🔗 Отправьте ссылку подписки (https://...)")
        keyboard = get_admin_approve_keyboard(order_id)
    text = (f"{emoji} Новый заказ #{order_id}\\n{user_info}\\n📦 {sub_type}\\n💸 {amount} руб."
            f"{instruction}")
    try:
        await bot.send_message(settings.ADMIN_ID, text, reply_markup=keyboard)
    except Exception as e:
        logger.exception(f"Не удалось уведомить админа о заказе {order_id}: {e}")


async def process_subscription_activation(bot: Bot, order_id, user_id, username,
                                           first_name, last_name, sub_type,
                                           link=None, config_file_id=None, config_file_name=None):
    async with aiosqlite.connect("orders2.db") as conn:
        now = datetime.now(); days = get_days_for_subscription(sub_type)
        if "Тест" in sub_type:
            await mark_test_used(user_id, username, "bypass" if is_amnezia_subscription(sub_type) else "work")
        expires = now + timedelta(days=days)
        async with conn.execute(
            "SELECT id, expires_at FROM user_subscriptions WHERE user_id=? AND subscription_type=? AND is_active=1",
            (user_id, sub_type)) as cur:
            active = await cur.fetchone()
        if active:
            try: old_exp = datetime.fromisoformat(active[1])
            except: old_exp = now
            new_exp = max(old_exp, now) + timedelta(days=days)
            if config_file_id:
                await conn.execute("UPDATE user_subscriptions SET expires_at=?, config_file_id=?, notified_expiry=0 WHERE id=?",
                                   (new_exp.isoformat(), config_file_id, active[0]))
            else:
                await conn.execute("UPDATE user_subscriptions SET expires_at=?, subscription_link=?, notified_expiry=0 WHERE id=?",
                                   (new_exp.isoformat(), link, active[0]))
            action_text = "продлена"; exp_display = new_exp.strftime("%d.%m.%Y")
        else:
            try:
                if config_file_id:
                    await conn.execute(
                        "INSERT INTO user_subscriptions (user_id, username, first_name, last_name, config_file_id, subscription_type, expires_at) VALUES (?,?,?,?,?,?,?)",
                        (user_id, username, first_name, last_name, config_file_id, sub_type, expires.isoformat()))
                else:
                    await conn.execute(
                        "INSERT INTO user_subscriptions (user_id, username, first_name, last_name, subscription_link, subscription_type, expires_at) VALUES (?,?,?,?,?,?,?)",
                        (user_id, username, first_name, last_name, link, sub_type, expires.isoformat()))
            except aiosqlite.OperationalError:
                if config_file_id:
                    await conn.execute("INSERT INTO user_subscriptions (user_id, config_file_id, subscription_type, expires_at) VALUES (?,?,?,?)",
                                       (user_id, config_file_id, sub_type, expires.isoformat()))
                else:
                    await conn.execute("INSERT INTO user_subscriptions (user_id, subscription_link, subscription_type, expires_at) VALUES (?,?,?,?)",
                                       (user_id, link, sub_type, expires.isoformat()))
            action_text = "активирована"; exp_display = expires.strftime("%d.%m.%Y")
        if config_file_id:
            await conn.execute("UPDATE orders SET status='approved', config_file_id=? WHERE id=?", (config_file_id, order_id))
        else:
            await conn.execute("UPDATE orders SET status='approved', subscription_link=? WHERE id=?", (link, order_id))
        await conn.commit()
    icon = "🔁" if action_text == "продлена" else "🎉"
    user_notified = False
    try:
        if config_file_id:
            await bot.send_document(user_id, config_file_id,
                caption=f"{icon} Подписка *{sub_type}* {action_text} до {exp_display}.\\n📎 Файл конфигурации:",
                parse_mode="Markdown")
        else:
            await bot.send_message(user_id,
                f"{icon} Подписка *{sub_type}* {action_text} до {exp_display}.\\n🔗 {link}",
                parse_mode="Markdown")
        user_notified = True
    except Exception as e:
        logger.exception(f"Не удалось уведомить {user_id}: {e}")
    logger.info(f"✅ Заказ #{order_id} для {user_id} (@{username})")
    return action_text, exp_display, user_notified
""")

write("bot/services/scheduler.py", """\
import os, logging, aiosqlite
from datetime import datetime
from aiogram import Bot
logger = logging.getLogger("ownnetbot")


async def backup_database() -> None:
    try:
        os.makedirs("backups", exist_ok=True)
        name = f"backups/orders_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        async with aiosqlite.connect("orders2.db") as conn:
            await conn.execute(f"VACUUM INTO '{name}'")
        logger.info(f"✅ Backup: {name}")
        now = datetime.now()
        for f in os.listdir("backups"):
            p = os.path.join("backups", f)
            if os.path.isfile(p) and (now - datetime.fromtimestamp(os.path.getmtime(p))).days > 7:
                os.remove(p)
    except Exception:
        logger.exception("Ошибка backup")


async def check_expired_subscriptions(bot: Bot) -> None:
    try:
        async with aiosqlite.connect("orders2.db") as conn:
            async with conn.execute(
                "SELECT id, user_id, subscription_type, expires_at FROM user_subscriptions WHERE is_active=1"
            ) as cur:
                rows = await cur.fetchall()
            for sub_id, user_id, sub_type, exp_date in rows:
                if not exp_date: continue
                try:
                    if datetime.fromisoformat(exp_date) < datetime.now():
                        await conn.execute("UPDATE user_subscriptions SET is_active=0 WHERE id=?", (sub_id,))
                        await conn.commit()
                        try:
                            await bot.send_message(user_id,
                                f"⏰ Срок подписки «{sub_type}» истёк.\\nПродлите, чтобы продолжить пользоваться.")
                        except Exception: pass
                except ValueError: pass
    except Exception:
        logger.exception("Ошибка check_expired_subscriptions")


async def notify_upcoming_expiry(bot: Bot) -> None:
    try:
        async with aiosqlite.connect("orders2.db") as conn:
            async with conn.execute(
                "SELECT id, user_id, subscription_type, expires_at FROM user_subscriptions"
                " WHERE is_active=1 AND notified_expiry=0 AND expires_at IS NOT NULL"
                " AND date(expires_at) <= date('now','+3 days') AND date(expires_at) > date('now')"
            ) as cur:
                rows = await cur.fetchall()
            for sub_id, user_id, sub_type, expires_at in rows:
                try:
                    exp = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
                    await bot.send_message(user_id,
                        f"⏰ Подписка *{sub_type}* истекает *{exp}*.\\nПродлите сервис.",
                        parse_mode="Markdown")
                    await conn.execute("UPDATE user_subscriptions SET notified_expiry=1 WHERE id=?", (sub_id,))
                    await conn.commit()
                except Exception as e:
                    logger.error(f"Ошибка уведомления для подписки {sub_id}: {e}")
    except Exception:
        logger.exception("Ошибка notify_upcoming_expiry")
""")

write("db/sqlite_legacy.py", """\
\"\"\"Временный модуль init_db для SQLite. Удалить после миграции на PostgreSQL.\"\"\"
import logging, aiosqlite
logger = logging.getLogger("ownnetbot")


async def init_db() -> None:
    async with aiosqlite.connect("orders2.db") as conn:
        await conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
            subscription_type TEXT, amount INTEGER, status TEXT DEFAULT 'pending',
            subscription_link TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)\"\"\")
        await conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS user_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subscription_link TEXT,
            subscription_type TEXT, is_active BOOLEAN DEFAULT 1, expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)\"\"\")
        await conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, first_start BOOLEAN DEFAULT 1)\"\"\")
        await conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS used_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, test_type TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, test_type))\"\"\")
        try:
            async with conn.execute("PRAGMA table_info(orders)") as cur:
                cols = [r[1] for r in await cur.fetchall()]
            for col in ("first_name","last_name","config_file_id"):
                if col not in cols: await conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TEXT")
            async with conn.execute("PRAGMA table_info(user_subscriptions)") as cur:
                cols = [r[1] for r in await cur.fetchall()]
            for col in ("username","first_name","last_name","config_file_id"):
                if col not in cols: await conn.execute(f"ALTER TABLE user_subscriptions ADD COLUMN {col} TEXT")
            if "notified_expiry" not in cols:
                await conn.execute("ALTER TABLE user_subscriptions ADD COLUMN notified_expiry BOOLEAN DEFAULT 0")
            async with conn.execute("PRAGMA table_info(users)") as cur:
                cols = [r[1] for r in await cur.fetchall()]
            for col in ("username","first_name","last_name"):
                if col not in cols: await conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
            async with conn.execute("PRAGMA table_info(used_tests)") as cur:
                cols = [r[1] for r in await cur.fetchall()]
            if "username" not in cols:
                await conn.execute("ALTER TABLE used_tests ADD COLUMN username TEXT")
        except Exception as e:
            logger.warning(f"Ошибка при миграции SQLite: {e}")
        await conn.commit()
""")

write("db/pool.py", """\
\"\"\"Пул соединений asyncpg. Заполняется на этапе 1.\"\"\"
from __future__ import annotations
import asyncpg
from config import settings
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=settings.DB_HOST, port=settings.DB_PORT,
            database=settings.DB_NAME, user=settings.DB_USER,
            password=settings.DB_PASSWORD, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
""")

for mod, doc in [("vpn_api","VPN-адаптеры (AWG, PasarGuard). Реализуется на этапе 2."),
                  ("payments","Оплата через ЮКассу. Реализуется на этапе 2."),
                  ("s3","Клиент Beget S3 (aioboto3). Реализуется на этапе 2."),
                  ("auth","JWT + OTP + двусторонняя привязка TG/email. Реализуется на этапе 3.")]:
    write(f"{mod}/__init__.py", f'"""{doc}"""\n')


write("bot/handlers/start.py", """\
import aiosqlite
from aiogram import Router, F, Bot, types
from aiogram.filters import Command
from bot.keyboards.main import get_main_menu, get_back_menu
from bot.utils.helpers import get_user_info, check_channel_subscription
from bot.utils.text_loader import load_welcome_text, get_about_text
from config import settings
router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    user_id, username, first_name, last_name = get_user_info(message.from_user)
    user_name = message.from_user.first_name or "пользователь"
    if not await check_channel_subscription(bot, user_id):
        await message.answer("📢 Подпишитесь на канал, чтобы пользоваться ботом:",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="📢 Подписаться",url=f"https://t.me/{settings.CHANNEL_USERNAME}")],
                [types.InlineKeyboardButton(text="✅ Я подписался",callback_data="check_subscription")],
            ]))
        return
    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute("SELECT first_start FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            try:
                await conn.execute("INSERT INTO users (user_id, username, first_name, last_name, first_start) VALUES (?,?,?,?,1)",
                    (user_id, username, first_name, last_name))
            except aiosqlite.OperationalError:
                await conn.execute("INSERT INTO users (user_id, first_start) VALUES (?,1)", (user_id,))
            await conn.commit(); first_start = True
        else:
            first_start = bool(row[0])
    if first_start:
        welcome = load_welcome_text(user_name)
        try: await message.answer(welcome, parse_mode="Markdown", disable_web_page_preview=True)
        except: await message.answer(welcome)
        async with aiosqlite.connect("orders2.db") as conn:
            await conn.execute("UPDATE users SET first_start=0 WHERE user_id=?", (user_id,)); await conn.commit()
    await message.answer("👋 Добро пожаловать!\\nВыберите действие:", reply_markup=get_main_menu(user_id))


@router.callback_query(F.data.in_({"main_menu","back_to_main"}))
async def back_to_main(callback: types.CallbackQuery):
    try: await callback.message.edit_text("🏠 Главное меню:", reply_markup=get_main_menu(callback.from_user.id))
    except: await callback.message.answer("🏠 Главное меню:", reply_markup=get_main_menu(callback.from_user.id))


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery, bot: Bot):
    if await check_channel_subscription(bot, callback.from_user.id):
        try: await callback.message.edit_text("👋 Добро пожаловать!\\nВыберите действие:", reply_markup=get_main_menu(callback.from_user.id))
        except: await callback.message.answer("👋 Добро пожаловать!\\nВыберите действие:", reply_markup=get_main_menu(callback.from_user.id))
    else:
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)


@router.callback_query(F.data == "about")
async def show_about(callback: types.CallbackQuery):
    try: await callback.message.edit_text(get_about_text(), reply_markup=get_back_menu())
    except: await callback.message.answer(get_about_text(), reply_markup=get_back_menu())
""")

write("bot/handlers/instructions.py", """\
import os, logging
from aiogram import Router, F, Bot, types
from aiogram.types import FSInputFile
from bot.keyboards.instructions import (
    get_instructions_main_menu, get_vless_instructions_menu, get_awg_instructions_menu)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
router = Router()
logger = logging.getLogger("ownnetbot")
_AWG = ("После установки:\\n1️⃣ В углу нажмите «+»\\n"
        "2️⃣ «Импорт из файла или архива», напишите имя соединения.\\n"
        "3️⃣ Включите соединение кнопкой вкл/выкл.")

async def _photo(bot: Bot, chat_id: int, img: str, caption: str):
    try: await bot.send_photo(chat_id, FSInputFile(os.path.join(BASE_DIR,"images",img)), caption=caption)
    except Exception as e: logger.warning(f"Не удалось отправить {img}: {e}")

@router.callback_query(F.data == "instructions")
async def show_instructions_main(callback: types.CallbackQuery):
    try: await callback.message.edit_text("📘 Выберите тип инструкций:", reply_markup=get_instructions_main_menu())
    except: await callback.message.answer("📘 Выберите тип инструкций:", reply_markup=get_instructions_main_menu())

@router.callback_query(F.data == "back_to_instructions_main")
async def back_to_instructions_main(callback: types.CallbackQuery):
    try: await callback.message.edit_text("📘 Выберите тип инструкций:", reply_markup=get_instructions_main_menu())
    except: await callback.message.answer("📘 Выберите тип инструкций:", reply_markup=get_instructions_main_menu())

@router.callback_query(F.data == "instr_vless")
async def show_vless_instructions(callback: types.CallbackQuery):
    try: await callback.message.edit_text("Vless - выберите платформу:", reply_markup=get_vless_instructions_menu())
    except: await callback.message.answer("Vless - выберите платформу:", reply_markup=get_vless_instructions_menu())

@router.callback_query(F.data == "instr_vless_android")
async def instr_vless_android(callback: types.CallbackQuery, bot: Bot):
    await _photo(bot, callback.from_user.id, "android_steps.jpg",
        "После установки:\\n1️⃣ Скопируйте ссылку.\\n2️⃣ «+» → «Вставить».\\n3️⃣ Включите VPN.")
    await callback.message.answer("📱 Android:\\nhttps://play.google.com/store/apps/details?id=com.happproxy",
        reply_markup=get_vless_instructions_menu())

@router.callback_query(F.data == "instr_vless_ios")
async def instr_vless_ios(callback: types.CallbackQuery, bot: Bot):
    await _photo(bot, callback.from_user.id, "ios_steps.jpg",
        "После установки:\\n1️⃣ Скопируйте ссылку.\\n2️⃣ «+» → «Вставить».\\n3️⃣ Нажмите подключение.")
    await callback.message.answer("🍏 iOS:\\nhttps://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
        reply_markup=get_vless_instructions_menu())

@router.callback_query(F.data == "instr_vless_windows")
async def instr_vless_windows(callback: types.CallbackQuery, bot: Bot):
    await _photo(bot, callback.from_user.id, "windows_steps.jpg",
        "После установки:\\n1️⃣ Скопируйте ссылку.\\n2️⃣ «+» → «Вставить».\\n3️⃣ Включите соединение.")
    await callback.message.answer(
        "💻 Windows:\\nhttps://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x86.exe",
        reply_markup=get_vless_instructions_menu())

@router.callback_query(F.data == "instr_awg")
async def show_awg_instructions(callback: types.CallbackQuery):
    try: await callback.message.edit_text("AmneziaWG - выберите платформу:", reply_markup=get_awg_instructions_menu())
    except: await callback.message.answer("AmneziaWG - выберите платформу:", reply_markup=get_awg_instructions_menu())

@router.callback_query(F.data == "instr_awg_android")
async def instr_awg_android(callback: types.CallbackQuery, bot: Bot):
    await _photo(bot, callback.from_user.id, "awg_android.jpg", f"📱 AmneziaWG Android\\n\\n{_AWG}")
    await callback.message.answer("🔗 Android:\\nhttps://play.google.com/store/apps/details?id=org.amnezia.awg",
        reply_markup=get_awg_instructions_menu())

@router.callback_query(F.data == "instr_awg_ios")
async def instr_awg_ios(callback: types.CallbackQuery, bot: Bot):
    await _photo(bot, callback.from_user.id, "awg_ios.jpg", f"🍏 AmneziaWG iOS\\n\\n{_AWG}")
    await callback.message.answer("🔗 iOS:\\nhttps://apps.apple.com/app/amneziawg/id6478942365",
        reply_markup=get_awg_instructions_menu())

@router.callback_query(F.data == "instr_awg_windows")
async def instr_awg_windows(callback: types.CallbackQuery, bot: Bot):
    await _photo(bot, callback.from_user.id, "awg_windows.jpg", f"💻 AmneziaWG Windows\\n\\n{_AWG}")
    await callback.message.answer("🔗 Windows:\\nhttps://github.com/amnezia-vpn/amneziawg-windows-client/releases",
        reply_markup=get_awg_instructions_menu())
""")

write("bot/main.py", """\
import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.handlers import start, subscription, instructions, admin
from bot.middlewares.auto_answer import AutoAnswerCallbackMiddleware
from bot.services.scheduler import backup_database, check_expired_subscriptions, notify_upcoming_expiry
from bot.utils.text_loader import load_about_text
from db.sqlite_legacy import init_db
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("purchases.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("ownnetbot")


async def on_startup(bot: Bot) -> None:
    await init_db()
    load_about_text()
    logger.info("✅ Бот запущен")

async def on_shutdown(bot: Bot) -> None:
    logger.info("🛑 Бот остановлен")

async def main() -> None:
    bot = Bot(token=settings.BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.callback_query.middleware(AutoAnswerCallbackMiddleware())
    dp.include_router(start.router)
    dp.include_router(subscription.router)
    dp.include_router(instructions.router)
    dp.include_router(admin.router)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(backup_database,             "cron",     hour=3,  minute=0)
    scheduler.add_job(check_expired_subscriptions, "interval", hours=1, args=[bot])
    scheduler.add_job(notify_upcoming_expiry,      "cron",     hour=10, minute=0, args=[bot])
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
""")

write("bot/handlers/subscription.py", """\
import logging, aiosqlite
from datetime import datetime
from aiogram import Router, F, Bot, types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.main import get_back_menu
from bot.keyboards.subscription import (get_subscription_type_menu, get_subscription_work_menu,
    get_amnezia_devices_menu, get_amnezia_plans_menu)
from bot.utils.helpers import get_user_info, has_used_test, AMNEZIA_PRICES
from bot.services.subscription import notify_admin_about_order
from config import settings
router = Router(); logger = logging.getLogger("ownnetbot")
MONTHS = {1:"1 месяц",2:"2 месяца",3:"3 месяца",6:"6 месяцев",12:"12 месяцев"}

@router.callback_query(F.data == "buy_subscription")
async def show_subscription_types(callback: types.CallbackQuery):
    try: await callback.message.edit_text("Выберите тип подписки 👇", reply_markup=get_subscription_type_menu())
    except: await callback.message.answer("Выберите тип подписки 👇", reply_markup=get_subscription_type_menu())

@router.callback_query(F.data == "back_to_subscription_type")
async def back_to_subscription_type(callback: types.CallbackQuery):
    try: await callback.message.edit_text("Выберите тип подписки 👇", reply_markup=get_subscription_type_menu())
    except: await callback.message.answer("Выберите тип подписки 👇", reply_markup=get_subscription_type_menu())

@router.callback_query(F.data == "sub_type_work")
async def show_work_subscriptions(callback: types.CallbackQuery):
    try: await callback.message.edit_text("Vless (5 устройств) - выберите вариант 👇", reply_markup=get_subscription_work_menu())
    except: await callback.message.answer("Vless (5 устройств) - выберите вариант 👇", reply_markup=get_subscription_work_menu())

@router.callback_query(F.data == "sub_type_bypass")
async def show_bypass_subscriptions(callback: types.CallbackQuery):
    try: await callback.message.edit_text("Amnezia WG - выберите количество устройств 👇", reply_markup=get_amnezia_devices_menu())
    except: await callback.message.answer("Amnezia WG - выберите количество устройств 👇", reply_markup=get_amnezia_devices_menu())

@router.callback_query(F.data == "back_to_amnezia_devices")
async def back_to_amnezia_devices(callback: types.CallbackQuery):
    try: await callback.message.edit_text("Amnezia WG - выберите количество устройств 👇", reply_markup=get_amnezia_devices_menu())
    except: await callback.message.answer("Amnezia WG - выберите количество устройств 👇", reply_markup=get_amnezia_devices_menu())

@router.callback_query(F.data.in_({"sub_bypass_devices_1","sub_bypass_devices_3","sub_bypass_devices_5"}))
async def show_amnezia_plans(callback: types.CallbackQuery):
    d = int(callback.data.split("_")[-1])
    label = {1:"1 устройство",3:"3 устройства",5:"5 устройств"}[d]
    try: await callback.message.edit_text(f"Amnezia WG ({label}) - выберите тариф 👇", reply_markup=get_amnezia_plans_menu(d))
    except: await callback.message.answer(f"Amnezia WG ({label}) - выберите тариф 👇", reply_markup=get_amnezia_plans_menu(d))

@router.callback_query(
    F.data.in_({"sub_work_test","sub_work_1month","sub_work_3month","sub_bypass_test"})
    | F.data.startswith("sub_bypass_plan_"))
async def handle_subscription_choice(callback: types.CallbackQuery, bot: Bot):
    user_id, username, first_name, last_name = get_user_info(callback.from_user)
    data = callback.data
    if data in ("sub_work_test","sub_bypass_test"):
        test_type = "work" if data == "sub_work_test" else "bypass"
        if await has_used_test(user_id, test_type):
            text = "❌ Вы уже использовали тестовый период для этого типа подписки.\\n\\n💡 Выберите платный тариф."
            try: await callback.message.edit_text(text, reply_markup=get_back_menu())
            except: await callback.message.answer(text, reply_markup=get_back_menu())
            return
    if data == "sub_work_test":
        sub_type, amount, is_test = "Vless для работы (5 устройств) - Тест 3 дня", 0, True
        limit_msg = "Подписка действует для 5 устройств без лимита трафика."
    elif data == "sub_work_1month":
        sub_type, amount, is_test = "Vless для работы (5 устройств) - 1 месяц", 320, False
        limit_msg = "Подписка действует для 5 устройств без лимита трафика."
    elif data == "sub_work_3month":
        sub_type, amount, is_test = "Vless для работы (5 устройств) - 3 месяца", 770, False
        limit_msg = "Подписка действует для 5 устройств без лимита трафика."
    elif data == "sub_bypass_test":
        sub_type, amount, is_test = "Amnezia WG - Тест 1 день", 0, True
        limit_msg = "Подписка действует без лимита трафика."
    elif data.startswith("sub_bypass_plan_"):
        parts = data.split("_"); devices, months = int(parts[3]), int(parts[4])
        amount = AMNEZIA_PRICES[devices][months]
        sub_type = f"Amnezia WG ({devices} устройство{'в' if devices!=1 else ''}) - {MONTHS[months]}"
        is_test = False; limit_msg = "Подписка действует без лимита трафика."
    else:
        await callback.answer("❌ Неизвестный тариф", show_alert=True); return
    async with aiosqlite.connect("orders2.db") as conn:
        try:
            await conn.execute("INSERT INTO orders (user_id, username, first_name, last_name, subscription_type, amount) VALUES (?,?,?,?,?,?)",
                (user_id, username, first_name, last_name, sub_type, amount))
        except aiosqlite.OperationalError:
            await conn.execute("INSERT INTO orders (user_id, username, subscription_type, amount) VALUES (?,?,?,?)",
                (user_id, username, sub_type, amount))
        await conn.commit()
        async with conn.execute("SELECT last_insert_rowid()") as cur:
            order_id = (await cur.fetchone())[0]
    if is_test:
        text = f"🧪 Вы выбрали *{sub_type}*. Ожидайте подтверждения администратора.\\n\\n{limit_msg}"
        try: await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_menu())
        except: await callback.message.answer(text, parse_mode="Markdown", reply_markup=get_back_menu())
    else:
        if settings.SBER_URL:
            b = InlineKeyboardBuilder()
            b.add(InlineKeyboardButton(text="💳 Перевод СБП на номер +79061803036", url=settings.SBER_URL))
            b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))
            b.adjust(1); markup = b.as_markup()
            text = (f"✅ Вы выбрали *{sub_type}*\\n💸 {amount} руб.\\n\\n"
                    f"Нажмите ниже для оплаты. После оплаты ждите подтверждения.\\n\\n{limit_msg}")
        else:
            markup = get_back_menu()
            text = (f"✅ Вы выбрали *{sub_type}*\\n💸 {amount} руб.\\n\\n"
                    f"❌ Ссылка на оплату не настроена. Свяжитесь с администратором.\\n\\n{limit_msg}")
        try: await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        except: await callback.message.answer(text, parse_mode="Markdown", reply_markup=markup)
    logger.info(f"Заказ #{order_id} от {user_id} (@{username}) ({sub_type})")
    await notify_admin_about_order(bot, order_id, user_id, username, first_name, last_name, sub_type, amount, is_test)

@router.callback_query(F.data == "my_subscriptions")
async def show_my_subscriptions(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute(
            "SELECT subscription_type, subscription_link, expires_at, is_active FROM user_subscriptions"
            " WHERE user_id=? ORDER BY created_at DESC", (user_id,)) as cur:
            subscriptions = await cur.fetchall()
    if not subscriptions:
        text = "📭 У вас пока нет активных подписок.\\n\\n🛒 Приобретите подписку в главном меню."
        try: await callback.message.edit_text(text, reply_markup=get_back_menu())
        except: await callback.message.answer(text, reply_markup=get_back_menu())
        return
    text = "📖 Ваши подписки:\\n\\n"; active_count = 0
    for sub_type, link, expires_at, is_active in subscriptions:
        status = "✅ Активна" if is_active else "❌ Неактивна"
        if expires_at:
            try: expires_text = f"до {datetime.fromisoformat(expires_at).strftime('%d.%m.%Y')}"
            except: expires_text = expires_at
        else: expires_text = "срок не указан"
        text += f"📦 {sub_type}\\n🔗 {link}\\n📅 {expires_text}\\n🟢 {status}\\n\\n"
        if is_active: active_count += 1
    if active_count == 0: text += "❌ Нет активных подписок. Продлите или приобретите новую."
    try: await callback.message.edit_text(text, reply_markup=get_back_menu())
    except: await callback.message.answer(text, reply_markup=get_back_menu())
""")

write("bot/handlers/admin.py", """\
import os, logging, aiosqlite, openpyxl
from datetime import datetime, timedelta
from aiogram import Router, F, Bot, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from bot.keyboards.main import get_main_menu
from bot.keyboards.subscription import get_admin_cancel_keyboard
from bot.states import AdminState
from bot.services.subscription import process_subscription_activation
from bot.utils.helpers import get_days_for_subscription, is_amnezia_subscription
from bot.utils.text_loader import reload_texts
from config import settings
router = Router(); logger = logging.getLogger("ownnetbot")


@router.callback_query(F.data.startswith("approve_"))
async def approve_order(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True); return
    try: order_id = int(callback.data.split("_",1)[1])
    except: await callback.answer("❌ Неверный формат", show_alert=True); return
    async with aiosqlite.connect("orders2.db") as conn:
        try:
            async with conn.execute("SELECT user_id,username,first_name,last_name,subscription_type,status FROM orders WHERE id=?", (order_id,)) as cur:
                row = await cur.fetchone()
            if not row: await callback.answer("❌ Заказ не найден", show_alert=True); return
            user_id,username,first_name,last_name,sub_type,status = row
        except aiosqlite.OperationalError:
            async with conn.execute("SELECT user_id,username,subscription_type,status FROM orders WHERE id=?", (order_id,)) as cur:
                row = await cur.fetchone()
            if not row: await callback.answer("❌ Заказ не найден", show_alert=True); return
            user_id,username,sub_type,status = row; first_name=last_name="Не указано"
    if status == "approved": await callback.answer("✅ Уже обработан", show_alert=True); return
    await state.update_data(order_id=order_id,user_id=user_id,username=username,
        first_name=first_name,last_name=last_name,subscription_type=sub_type)
    if is_amnezia_subscription(sub_type):
        await state.set_state(AdminState.waiting_for_amnezia_config)
        instruction = "📎 Пожалуйста, отправьте файл конфигурации (.conf):"
    else:
        await state.set_state(AdminState.waiting_for_subscription_link)
        instruction = "📝 Пожалуйста, отправьте ссылку для активации:"
    user_info = f"👤 ID: {user_id}"
    if username and username != "Не указан": user_info += f" (@{username})"
    text = f"📝 Заказ #{order_id}\\n{user_info}\\n📦 {sub_type}\\n\\n{instruction}"
    try: await callback.message.edit_text(text, reply_markup=get_admin_cancel_keyboard())
    except: await callback.message.answer(text, reply_markup=get_admin_cancel_keyboard())


@router.callback_query(F.data.startswith("renew_"))
async def renew_order(callback: types.CallbackQuery, bot: Bot):
    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True); return
    try: order_id = int(callback.data.split("_",1)[1])
    except: await callback.answer("❌ Неверный формат", show_alert=True); return
    async with aiosqlite.connect("orders2.db") as conn:
        try:
            async with conn.execute("SELECT user_id,username,first_name,last_name,subscription_type,status FROM orders WHERE id=?", (order_id,)) as cur:
                row = await cur.fetchone()
            if not row: await callback.answer("❌ Заказ не найден", show_alert=True); return
            user_id,username,first_name,last_name,sub_type,status = row
        except aiosqlite.OperationalError:
            async with conn.execute("SELECT user_id,username,subscription_type,status FROM orders WHERE id=?", (order_id,)) as cur:
                row = await cur.fetchone()
            if not row: await callback.answer("❌ Заказ не найден", show_alert=True); return
            user_id,username,sub_type,status = row; first_name=last_name="Не указано"
    if status == "approved": await callback.answer("✅ Уже обработан", show_alert=True); return
    days = get_days_for_subscription(sub_type); now = datetime.now()
    try:
        async with aiosqlite.connect("orders2.db") as conn:
            async with conn.execute("SELECT id,expires_at FROM user_subscriptions WHERE user_id=? AND subscription_type=? ORDER BY expires_at DESC LIMIT 1",
                (user_id, sub_type)) as cur:
                existing = await cur.fetchone()
            if not existing:
                await callback.answer("⚠️ Подписка не найдена — используйте «Выдать заново»", show_alert=True); return
            sub_id, old_str = existing
            try: old_exp = datetime.fromisoformat(old_str)
            except: old_exp = now
            new_exp = max(old_exp, now) + timedelta(days=days)
            await conn.execute("UPDATE user_subscriptions SET expires_at=?,is_active=1,notified_expiry=0 WHERE id=?",
                (new_exp.isoformat(), sub_id))
            await conn.execute("UPDATE orders SET status='approved' WHERE id=?", (order_id,))
            await conn.commit()
        user_notified = False
        try:
            await bot.send_message(user_id, f"🔁 Подписка *{sub_type}* продлена на {days} дн. до {new_exp.strftime('%d.%m.%Y')}.", parse_mode="Markdown")
            user_notified = True
        except Exception as e: logger.exception(f"Не удалось уведомить {user_id}: {e}")
        user_info = f"👤 ID: {user_id}"
        if username and username != "Не указан": user_info += f" (@{username})"
        icon = "✅" if user_notified else "⚠️"
        text = (f"{icon} Продлена!\\n\\n📦 Заказ: #{order_id}\\n{user_info}\\n📅 {sub_type}\\n"
                f"⏳ +{days} дн. до {new_exp.strftime('%d.%m.%Y')}\\n\\n"
                + ("✅ Сообщение отправлено." if user_notified else "⚠️ Пользователь недоступен, БД обновлена."))
        try: await callback.message.edit_text(text)
        except: await callback.message.answer(text)
        logger.info(f"🔁 Заказ #{order_id} продлён для {user_id}")
    except Exception as e:
        logger.exception(f"Ошибка при продлении: {e}")
        await callback.answer("❌ Ошибка при продлении. Попробуйте ещё раз.", show_alert=True)


@router.message(AdminState.waiting_for_subscription_link)
async def process_subscription_link(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != settings.ADMIN_ID: return
    link = message.text.strip()
    if "://" not in link:
        await message.answer("❌ Это не похоже на валидную ссылку. Отправьте корректную ссылку:"); return
    data = await state.get_data()
    if not all([data.get("order_id"), data.get("user_id"), data.get("subscription_type")]):
        await message.answer("❌ Ошибка состояния."); await state.clear(); return
    await _run_activation(message, state, bot, data, link=link)


@router.message(AdminState.waiting_for_amnezia_config)
async def process_amnezia_config(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != settings.ADMIN_ID: return
    if not message.document:
        await message.answer("❌ Пожалуйста, отправьте файл конфигурации (.conf):"); return
    data = await state.get_data()
    if not all([data.get("order_id"), data.get("user_id"), data.get("subscription_type")]):
        await message.answer("❌ Ошибка состояния."); await state.clear(); return
    await _run_activation(message, state, bot, data,
        config_file_id=message.document.file_id, config_file_name=message.document.file_name or "config.conf")


async def _run_activation(message, state, bot, data, link=None, config_file_id=None, config_file_name=None):
    try:
        action, exp, notified = await process_subscription_activation(
            bot, data["order_id"], data["user_id"],
            data.get("username","Не указан"), data.get("first_name","Не указано"),
            data.get("last_name","Не указано"), data["subscription_type"],
            link, config_file_id, config_file_name)
        user_info = f"👤 ID: {data['user_id']}"
        if data.get("username") and data["username"] != "Не указан": user_info += f" (@{data['username']})"
        icon = "✅" if notified else "⚠️"
        if config_file_id:
            result = (f"{icon} Подписка {action}!\\n\\n📦 #{data['order_id']}\\n{user_info}\\n"
                      f"📅 {data['subscription_type']}\\n📎 {config_file_name}\\n\\n"
                      + ("✅ Файл отправлен." if notified else "⚠️ Пользователь недоступен."))
        else:
            result = (f"{icon} Подписка {action}!\\n\\n📦 #{data['order_id']}\\n{user_info}\\n"
                      f"📅 {data['subscription_type']}\\n🔗 {link}\\n\\n"
                      + ("✅ Отправлено." if notified else "⚠️ Пользователь недоступен."))
        await message.answer(result)
    except Exception: await message.answer("❌ Произошла ошибка при обработке. Попробуйте ещё раз.")
    await state.clear()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True); return
    await state.clear()
    try: await callback.message.edit_text("❌ Операция отменена.", reply_markup=get_main_menu(callback.from_user.id))
    except: await callback.message.answer("❌ Операция отменена.", reply_markup=get_main_menu(callback.from_user.id))


@router.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != settings.ADMIN_ID: return
    if await state.get_state() is None: return
    await state.clear()
    await message.answer("❌ Операция отменена.", reply_markup=get_main_menu(message.from_user.id))


@router.callback_query(F.data == "export_orders")
async def export_orders(callback: types.CallbackQuery, bot: Bot):
    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True); return
    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute("SELECT * FROM orders ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        if not rows: await callback.answer("📭 Нет заказов для экспорта", show_alert=True); return
        os.makedirs("exports", exist_ok=True)
        fp = f"exports/orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Orders"
        try:
            async with conn.execute("PRAGMA table_info(orders)") as cur2:
                ws.append([c[1] for c in await cur2.fetchall()])
        except: ws.append(["ID","User ID","Username","Type","Amount","Status","Link","Created"])
        for r in rows: ws.append(list(r))
        wb.save(fp)
    try:
        await bot.send_document(callback.from_user.id, FSInputFile(fp))
        await callback.answer("✅ Файл отправлен", show_alert=True)
    except: await callback.answer("❌ Не удалось отправить файл", show_alert=True)


@router.callback_query(F.data == "reload_texts")
async def reload_texts_button(callback: types.CallbackQuery):
    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True); return
    reload_texts(); await callback.answer("♻️ Тексты обновлены!", show_alert=True)
    try: await callback.message.edit_text("✅ Тексты about.txt и welcome.txt перезагружены.", reply_markup=get_main_menu(callback.from_user.id))
    except: await callback.message.answer("✅ Тексты перезагружены.", reply_markup=get_main_menu(callback.from_user.id))


@router.message(Command("reload_texts"))
async def reload_texts_cmd(message: types.Message):
    if message.from_user.id != settings.ADMIN_ID: return
    reload_texts()
    await message.answer("♻️ Тексты перезагружены.", reply_markup=get_main_menu(message.from_user.id))


@router.message(Command("backup"))
async def manual_backup(message: types.Message):
    if message.from_user.id != settings.ADMIN_ID: return
    from bot.services.scheduler import backup_database
    await backup_database()
    await message.answer("✅ Бэкап создан вручную.")
""")

print("\n✅ Все файлы созданы!")
count = sum(1 for _ in __import__('pathlib').Path('.').rglob('*.py'))
print(f"Python-файлов в проекте: {count}")
print("\nДальнейшие шаги:")
print("  1. cp .env.example .env  # заполните значения")
print("  2. pip install -r requirements.txt")
print("  3. python -m bot.main    # тест нового запуска")
print("  4. Убедитесь, что всё работает, затем:")
print("     git add . && git commit -m 'refactor: restructure bot into modules'")
print("  5. Удалите старый bot.py после проверки")
