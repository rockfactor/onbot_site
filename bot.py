import asyncio
import logging
import os
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, FSInputFile, TelegramObject
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import openpyxl
from dotenv import load_dotenv
from typing import Callable, Any, Awaitable

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("purchases.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ownnetbot")

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "own_netbot")
SBER_URL = os.getenv("SBER_URL")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rockfactor")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID не найден в .env")
if not SUPPORT_USERNAME:
    raise ValueError("SUPPORT_USERNAME не найден в .env")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== ГЛОБАЛЫ ДЛЯ ТЕКСТОВ ==========
WELCOME_TEXT_TEMPLATE = None
ABOUT_TEXT_CACHE = None

# ========== ТАБЛИЦА ЦЕН AMNEZIA WG ==========
AMNEZIA_PRICES = {
    1: {  # 1 устройство
        1: 187,
        2: 340,
        3: 505,
        6: 898,
        12: 1571
    },
    3: {  # 3 устройства
        1: 449,
        2: 842,
        3: 1178,
        6: 2020,
        12: 3366
    },
    5: {  # 5 устройств
        1: 655,
        2: 1216,
        3: 1683,
        6: 2805,
        12: 4488
    }
}

# ========== СОСТОЯНИЯ ==========
class AdminState(StatesGroup):
    waiting_for_subscription_link = State()
    waiting_for_amnezia_config = State()


# ========== MIDDLEWARE ДЛЯ АВТООТВЕТА НА CALLBACK ==========
class AutoAnswerCallbackMiddleware(BaseMiddleware):
    """Автоматически отвечает на callback-запросы, если хендлер не сделал это сам.
    Хендлеры с show_alert=True должны вызывать callback.answer(...) вручную."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        result = await handler(event, data)
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass
        return result


# ========== ИНИЦИАЛИЗАЦИЯ БД ==========
async def init_db():
    async with aiosqlite.connect("orders2.db") as conn:
        await conn.execute(
            '''CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                subscription_type TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                subscription_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''
        )
        await conn.execute(
            '''CREATE TABLE IF NOT EXISTS user_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                subscription_link TEXT,
                subscription_type TEXT,
                is_active BOOLEAN DEFAULT 1,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''
        )
        await conn.execute(
            '''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_start BOOLEAN DEFAULT 1
            )'''
        )
        await conn.execute(
            '''CREATE TABLE IF NOT EXISTS used_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                test_type TEXT,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, test_type)
            )'''
        )

        # МИГРАЦИЯ: добавляем новые колонки если их нет
        try:
            async with conn.execute("PRAGMA table_info(orders)") as cur:
                columns = [row[1] for row in await cur.fetchall()]
            for col in ('first_name', 'last_name', 'config_file_id'):
                if col not in columns:
                    await conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TEXT")

            async with conn.execute("PRAGMA table_info(user_subscriptions)") as cur:
                columns = [row[1] for row in await cur.fetchall()]
            for col in ('username', 'first_name', 'last_name', 'config_file_id'):
                if col not in columns:
                    await conn.execute(f"ALTER TABLE user_subscriptions ADD COLUMN {col} TEXT")
            if 'notified_expiry' not in columns:
                await conn.execute(
                    "ALTER TABLE user_subscriptions ADD COLUMN notified_expiry BOOLEAN DEFAULT 0"
                )

            async with conn.execute("PRAGMA table_info(users)") as cur:
                columns = [row[1] for row in await cur.fetchall()]
            for col in ('username', 'first_name', 'last_name'):
                if col not in columns:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")

            async with conn.execute("PRAGMA table_info(used_tests)") as cur:
                columns = [row[1] for row in await cur.fetchall()]
            if 'username' not in columns:
                await conn.execute("ALTER TABLE used_tests ADD COLUMN username TEXT")

        except Exception as e:
            logger.warning(f"Ошибка при миграции БД: {e}")

        await conn.commit()


# ========== ЧТЕНИЕ ТЕКСТОВ ==========
def load_about_text():
    try:
        with open("about.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "ℹ️ Файл about.txt не найден. Добавьте его в каталог с bot.py."
    except Exception:
        logger.exception("Ошибка при чтении about.txt")
        return "❌ Ошибка чтения файла about.txt"


def load_welcome_text(user_name: str) -> str:
    global WELCOME_TEXT_TEMPLATE
    try:
        if not WELCOME_TEXT_TEMPLATE:
            try:
                with open("welcome.txt", "r", encoding="utf-8") as f:
                    WELCOME_TEXT_TEMPLATE = f.read().strip()
            except FileNotFoundError:
                WELCOME_TEXT_TEMPLATE = None
        if WELCOME_TEXT_TEMPLATE:
            return WELCOME_TEXT_TEMPLATE.replace("{имя пользователя}", user_name)
        else:
            return f"🙋Привет, {user_name}!\n⚠️ Файл welcome.txt не найден."
    except Exception:
        logger.exception("Ошибка при чтении welcome.txt")
        return "❌ Ошибка чтения файла welcome.txt"


# Инициализация кэша about
ABOUT_TEXT_CACHE = load_about_text()

# ========== УТИЛИТЫ ==========
async def check_channel_subscription(user_id):
    try:
        chat = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        return chat.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.warning(f"Ошибка проверки подписки пользователя {user_id}: {e}")
        return False


def get_user_info(user: types.User) -> tuple:
    """Возвращает информацию о пользователе: user_id, username, first_name, last_name"""
    return (
        user.id,
        user.username or "Не указан",
        user.first_name or "Не указано",
        user.last_name or "Не указано"
    )


def get_days_for_subscription(sub_type: str) -> int:
    """Возвращает количество дней подписки по её типу."""
    if "Тест" in sub_type:
        if "Amnezia WG" in sub_type:
            return 1
        return 3
    if "12 месяцев" in sub_type:
        return 365
    if "6 месяцев" in sub_type:
        return 180
    if "3 месяца" in sub_type:
        return 90
    if "2 месяца" in sub_type:
        return 60
    if "1 месяц" in sub_type:
        return 30
    return 30


async def has_used_test(user_id: int, test_type: str) -> bool:
    """Проверяет, использовал ли пользователь уже тестовый период"""
    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute(
            "SELECT 1 FROM used_tests WHERE user_id = ? AND test_type = ?",
            (user_id, test_type)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_test_used(user_id: int, username: str, test_type: str):
    """Помечает тестовый период как использованный"""
    async with aiosqlite.connect("orders2.db") as conn:
        try:
            await conn.execute(
                "INSERT INTO used_tests (user_id, username, test_type) VALUES (?, ?, ?)",
                (user_id, username, test_type)
            )
            await conn.commit()
        except aiosqlite.IntegrityError:
            pass  # уже существует — игнорируем


def is_amnezia_subscription(sub_type: str) -> bool:
    """Проверяет, является ли подписка типом Amnezia WG"""
    return "Amnezia WG" in sub_type


# ========== КЛАВИАТУРЫ ==========
def get_main_menu(user_id):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy_subscription"))
    b.add(InlineKeyboardButton(text="📖 Мои подписки", callback_data="my_subscriptions"))
    b.add(InlineKeyboardButton(text="📘 Инструкции", callback_data="instructions"))
    b.add(InlineKeyboardButton(text="ℹ️ О нас", callback_data="about"))
    b.add(InlineKeyboardButton(text="🛠 Тех. поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))

    if user_id == ADMIN_ID:
        b.add(InlineKeyboardButton(text="📊 Экспорт заказов", callback_data="export_orders"))
        b.add(InlineKeyboardButton(text="♻️ Обновить тексты", callback_data="reload_texts"))
        b.adjust(2, 2, 1, 2)
    else:
        b.adjust(2, 2, 1)
    return b.as_markup()


def get_subscription_type_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Vless для работы (5 устройств)", callback_data="sub_type_work"))
    b.add(InlineKeyboardButton(text="Amnezia WG", callback_data="sub_type_bypass"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    b.adjust(1)
    return b.as_markup()


def get_subscription_work_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Тест на 3 дня - бесплатно", callback_data="sub_work_test"))
    b.add(InlineKeyboardButton(text="1 месяц - 550 руб.", callback_data="sub_work_1month"))
    b.add(InlineKeyboardButton(text="3 месяца - 1320 руб.", callback_data="sub_work_3month"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription_type"))
    b.adjust(1)
    return b.as_markup()


def get_amnezia_devices_menu():
    """Меню выбора количества устройств для Amnezia WG"""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🧪 Тест на 1 день - бесплатно", callback_data="sub_bypass_test"))
    b.add(InlineKeyboardButton(text="1 устройство", callback_data="sub_bypass_devices_1"))
    b.add(InlineKeyboardButton(text="3 устройства", callback_data="sub_bypass_devices_3"))
    b.add(InlineKeyboardButton(text="5 устройств", callback_data="sub_bypass_devices_5"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription_type"))
    b.adjust(1)
    return b.as_markup()


def get_amnezia_plans_menu(devices: int):
    """Меню выбора тарифа для конкретного количества устройств"""
    b = InlineKeyboardBuilder()
    prices = AMNEZIA_PRICES[devices]

    months_labels = {1: "1 месяц", 2: "2 месяца", 3: "3 месяца", 6: "6 месяцев", 12: "12 месяцев"}
    for months, price in sorted(prices.items()):
        months_text = months_labels.get(months, f"{months} месяцев")
        b.add(InlineKeyboardButton(
            text=f"{months_text} - {price} руб.",
            callback_data=f"sub_bypass_plan_{devices}_{months}"
        ))

    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_amnezia_devices"))
    b.adjust(1)
    return b.as_markup()


# ========== НОВЫЕ КЛАВИАТУРЫ ДЛЯ ИНСТРУКЦИЙ ==========
def get_instructions_main_menu():
    """Главное меню инструкций: выбор между Vless и AmneziaWG"""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Vless для работы (5 устройств)", callback_data="instr_vless"))
    b.add(InlineKeyboardButton(text="AmneziaWG", callback_data="instr_awg"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    b.adjust(1)
    return b.as_markup()


def get_vless_instructions_menu():
    """Подменю инструкций для Vless (Happ Proxy)"""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="📱 Android", callback_data="instr_vless_android"))
    b.add(InlineKeyboardButton(text="🍏 iOS", callback_data="instr_vless_ios"))
    b.add(InlineKeyboardButton(text="💻 Windows", callback_data="instr_vless_windows"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_instructions_main"))
    b.adjust(1)
    return b.as_markup()


def get_awg_instructions_menu():
    """Подменю инструкций для AmneziaWG"""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="📱 Android", callback_data="instr_awg_android"))
    b.add(InlineKeyboardButton(text="🍏 iOS", callback_data="instr_awg_ios"))
    b.add(InlineKeyboardButton(text="💻 Windows", callback_data="instr_awg_windows"))
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_instructions_main"))
    b.adjust(1)
    return b.as_markup()


def get_back_instructions_menu():
    """Кнопка назад к списку инструкций"""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="◀️ Назад к инструкциям", callback_data="back_to_instructions_main"))
    return b.as_markup()


def get_back_menu():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return b.as_markup()


def get_admin_approve_keyboard(order_id):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Выдать/Продлить", callback_data=f"approve_{order_id}"))
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


def get_admin_renew_keyboard(order_id):
    """Клавиатура для продления — без запроса файла/ссылки"""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🔁 Продлить", callback_data=f"renew_{order_id}"))
    b.add(InlineKeyboardButton(text="✅ Выдать заново", callback_data=f"approve_{order_id}"))
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    b.adjust(1)
    return b.as_markup()


def get_admin_cancel_keyboard():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))
    return b.as_markup()


# ========== УВЕДОМЛЕНИЕ АДМИНА ==========
async def _get_existing_subscription(user_id: int, sub_type: str):
    """
    Возвращает запись из user_subscriptions, если:
    - Amnezia WG: подписка активна (is_active=1)
    - Vless: подписка активна ИЛИ истекла не более 3 дней назад
    Возвращает (sub_id, expires_at_str) или None.
    """
    async with aiosqlite.connect("orders2.db") as conn:
        if is_amnezia_subscription(sub_type):
            async with conn.execute(
                """
                SELECT id, expires_at FROM user_subscriptions
                WHERE user_id=? AND subscription_type=? AND is_active=1
                ORDER BY expires_at DESC LIMIT 1
                """,
                (user_id, sub_type)
            ) as cur:
                return await cur.fetchone()
        else:
            cutoff = (datetime.now() - timedelta(days=3)).isoformat()
            async with conn.execute(
                """
                SELECT id, expires_at FROM user_subscriptions
                WHERE user_id=? AND subscription_type=?
                  AND (is_active=1 OR (is_active=0 AND expires_at >= ?))
                ORDER BY expires_at DESC LIMIT 1
                """,
                (user_id, sub_type, cutoff)
            ) as cur:
                return await cur.fetchone()


async def notify_admin_about_order(order_id, user_id, username, first_name, last_name,
                                   sub_type, amount, is_test=False):
    emoji = "🧪" if is_test else "💰"
    user_info = f"👤 ID: {user_id}"
    if username and username != "Не указан":
        user_info += f" (@{username})"
    if first_name and first_name != "Не указано":
        user_info += f" | {first_name}"
    if last_name and last_name != "Не указано":
        user_info += f" {last_name}"

    existing = await _get_existing_subscription(user_id, sub_type)

    if existing:
        try:
            expires_str = datetime.fromisoformat(existing[1]).strftime('%d.%m.%Y')
        except (ValueError, TypeError):
            expires_str = existing[1]
        if is_amnezia_subscription(sub_type):
            instruction = f"\n🔁 У пользователя есть активная подписка (до {expires_str}). Нажмите 🔁 Продлить."
        else:
            instruction = f"\n🔁 Подписка истекла совсем недавно (до {expires_str}). Нажмите 🔁 Продлить."
        keyboard = get_admin_renew_keyboard(order_id)
    else:
        if is_amnezia_subscription(sub_type):
            instruction = "\n📎 Отправьте файл конфигурации (.conf)"
        else:
            instruction = "\n🔗 Отправьте ссылку подписки (https://...)"
        keyboard = get_admin_approve_keyboard(order_id)

    text = (
        f"{emoji} Новый заказ #{order_id}\n"
        f"{user_info}\n📦 {sub_type}\n💸 {amount} руб."
        f"{instruction}"
    )
    try:
        await bot.send_message(ADMIN_ID, text, reply_markup=keyboard)
    except Exception as e:
        logger.exception(f"Не удалось уведомить админа о заказе {order_id}: {e}")


# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id, username, first_name, last_name = get_user_info(message.from_user)
    user_name = message.from_user.first_name or "пользователь"

    if not await check_channel_subscription(user_id):
        await message.answer(
            "📢 Подпишитесь на канал, чтобы пользоваться ботом:",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="📢 Подписаться",
                        url=f"https://t.me/{CHANNEL_USERNAME}"
                    )],
                    [InlineKeyboardButton(
                        text="✅ Я подписался",
                        callback_data="check_subscription"
                    )]
                ]
            )
        )
        return

    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute(
            "SELECT first_start FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            try:
                await conn.execute(
                    "INSERT INTO users (user_id, username, first_name, last_name, first_start)"
                    " VALUES (?, ?, ?, ?, 1)",
                    (user_id, username, first_name, last_name)
                )
            except aiosqlite.OperationalError:
                await conn.execute(
                    "INSERT INTO users (user_id, first_start) VALUES (?, 1)",
                    (user_id,)
                )
            await conn.commit()
            first_start = True
        else:
            first_start = bool(row[0])

    if first_start:
        welcome_text = load_welcome_text(user_name)
        try:
            await message.answer(
                welcome_text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception:
            await message.answer(welcome_text)

        async with aiosqlite.connect("orders2.db") as conn:
            await conn.execute(
                "UPDATE users SET first_start=0 WHERE user_id=?", (user_id,)
            )
            await conn.commit()

    await message.answer(
        "👋 Добро пожаловать!\nВыберите действие:",
        reply_markup=get_main_menu(user_id)
    )


@dp.callback_query(F.data.in_({"main_menu", "back_to_main"}))
async def back_to_main(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "🏠 Главное меню:",
            reply_markup=get_main_menu(callback.from_user.id)
        )
    except Exception:
        await callback.message.answer(
            "🏠 Главное меню:",
            reply_markup=get_main_menu(callback.from_user.id)
        )


# ---------- Покупка ----------
@dp.callback_query(F.data == "buy_subscription")
async def show_subscription_types(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "Выберите тип подписки 👇",
            reply_markup=get_subscription_type_menu()
        )
    except Exception:
        await callback.message.answer(
            "Выберите тип подписки 👇",
            reply_markup=get_subscription_type_menu()
        )


@dp.callback_query(F.data == "back_to_subscription_type")
async def back_to_subscription_type(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "Выберите тип подписки 👇",
            reply_markup=get_subscription_type_menu()
        )
    except Exception:
        await callback.message.answer(
            "Выберите тип подписки 👇",
            reply_markup=get_subscription_type_menu()
        )


@dp.callback_query(F.data == "sub_type_work")
async def show_work_subscriptions(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "Vless для работы (5 устройств) - выберите вариант 👇",
            reply_markup=get_subscription_work_menu()
        )
    except Exception:
        await callback.message.answer(
            "Vless для работы (5 устройств) - выберите вариант 👇",
            reply_markup=get_subscription_work_menu()
        )


@dp.callback_query(F.data == "sub_type_bypass")
async def show_bypass_subscriptions(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "Amnezia WG - выберите количество устройств 👇",
            reply_markup=get_amnezia_devices_menu()
        )
    except Exception:
        await callback.message.answer(
            "Amnezia WG - выберите количество устройств 👇",
            reply_markup=get_amnezia_devices_menu()
        )


@dp.callback_query(F.data == "back_to_amnezia_devices")
async def back_to_amnezia_devices(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "Amnezia WG - выберите количество устройств 👇",
            reply_markup=get_amnezia_devices_menu()
        )
    except Exception:
        await callback.message.answer(
            "Amnezia WG - выберите количество устройств 👇",
            reply_markup=get_amnezia_devices_menu()
        )


@dp.callback_query(F.data.in_({"sub_bypass_devices_1", "sub_bypass_devices_3", "sub_bypass_devices_5"}))
async def show_amnezia_plans(callback: types.CallbackQuery):
    """Показывает меню тарифов для выбранного количества устройств"""
    devices = int(callback.data.split("_")[-1])
    device_text = {1: "1 устройства", 3: "3 устройств", 5: "5 устройств"}[devices]

    try:
        await callback.message.edit_text(
            f"Amnezia WG ({device_text}) - выберите тариф 👇",
            reply_markup=get_amnezia_plans_menu(devices)
        )
    except Exception:
        await callback.message.answer(
            f"Amnezia WG ({device_text}) - выберите тариф 👇",
            reply_markup=get_amnezia_plans_menu(devices)
        )


@dp.callback_query(
    F.data.in_(
        {"sub_work_test", "sub_work_1month", "sub_work_3month", "sub_bypass_test"}
    ) | F.data.startswith("sub_bypass_plan_")
)
async def handle_subscription_choice(callback: types.CallbackQuery):
    user_id, username, first_name, last_name = get_user_info(callback.from_user)
    data = callback.data

    # Проверка для тестовых подписок
    if data in ["sub_work_test", "sub_bypass_test"]:
        test_type = "work" if data == "sub_work_test" else "bypass"

        if await has_used_test(user_id, test_type):
            text = (
                "❌ Вы уже использовали тестовый период для этого типа подписки.\n\n"
                "💡 Вы можете выбрать платный тариф для продолжения использования."
            )
            try:
                await callback.message.edit_text(text, reply_markup=get_back_menu())
            except Exception:
                await callback.message.answer(text, reply_markup=get_back_menu())
            return

    months_labels = {1: "1 месяц", 2: "2 месяца", 3: "3 месяца", 6: "6 месяцев", 12: "12 месяцев"}

    # Определяем параметры подписки
    if data == "sub_work_test":
        sub_type = "Vless для работы (5 устройств) - Тест 3 дня"
        amount = 0
        is_test = True
        limit_msg = "Подписка действует для 5 устройств без лимита трафика."
    elif data == "sub_work_1month":
        sub_type = "Vless для работы (5 устройств) - 1 месяц"
        amount = 320
        is_test = False
        limit_msg = "Подписка действует для 5 устройств без лимита трафика."
    elif data == "sub_work_3month":
        sub_type = "Vless для работы (5 устройств) - 3 месяца"
        amount = 770
        is_test = False
        limit_msg = "Подписка действует для 5 устройств без лимита трафика."
    elif data == "sub_bypass_test":
        sub_type = "Amnezia WG - Тест 1 день"
        amount = 0
        is_test = True
        limit_msg = "Подписка действует без лимита трафика."
    elif data.startswith("sub_bypass_plan_"):
        parts = data.split("_")
        devices = int(parts[3])
        months = int(parts[4])
        amount = AMNEZIA_PRICES[devices][months]
        months_text = months_labels.get(months, f"{months} месяцев")
        sub_type = f"Amnezia WG ({devices} устройство{'в' if devices != 1 else ''}) - {months_text}"
        is_test = False
        limit_msg = "Подписка действует без лимита трафика."
    else:
        # Старые обработчики для совместимости
        if data == "sub_bypass_15days":
            sub_type = "Amnezia WG (1 устройство) - 15 дней"
            amount = 90
            is_test = False
            limit_msg = "Подписка действует для 1 устройства без лимита трафика."
        elif data == "sub_bypass_1month":
            sub_type = "Amnezia WG (1 устройство) - 1 месяц"
            amount = 140
            is_test = False
            limit_msg = "Подписка действует для 1 устройства без лимита трафика."
        elif data == "sub_bypass_3month":
            sub_type = "Amnezia WG (1 устройство) - 3 месяца"
            amount = 380
            is_test = False
            limit_msg = "Подписка действует для 1 устройства без лимита трафика."
        else:
            await callback.answer("❌ Неизвестный тариф", show_alert=True)
            return

    async with aiosqlite.connect("orders2.db") as conn:
        try:
            await conn.execute(
                "INSERT INTO orders (user_id, username, first_name, last_name, "
                "subscription_type, amount) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, first_name, last_name, sub_type, amount)
            )
        except aiosqlite.OperationalError:
            await conn.execute(
                "INSERT INTO orders (user_id, username, subscription_type, amount)"
                " VALUES (?, ?, ?, ?)",
                (user_id, username, sub_type, amount)
            )
        await conn.commit()
        async with conn.execute("SELECT last_insert_rowid()") as cur:
            row = await cur.fetchone()
        order_id = row[0]

    if is_test:
        text = (
            f"🧪 Вы выбрали *{sub_type}*. Ожидайте подтверждения администратора.\n\n"
            f"{limit_msg}"
        )
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_menu())
        except Exception:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=get_back_menu())
    else:
        pay_url = SBER_URL or ""
        if pay_url:
            pay_keyboard = InlineKeyboardBuilder()
            pay_keyboard.add(
                InlineKeyboardButton(
                    text="💳 Перевод СБП на номер +79061803036",
                    url=pay_url
                )
            )
            pay_keyboard.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))
            pay_keyboard.adjust(1)
            reply_markup = pay_keyboard.as_markup()
            text = (
                f"✅ Вы выбрали *{sub_type}*\n"
                f"💸 {amount} руб.\n\n"
                f"Нажмите на кнопку ниже, чтобы произвести оплату.\n"
                f"После оплаты ждите подтверждения администратора.\n\n"
                f"{limit_msg}"
            )
        else:
            reply_markup = get_back_menu()
            text = (
                f"✅ Вы выбрали *{sub_type}*\n"
                f"💸 {amount} руб.\n\n"
                f"❌ Ссылка на оплату не настроена. Пожалуйста, свяжитесь с администратором.\n\n"
                f"{limit_msg}"
            )

        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=reply_markup)

    logger.info(f"Создан заказ #{order_id} от user_id={user_id} (@{username}) ({sub_type})")
    await notify_admin_about_order(
        order_id, user_id, username, first_name, last_name, sub_type, amount, is_test
    )


# ---------- Мои подписки ----------
@dp.callback_query(F.data == "my_subscriptions")
async def show_my_subscriptions(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute(
            """
            SELECT subscription_type, subscription_link, expires_at, is_active
            FROM user_subscriptions
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,)
        ) as cur:
            subscriptions = await cur.fetchall()

    if not subscriptions:
        text = (
            "📭 У вас пока нет активных подписок.\n\n"
            "🛒 Вы можете приобрести подписку в главном меню."
        )
        try:
            await callback.message.edit_text(text, reply_markup=get_back_menu())
        except Exception:
            await callback.message.answer(text, reply_markup=get_back_menu())
        return

    text = "📖 Ваши подписки:\n\n"
    active_count = 0

    for sub_type, link, expires_at, is_active in subscriptions:
        status = "✅ Активна" if is_active else "❌ Неактивна"
        if expires_at:
            try:
                exp_date = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
                expires_text = f"до {exp_date}"
            except (ValueError, TypeError):
                expires_text = expires_at
        else:
            expires_text = "срок не указан"

        text += f"📦 {sub_type}\n"
        text += f"🔗 {link}\n"
        text += f"📅 {expires_text}\n"
        text += f"🟢 {status}\n\n"

        if is_active:
            active_count += 1

    if active_count == 0:
        text += "❌ У вас нет активных подписок. Продлите или приобретите новую."

    try:
        await callback.message.edit_text(text, reply_markup=get_back_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_menu())


# ---------- Инструкции (НОВАЯ СТРУКТУРА) ----------
@dp.callback_query(F.data == "instructions")
async def show_instructions_main(callback: types.CallbackQuery):
    text = "📘 Выберите тип инструкций:"
    try:
        await callback.message.edit_text(text, reply_markup=get_instructions_main_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=get_instructions_main_menu())


@dp.callback_query(F.data == "back_to_instructions_main")
async def back_to_instructions_main(callback: types.CallbackQuery):
    text = "📘 Выберите тип инструкций:"
    try:
        await callback.message.edit_text(text, reply_markup=get_instructions_main_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=get_instructions_main_menu())


# --- Vless инструкции (Happ Proxy) ---
@dp.callback_query(F.data == "instr_vless")
async def show_vless_instructions(callback: types.CallbackQuery):
    text = "Vless для работы (5 устройств) - выберите платформу:"
    try:
        await callback.message.edit_text(text, reply_markup=get_vless_instructions_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=get_vless_instructions_menu())


@dp.callback_query(F.data == "instr_vless_android")
async def instr_vless_android(callback: types.CallbackQuery):
    try:
        photo_path = os.path.join(BASE_DIR, "images", "android_steps.jpg")
        photo = FSInputFile(photo_path)
        await bot.send_photo(
            callback.from_user.id,
            photo=photo,
            caption=(
                "После установки приложения:\n"
                "1️⃣ Скопируйте ссылку на подписку.\n"
                "2️⃣ Нажмите «+» → «Вставить из буфера обмена».\n"
                "3️⃣ Выберите страну и включите VPN кнопкой (вкл/выкл)."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить изображение android_steps.jpg: {e}")
        await callback.message.answer("❌ Не удалось загрузить инструкцию.")

    text = "📱 Приложение для Android:\nhttps://play.google.com/store/apps/details?id=com.happproxy"
    await callback.message.answer(text, reply_markup=get_vless_instructions_menu())


@dp.callback_query(F.data == "instr_vless_ios")
async def instr_vless_ios(callback: types.CallbackQuery):
    try:
        photo_path = os.path.join(BASE_DIR, "images", "ios_steps.jpg")
        photo = FSInputFile(photo_path)
        await bot.send_photo(
            callback.from_user.id,
            photo=photo,
            caption=(
                "После установки приложения:\n"
                "1️⃣ Скопируйте ссылку на подписку.\n"
                "2️⃣ Нажмите «+» → «Вставить из буфера обмена».\n"
                "3️⃣ Выберите страну и нажмите кнопку подключения."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить изображение ios_steps.jpg: {e}")
        await callback.message.answer("❌ Не удалось загрузить инструкцию.")

    text = (
        "🍏 Приложение для iOS:\n"
        "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973"
    )
    await callback.message.answer(text, reply_markup=get_vless_instructions_menu())


@dp.callback_query(F.data == "instr_vless_windows")
async def instr_vless_windows(callback: types.CallbackQuery):
    try:
        photo_path = os.path.join(BASE_DIR, "images", "windows_steps.jpg")
        photo = FSInputFile(photo_path)
        await bot.send_photo(
            callback.from_user.id,
            photo=photo,
            caption=(
                "После установки:\n"
                "1️⃣ Скопируйте ссылку на подписку.\n"
                "2️⃣ В правом верхнем углу нажмите «+» → «Вставить из буфера обмена».\n"
                "3️⃣ Выберите страну и включите соединение кнопкой вкл/выкл."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить изображение windows_steps.jpg: {e}")
        await callback.message.answer("❌ Не удалось загрузить инструкцию.")

    text = (
        "💻 Приложение для Windows:\n"
        "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x86.exe"
    )
    await callback.message.answer(text, reply_markup=get_vless_instructions_menu())


# --- AmneziaWG инструкции ---
@dp.callback_query(F.data == "instr_awg")
async def show_awg_instructions(callback: types.CallbackQuery):
    text = "AmneziaWG - выберите платформу:"
    try:
        await callback.message.edit_text(text, reply_markup=get_awg_instructions_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=get_awg_instructions_menu())


@dp.callback_query(F.data == "instr_awg_android")
async def instr_awg_android(callback: types.CallbackQuery):
    try:
        photo_path = os.path.join(BASE_DIR, "images", "awg_android.jpg")
        photo = FSInputFile(photo_path)
        await bot.send_photo(
            callback.from_user.id,
            photo=photo,
            caption=(
                "📱 AmneziaWG для Android\n\n"
                "После установки:\n"
                "1️⃣ В углу нажмите «+» \n"
                "2️⃣ «Импорт из файла или архива», при необходимости напишите любое имя нового соединения.\n"
                "3️⃣ Включите соединение кнопкой вкл/выкл."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить изображение awg_android.jpg: {e}")
        await callback.message.answer("❌ Не удалось загрузить инструкцию.")

    text = "🔗 Скачать AmneziaWG для Android:\nhttps://play.google.com/store/apps/details?id=org.amnezia.awg"
    await callback.message.answer(text, reply_markup=get_awg_instructions_menu())


@dp.callback_query(F.data == "instr_awg_ios")
async def instr_awg_ios(callback: types.CallbackQuery):
    try:
        photo_path = os.path.join(BASE_DIR, "images", "awg_ios.jpg")
        photo = FSInputFile(photo_path)
        await bot.send_photo(
            callback.from_user.id,
            photo=photo,
            caption=(
                "🍏 AmneziaWG для iOS\n\n"
                "После установки:\n"
                "1️⃣ В углу нажмите «+» \n"
                "2️⃣ «Импорт из файла или архива», при необходимости напишите любое имя нового соединения.\n"
                "3️⃣ Включите соединение кнопкой вкл/выкл."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить изображение awg_ios.jpg: {e}")
        await callback.message.answer("❌ Не удалось загрузить инструкцию.")

    text = "🔗 Скачать AmneziaWG для iOS:\nhttps://apps.apple.com/app/amneziawg/id6478942365"
    await callback.message.answer(text, reply_markup=get_awg_instructions_menu())


@dp.callback_query(F.data == "instr_awg_windows")
async def instr_awg_windows(callback: types.CallbackQuery):
    try:
        photo_path = os.path.join(BASE_DIR, "images", "awg_windows.jpg")
        photo = FSInputFile(photo_path)
        await bot.send_photo(
            callback.from_user.id,
            photo=photo,
            caption=(
                "💻 AmneziaWG для Windows\n\n"
                "После установки:\n"
                "1️⃣ В углу нажмите «+» \n"
                "2️⃣ «Импорт из файла или архива», при необходимости напишите любое имя нового соединения.\n"
                "3️⃣ Включите соединение кнопкой вкл/выкл."
            )
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить изображение awg_windows.jpg: {e}")
        await callback.message.answer("❌ Не удалось загрузить инструкцию.")

    text = (
        "🔗 Скачать AmneziaWG для Windows:\n"
        "https://github.com/amnezia-vpn/amneziawg-windows-client/releases"
    )
    await callback.message.answer(text, reply_markup=get_awg_instructions_menu())


# ---------- Проверка подписки (callback) ----------
@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery):
    if await check_channel_subscription(callback.from_user.id):
        try:
            await callback.message.edit_text(
                "👋 Добро пожаловать!\nВыберите действие:",
                reply_markup=get_main_menu(callback.from_user.id)
            )
        except Exception:
            await callback.message.answer(
                "👋 Добро пожаловать!\nВыберите действие:",
                reply_markup=get_main_menu(callback.from_user.id)
            )
    else:
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)


# ---------- ОБРАБОТЧИК ДЛЯ "О НАС" ----------
@dp.callback_query(F.data == "about")
async def show_about(callback: types.CallbackQuery):
    global ABOUT_TEXT_CACHE
    text = ABOUT_TEXT_CACHE or load_about_text()
    try:
        await callback.message.edit_text(text, reply_markup=get_back_menu())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_menu())


# ========== АДМИН: подтверждение заказа (запрос ссылки/файла) ==========
@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return

    try:
        order_id = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer("❌ Неверный формат заказа", show_alert=True)
        return

    async with aiosqlite.connect("orders2.db") as conn:
        try:
            async with conn.execute(
                "SELECT user_id, username, first_name, last_name, "
                "subscription_type, status FROM orders WHERE id=?",
                (order_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await callback.answer("❌ Заказ не найден", show_alert=True)
                return
            user_id, username, first_name, last_name, sub_type, status = row
        except aiosqlite.OperationalError:
            async with conn.execute(
                "SELECT user_id, username, subscription_type, status FROM orders WHERE id=?",
                (order_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await callback.answer("❌ Заказ не найден", show_alert=True)
                return
            user_id, username, sub_type, status = row
            first_name, last_name = "Не указано", "Не указано"

    if status == 'approved':
        await callback.answer("✅ Этот заказ уже обработан", show_alert=True)
        return

    await state.update_data(
        order_id=order_id,
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        subscription_type=sub_type
    )

    if is_amnezia_subscription(sub_type):
        await state.set_state(AdminState.waiting_for_amnezia_config)
        instruction_text = "📎 Пожалуйста, отправьте файл конфигурации (.conf):"
    else:
        await state.set_state(AdminState.waiting_for_subscription_link)
        instruction_text = "📝 Пожалуйста, отправьте ссылку для активации:"

    user_info = f"👤 ID: {user_id}"
    if username and username != "Не указан":
        user_info += f" (@{username})"
    if first_name and first_name != "Не указано":
        user_info += f" | {first_name}"
    if last_name and last_name != "Не указано":
        user_info += f" {last_name}"

    try:
        await callback.message.edit_text(
            f"📝 Для заказа #{order_id}\n{user_info}\n📦 {sub_type}\n\n{instruction_text}",
            reply_markup=get_admin_cancel_keyboard()
        )
    except Exception:
        await callback.message.answer(
            f"📝 Для заказа #{order_id}\n{user_info}\n📦 {sub_type}\n\n{instruction_text}",
            reply_markup=get_admin_cancel_keyboard()
        )


# ========== ОБРАБОТЧИК: БЫСТРОЕ ПРОДЛЕНИЕ (без запроса файла/ссылки) ==========
@dp.callback_query(F.data.startswith("renew_"))
async def renew_order(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return

    try:
        order_id = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer("❌ Неверный формат заказа", show_alert=True)
        return

    async with aiosqlite.connect("orders2.db") as conn:
        try:
            async with conn.execute(
                "SELECT user_id, username, first_name, last_name, "
                "subscription_type, status FROM orders WHERE id=?",
                (order_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await callback.answer("❌ Заказ не найден", show_alert=True)
                return
            user_id, username, first_name, last_name, sub_type, status = row
        except aiosqlite.OperationalError:
            async with conn.execute(
                "SELECT user_id, username, subscription_type, status FROM orders WHERE id=?",
                (order_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await callback.answer("❌ Заказ не найден", show_alert=True)
                return
            user_id, username, sub_type, status = row
            first_name, last_name = "Не указано", "Не указано"

    if status == 'approved':
        await callback.answer("✅ Этот заказ уже обработан", show_alert=True)
        return

    days = get_days_for_subscription(sub_type)
    now = datetime.now()

    try:
        async with aiosqlite.connect("orders2.db") as conn:
            async with conn.execute(
                """
                SELECT id, expires_at FROM user_subscriptions
                WHERE user_id=? AND subscription_type=?
                ORDER BY expires_at DESC LIMIT 1
                """,
                (user_id, sub_type)
            ) as cur:
                existing = await cur.fetchone()

            if not existing:
                await callback.answer(
                    "⚠️ Подписка не найдена — используйте «Выдать заново»",
                    show_alert=True
                )
                return

            sub_id, old_expires_str = existing
            try:
                old_exp = datetime.fromisoformat(old_expires_str)
            except (ValueError, TypeError):
                old_exp = now
            new_exp = max(old_exp, now) + timedelta(days=days)

            await conn.execute(
                "UPDATE user_subscriptions SET expires_at=?, is_active=1, notified_expiry=0 WHERE id=?",
                (new_exp.isoformat(), sub_id)
            )
            await conn.execute(
                "UPDATE orders SET status='approved' WHERE id=?",
                (order_id,)
            )
            await conn.commit()

        text_user = (
            f"🔁 Подписка *{sub_type}* продлена на {days} дн. "
            f"до {new_exp.strftime('%d.%m.%Y')}."
        )
        user_notified = False
        try:
            await bot.send_message(user_id, text_user, parse_mode="Markdown")
            user_notified = True
        except Exception as e:
            logger.exception(f"Не удалось уведомить пользователя {user_id}: {e}")

        user_info = f"👤 ID: {user_id}"
        if username and username != "Не указан":
            user_info += f" (@{username})"
        if first_name and first_name != "Не указано":
            user_info += f" | {first_name}"

        status_icon = "✅" if user_notified else "⚠️"
        admin_text = (
            f"{status_icon} Подписка продлена!\n\n"
            f"📦 Заказ: #{order_id}\n"
            f"{user_info}\n"
            f"📅 Тип: {sub_type}\n"
            f"⏳ Продлено на: {days} дн.\n"
            f"📅 До: {new_exp.strftime('%d.%m.%Y')}\n\n"
            + ("✅ Сообщение отправлено пользователю." if user_notified
               else "⚠️ Пользователь недоступен, но БД обновлена.")
        )

        try:
            await callback.message.edit_text(admin_text)
        except Exception:
            await callback.message.answer(admin_text)

        logger.info(f"🔁 Заказ #{order_id} продлён админом для user_id={user_id} (@{username})")

    except Exception as e:
        logger.exception(f"❌ Ошибка при продлении подписки: {e}")
        await callback.answer("❌ Ошибка при продлении. Попробуйте ещё раз.", show_alert=True)


# ========== ОБРАБОТЧИК ССЫЛКИ/ФАЙЛА ОТ АДМИНА ==========
@dp.message(AdminState.waiting_for_subscription_link)
async def process_subscription_link(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только админ может выполнять эту операцию")
        return

    link = message.text.strip()
    if not (
        link.startswith('http://')
        or link.startswith('https://')
        or link.startswith('tcp://')
        or '://' in link
    ):
        await message.answer(
            "❌ Это не похоже на валидную ссылку. Пожалуйста, отправьте корректную ссылку:"
        )
        return

    data = await state.get_data()
    order_id = data.get('order_id')
    user_id = data.get('user_id')
    username = data.get('username')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    sub_type = data.get('subscription_type')

    if not all([order_id, user_id, username, sub_type]):
        await message.answer("❌ Ошибка состояния — данные заказа не найдены.")
        await state.clear()
        return

    await _process_subscription_activation(
        message, state, order_id, user_id, username, first_name, last_name,
        sub_type, link, None, None
    )


@dp.message(AdminState.waiting_for_amnezia_config)
async def process_amnezia_config(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только админ может выполнять эту операцию")
        return

    if not message.document:
        await message.answer("❌ Пожалуйста, отправьте файл конфигурации (.conf):")
        return

    data = await state.get_data()
    order_id = data.get('order_id')
    user_id = data.get('user_id')
    username = data.get('username')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    sub_type = data.get('subscription_type')

    if not all([order_id, user_id, username, sub_type]):
        await message.answer("❌ Ошибка состояния — данные заказа не найдены.")
        await state.clear()
        return

    config_file_id = message.document.file_id
    config_file_name = message.document.file_name or "config.conf"

    await _process_subscription_activation(
        message, state, order_id, user_id, username, first_name, last_name,
        sub_type, None, config_file_id, config_file_name
    )


async def _process_subscription_activation(
    message: types.Message,
    state: FSMContext,
    order_id,
    user_id,
    username,
    first_name,
    last_name,
    sub_type,
    link=None,
    config_file_id=None,
    config_file_name=None
):
    """Общая функция для обработки активации подписки (Vless ссылка или Amnezia файл)"""
    try:
        async with aiosqlite.connect("orders2.db") as conn:
            now = datetime.now()
            days = get_days_for_subscription(sub_type)

            if "Тест" in sub_type:
                test_type = "bypass" if is_amnezia_subscription(sub_type) else "work"
                await mark_test_used(user_id, username, test_type)

            expires = now + timedelta(days=days)

            async with conn.execute(
                """
                SELECT id, expires_at FROM user_subscriptions
                WHERE user_id=? AND subscription_type=? AND is_active=1
                """,
                (user_id, sub_type)
            ) as cur:
                active = await cur.fetchone()

            if active:
                try:
                    old_exp = datetime.fromisoformat(active[1])
                except (ValueError, TypeError):
                    old_exp = now
                new_exp = max(old_exp, now) + timedelta(days=days)

                if config_file_id:
                    await conn.execute(
                        "UPDATE user_subscriptions SET expires_at=?, config_file_id=?, notified_expiry=0 WHERE id=?",
                        (new_exp.isoformat(), config_file_id, active[0])
                    )
                else:
                    await conn.execute(
                        "UPDATE user_subscriptions SET expires_at=?, subscription_link=?, notified_expiry=0 WHERE id=?",
                        (new_exp.isoformat(), link, active[0])
                    )

                if config_file_id:
                    text_user = (
                        f"🔁 Подписка *{sub_type}* продлена до "
                        f"{new_exp.strftime('%d.%m.%Y')}.\n📎 Файл конфигурации:"
                    )
                else:
                    text_user = (
                        f"🔁 Подписка *{sub_type}* продлена до "
                        f"{new_exp.strftime('%d.%m.%Y')}.\n🔗 {link}"
                    )
                action_text = "продлена"
            else:
                try:
                    if config_file_id:
                        await conn.execute(
                            """
                            INSERT INTO user_subscriptions
                            (user_id, username, first_name, last_name, config_file_id,
                             subscription_type, expires_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, username, first_name, last_name,
                             config_file_id, sub_type, expires.isoformat())
                        )
                    else:
                        await conn.execute(
                            """
                            INSERT INTO user_subscriptions
                            (user_id, username, first_name, last_name, subscription_link,
                             subscription_type, expires_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, username, first_name, last_name,
                             link, sub_type, expires.isoformat())
                        )
                except aiosqlite.OperationalError:
                    if config_file_id:
                        await conn.execute(
                            """
                            INSERT INTO user_subscriptions
                            (user_id, config_file_id, subscription_type, expires_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (user_id, config_file_id, sub_type, expires.isoformat())
                        )
                    else:
                        await conn.execute(
                            """
                            INSERT INTO user_subscriptions
                            (user_id, subscription_link, subscription_type, expires_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (user_id, link, sub_type, expires.isoformat())
                        )

                if config_file_id:
                    text_user = (
                        f"🎉 Подписка *{sub_type}* активирована до "
                        f"{expires.strftime('%d.%m.%Y')}!\n📎 Файл конфигурации:"
                    )
                else:
                    text_user = (
                        f"🎉 Подписка *{sub_type}* активирована до "
                        f"{expires.strftime('%d.%m.%Y')}!\n🔗 {link}"
                    )
                action_text = "активирована"

            if config_file_id:
                await conn.execute(
                    "UPDATE orders SET status='approved', config_file_id=? WHERE id=?",
                    (config_file_id, order_id)
                )
            else:
                await conn.execute(
                    "UPDATE orders SET status='approved', subscription_link=? WHERE id=?",
                    (link, order_id)
                )
            await conn.commit()

        user_notified = False
        try:
            if config_file_id:
                await bot.send_document(
                    user_id,
                    config_file_id,
                    caption=text_user,
                    parse_mode="Markdown"
                )
            else:
                await bot.send_message(user_id, text_user, parse_mode="Markdown")
            user_notified = True
        except Exception as e:
            logger.exception(f"Не удалось отправить подписку пользователю {user_id}: {e}")

        user_info = f"👤 ID: {user_id}"
        if username and username != "Не указан":
            user_info += f" (@{username})"
        if first_name and first_name != "Не указано":
            user_info += f" | {first_name}"
        if last_name and last_name != "Не указано":
            user_info += f" {last_name}"

        if user_notified:
            if config_file_id:
                await message.answer(
                    f"✅ Подписка успешно {action_text}!\n\n"
                    f"📦 Заказ: #{order_id}\n{user_info}\n"
                    f"📅 Тип: {sub_type}\n📎 Файл: {config_file_name}\n\n"
                    f"✅ Файл отправлен пользователю."
                )
            else:
                await message.answer(
                    f"✅ Подписка успешно {action_text}!\n\n"
                    f"📦 Заказ: #{order_id}\n{user_info}\n"
                    f"📅 Тип: {sub_type}\n🔗 Ссылка: {link}\n\n"
                    f"✅ Сообщение отправлено пользователю."
                )
        else:
            if config_file_id:
                await message.answer(
                    f"⚠️ Подписка {action_text}, но пользователь может быть недоступен.\n\n"
                    f"📦 Заказ: #{order_id}\n{user_info}\n"
                    f"📅 Тип: {sub_type}\n📎 Файл: {config_file_name}"
                )
            else:
                await message.answer(
                    f"⚠️ Подписка {action_text}, но пользователь может быть недоступен.\n\n"
                    f"📦 Заказ: #{order_id}\n{user_info}\n"
                    f"📅 Тип: {sub_type}\n🔗 Ссылка: {link}"
                )

        logger.info(f"✅ Заказ #{order_id} обработан админом для user_id={user_id} (@{username})")

    except Exception as e:
        logger.exception(f"❌ Ошибка при обработке подписки: {e}")
        await message.answer("❌ Произошла ошибка при обработке подписки. Попробуйте ещё раз.")
        return

    await state.clear()


# ========== КНОПКА ОТМЕНЫ ==========
@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    await state.clear()
    try:
        await callback.message.edit_text(
            "❌ Операция отменена.",
            reply_markup=get_main_menu(callback.from_user.id)
        )
    except Exception:
        await callback.message.answer(
            "❌ Операция отменена.",
            reply_markup=get_main_menu(callback.from_user.id)
        )


@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer(
        "❌ Операция отменена.",
        reply_markup=get_main_menu(message.from_user.id)
    )


# ---------- Экспорт заказов ----------
@dp.callback_query(F.data == "export_orders")
async def export_orders(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return

    async with aiosqlite.connect("orders2.db") as conn:
        async with conn.execute("SELECT * FROM orders ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        if not rows:
            await callback.answer("📭 Нет заказов для экспорта", show_alert=True)
            return

        os.makedirs("exports", exist_ok=True)
        file_path = f"exports/orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Orders"

        try:
            async with conn.execute("PRAGMA table_info(orders)") as cur2:
                columns_info = await cur2.fetchall()
            column_names = [col[1] for col in columns_info]
            ws.append(column_names)
            for r in rows:
                ws.append(list(r))
        except Exception as e:
            logger.warning(f"Не удалось определить структуру orders: {e}")
            ws.append(["ID", "User ID", "Username", "Type", "Amount", "Status", "Link", "Created At"])
            for r in rows:
                ws.append(list(r))

        wb.save(file_path)

    try:
        await bot.send_document(callback.from_user.id, FSInputFile(file_path))
        await callback.answer("✅ Файл отправлен", show_alert=True)
        logger.info(f"Экспорт заказов: {file_path}")
    except Exception:
        await callback.answer("❌ Не удалось отправить файл", show_alert=True)


# ---------- Обновление текстов через кнопку ----------
@dp.callback_query(F.data == "reload_texts")
async def reload_texts_button(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ может использовать эту функцию.", show_alert=True)
        return

    global ABOUT_TEXT_CACHE, WELCOME_TEXT_TEMPLATE
    ABOUT_TEXT_CACHE = load_about_text()
    try:
        with open("welcome.txt", "r", encoding="utf-8") as f:
            WELCOME_TEXT_TEMPLATE = f.read().strip()
    except FileNotFoundError:
        WELCOME_TEXT_TEMPLATE = None
    except Exception:
        logger.exception("Ошибка при загрузке welcome.txt через кнопку")

    logger.info("♻️ Админ обновил тексты about.txt и welcome.txt")
    await callback.answer("♻️ Тексты успешно обновлены!", show_alert=True)
    try:
        await callback.message.edit_text(
            "✅ Файлы `about.txt` и `welcome.txt` перезагружены.\n🏠 Возврат в главное меню:",
            reply_markup=get_main_menu(callback.from_user.id)
        )
    except Exception:
        await callback.message.answer(
            "✅ Файлы `about.txt` и `welcome.txt` перезагружены.",
            reply_markup=get_main_menu(callback.from_user.id)
        )


# ---------- Команда перезагрузки текстов (админ) ----------
@dp.message(Command("reload_texts"))
async def reload_texts_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только админ может использовать эту команду.")
        return
    global ABOUT_TEXT_CACHE, WELCOME_TEXT_TEMPLATE
    ABOUT_TEXT_CACHE = load_about_text()
    try:
        with open("welcome.txt", "r", encoding="utf-8") as f:
            WELCOME_TEXT_TEMPLATE = f.read().strip()
    except FileNotFoundError:
        WELCOME_TEXT_TEMPLATE = None
    except Exception:
        logger.exception("Ошибка при загрузке welcome.txt через команду")
    logger.info("♻️ Админ перезагрузил тексты через /reload_texts")
    await message.answer(
        "♻️ Тексты about.txt и welcome.txt перезагружены.",
        reply_markup=get_main_menu(message.from_user.id)
    )


# ========== РЕЗЕРВНОЕ КОПИРОВАНИЕ ==========
async def backup_database():
    try:
        os.makedirs("backups", exist_ok=True)
        backup_name = f"backups/orders_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        async with aiosqlite.connect("orders2.db") as conn:
            await conn.execute(f"VACUUM INTO '{backup_name}'")
        logger.info(f"✅ Создан backup: {backup_name}")

        now = datetime.now()
        for file in os.listdir("backups"):
            path = os.path.join("backups", file)
            if os.path.isfile(path):
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                if (now - mtime).days > 7:
                    os.remove(path)
                    logger.info(f"🗑️ Удалён старый backup: {path}")
    except Exception as e:
        logger.exception(f"❌ Ошибка резервного копирования: {e}")


# ========== ПРОВЕРКА ИСТЕЧЕНИЯ ПОДПИСОК ==========
async def check_expired_subscriptions():
    try:
        async with aiosqlite.connect("orders2.db") as conn:
            async with conn.execute(
                "SELECT id, user_id, username, subscription_type, expires_at "
                "FROM user_subscriptions WHERE is_active = 1"
            ) as cur:
                active = await cur.fetchall()

            for sub_id, user_id, username, sub_type, exp_date in active:
                if not exp_date:
                    continue
                try:
                    if datetime.fromisoformat(exp_date) < datetime.now():
                        await conn.execute(
                            "UPDATE user_subscriptions SET is_active = 0 WHERE id = ?",
                            (sub_id,)
                        )
                        await conn.commit()
                        try:
                            await bot.send_message(
                                user_id,
                                f"⏰ Срок вашей подписки «{sub_type}» истёк.\n"
                                f"Продлите, чтобы продолжить пользоваться."
                            )
                        except Exception:
                            logger.warning(
                                f"Не удалось уведомить пользователя {user_id} "
                                f"(@{username}) об истечении подписки"
                            )
                except ValueError:
                    logger.warning(
                        f"Невозможно распарсить expires_at для подписки {sub_id}: {exp_date}"
                    )
    except Exception:
        logger.exception("Ошибка при проверке истекших подписок")


# ========== УВЕДОМЛЕНИЯ О СКОРОМ ОКОНЧАНИИ ==========
async def notify_upcoming_expiry():
    """Отправляет уведомления пользователям о подписках, истекающих через 3 дня."""
    try:
        async with aiosqlite.connect("orders2.db") as conn:
            async with conn.execute(
                """
                SELECT id, user_id, subscription_type, expires_at
                FROM user_subscriptions
                WHERE is_active = 1
                  AND notified_expiry = 0
                  AND expires_at IS NOT NULL
                  AND date(expires_at) <= date('now', '+3 days')
                  AND date(expires_at) > date('now')
                """
            ) as cur:
                subscriptions = await cur.fetchall()

            for sub_id, user_id, sub_type, expires_at in subscriptions:
                try:
                    exp_date = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
                    text = (
                        f"⏰ Внимание! Ваша подписка *{sub_type}* истекает *{exp_date}*.\n"
                        f"Продлите подписку, чтобы продолжить пользоваться сервисом."
                    )
                    await bot.send_message(user_id, text, parse_mode="Markdown")
                    await conn.execute(
                        "UPDATE user_subscriptions SET notified_expiry = 1 WHERE id = ?",
                        (sub_id,)
                    )
                    await conn.commit()
                    logger.info(
                        f"Отправлено уведомление об истечении подписки {sub_id} пользователю {user_id}"
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление для подписки {sub_id}: {e}")
    except Exception:
        logger.exception("Ошибка в notify_upcoming_expiry")


# ========== РУЧНОЙ БЭКАП КОМАНДОЙ ==========
@dp.message(Command("backup"))
async def manual_backup(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await backup_database()
    await message.answer("✅ Бэкап создан вручную.")


# ========== ЗАПУСК ==========
async def main():
    await init_db()

    # Middleware для автоответа на callback (регистрируем до start_polling)
    dp.callback_query.middleware(AutoAnswerCallbackMiddleware())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(backup_database, 'cron', hour=3, minute=0)
    scheduler.add_job(check_expired_subscriptions, 'interval', hours=1)
    scheduler.add_job(notify_upcoming_expiry, 'cron', hour=10, minute=0)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
