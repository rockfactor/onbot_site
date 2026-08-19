"""Выбор тарифа, создание заказа, «Мои подписки»."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router, types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.main import get_back_menu
from bot.keyboards.subscription import (
    get_amnezia_devices_menu, get_amnezia_plans_menu,
    get_subscription_type_menu, get_vless_menu,
)
from bot.prices import (
    AMNEZIA_PRICES, DEVICE_LABELS, Tariff, VLESS_PRICES,
    awg_plan, awg_test, test_kind, vless_plan, vless_test,
)
from bot.services.subscription import notify_admin_about_order
from bot.utils.helpers import format_date, get_user_info
from config import settings
from db import queries

router = Router()
logger = logging.getLogger("ownnetbot")

TYPE_PROMPT = "Выберите тип подписки 👇"
VLESS_PROMPT = "Vless (5 устройств) — выберите вариант 👇"
AWG_PROMPT = "Amnezia WG — выберите количество устройств 👇"


async def _edit_or_send(event: types.CallbackQuery, text: str, **kwargs) -> None:
    try:
        await event.message.edit_text(text, **kwargs)
    except Exception:
        await event.message.answer(text, **kwargs)


# ── Навигация по тарифам ─────────────────────────────────────────────────────

@router.callback_query(F.data.in_({"buy_subscription", "back_to_subscription_type"}))
async def show_subscription_types(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, TYPE_PROMPT, reply_markup=get_subscription_type_menu())


@router.callback_query(F.data == "sub_type_work")
async def show_vless(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, VLESS_PROMPT, reply_markup=get_vless_menu())


@router.callback_query(F.data.in_({"sub_type_bypass", "back_to_amnezia_devices"}))
async def show_awg_devices(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, AWG_PROMPT, reply_markup=get_amnezia_devices_menu())


@router.callback_query(F.data.startswith("sub_bypass_devices_"))
async def show_awg_plans(callback: types.CallbackQuery) -> None:
    try:
        devices = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Неизвестный вариант", show_alert=True)
        return
    if devices not in AMNEZIA_PRICES:
        await callback.answer("❌ Такого тарифа нет", show_alert=True)
        return
    await _edit_or_send(
        callback,
        f"Amnezia WG ({DEVICE_LABELS[devices]}) — выберите срок 👇",
        reply_markup=get_amnezia_plans_menu(devices),
    )


# ── Оформление заказа ────────────────────────────────────────────────────────

def _parse_tariff(data: str) -> Tariff | None:
    """Разобрать callback_data в тариф. None — если данные некорректны."""
    if data == "sub_work_test":
        return vless_test()
    if data == "sub_bypass_test":
        return awg_test()

    if data.startswith("sub_work_plan_"):
        try:
            months = int(data.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            return None
        return vless_plan(months) if months in VLESS_PRICES else None

    if data.startswith("sub_bypass_plan_"):
        parts = data.split("_")
        try:
            devices, months = int(parts[3]), int(parts[4])
        except (ValueError, IndexError):
            return None
        if devices in AMNEZIA_PRICES and months in AMNEZIA_PRICES[devices]:
            return awg_plan(devices, months)
    return None


def _payment_markup():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="💳 Перейти к оплате", url=settings.SBER_URL))
    b.add(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))
    b.adjust(1)
    return b.as_markup()


@router.callback_query(
    F.data.in_({"sub_work_test", "sub_bypass_test"})
    | F.data.startswith("sub_work_plan_")
    | F.data.startswith("sub_bypass_plan_")
)
async def handle_subscription_choice(callback: types.CallbackQuery, bot: Bot) -> None:
    tariff = _parse_tariff(callback.data)
    if tariff is None:
        await callback.answer("❌ Неизвестный тариф", show_alert=True)
        return

    user_id, username, first_name, last_name = get_user_info(callback.from_user)

    # Тест выдаётся один раз на каждый тип подписки
    if tariff.is_test and await queries.has_used_test(user_id, test_kind(tariff.sub_type)):
        await _edit_or_send(
            callback,
            "❌ Вы уже использовали тестовый период для этого типа подписки.\n\n"
            "💡 Выберите платный тариф.",
            reply_markup=get_back_menu(),
        )
        return

    # Заказ ссылается на users по внешнему ключу — гарантируем наличие записи
    await queries.ensure_user(user_id, username, first_name, last_name)
    order_id = await queries.create_order(
        user_id, username, first_name, last_name, tariff.sub_type, tariff.amount
    )

    if tariff.is_test:
        text = (f"🧪 Вы выбрали *{tariff.sub_type}*.\n"
                f"Ожидайте подтверждения администратора.\n\n{tariff.note}")
        markup = get_back_menu()
    elif settings.SBER_URL:
        text = (f"✅ Вы выбрали *{tariff.sub_type}*\n💸 {tariff.amount} руб.\n\n"
                f"Нажмите кнопку ниже для оплаты. "
                f"После оплаты дождитесь подтверждения.\n\n{tariff.note}")
        markup = _payment_markup()
    else:
        text = (f"✅ Вы выбрали *{tariff.sub_type}*\n💸 {tariff.amount} руб.\n\n"
                f"❌ Оплата временно недоступна — свяжитесь с администратором.\n\n"
                f"{tariff.note}")
        markup = get_back_menu()

    await _edit_or_send(callback, text, parse_mode="Markdown", reply_markup=markup)

    logger.info("Заказ #%s от %s (@%s): %s", order_id, user_id, username, tariff.sub_type)
    await notify_admin_about_order(
        bot, order_id, user_id, username, first_name, last_name,
        tariff.sub_type, tariff.amount, tariff.is_test,
    )


# ── Мои подписки ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_subscriptions")
async def show_my_subscriptions(callback: types.CallbackQuery) -> None:
    subs = await queries.list_user_subscriptions(callback.from_user.id)

    if not subs:
        await _edit_or_send(
            callback,
            "📭 У вас пока нет подписок.\n\n🛒 Приобрести можно в главном меню.",
            reply_markup=get_back_menu(),
        )
        return

    lines = ["📖 Ваши подписки:", ""]
    active = 0
    for sub in subs:
        status = "✅ Активна" if sub["is_active"] else "❌ Неактивна"
        lines.append(f"📦 {sub['subscription_type']}")
        if sub["subscription_link"]:
            lines.append(f"🔗 {sub['subscription_link']}")
        elif sub["config_file_id"]:
            lines.append("📎 Конфигурация отправлена файлом выше")
        lines.append(f"📅 до {format_date(sub['expires_at'])}")
        lines.append(f"🟢 {status}")
        lines.append("")
        if sub["is_active"]:
            active += 1

    if active == 0:
        lines.append("❌ Активных подписок нет. Продлите или приобретите новую.")

    await _edit_or_send(callback, "\n".join(lines).strip(),
                        reply_markup=get_back_menu(),
                        disable_web_page_preview=True)
