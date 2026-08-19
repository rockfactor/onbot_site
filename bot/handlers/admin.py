"""Админские действия: выдача, продление, экспорт, перезагрузка текстов."""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone

import openpyxl
from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from bot.keyboards.main import get_main_menu
from bot.keyboards.subscription import get_admin_cancel_keyboard
from bot.prices import is_amnezia
from bot.services.subscription import activate_and_notify, renew_and_notify
from bot.states import AdminState
from bot.utils.helpers import format_user, is_admin
from bot.utils.text_loader import reload_texts
from db import queries

router = Router()
logger = logging.getLogger("ownnetbot")


async def _load_order(callback: types.CallbackQuery, prefix: str):
    """Общая часть approve_/renew_: проверить права, разобрать id, взять заказ."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Только администратор", show_alert=True)
        return None
    try:
        order_id = int(callback.data[len(prefix):])
    except ValueError:
        await callback.answer("❌ Неверный формат заказа", show_alert=True)
        return None

    order = await queries.get_order(order_id)
    if order is None:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return None
    if order["status"] == "approved":
        await callback.answer("✅ Заказ уже обработан", show_alert=True)
        return None
    return order


@router.callback_query(F.data.startswith("approve_"))
async def approve_order(callback: types.CallbackQuery, state: FSMContext) -> None:
    order = await _load_order(callback, "approve_")
    if order is None:
        return

    sub_type = order["subscription_type"]
    await state.update_data(
        order_id=order["id"], user_id=order["user_id"],
        username=order["username"], first_name=order["first_name"],
        last_name=order["last_name"], subscription_type=sub_type,
    )

    if is_amnezia(sub_type):
        await state.set_state(AdminState.waiting_for_amnezia_config)
        instruction = "📎 Отправьте файл конфигурации (.conf):"
    else:
        await state.set_state(AdminState.waiting_for_subscription_link)
        instruction = "🔗 Отправьте ссылку для активации:"

    user_info = format_user(order["user_id"], order["username"])
    text = f"📝 Заказ #{order['id']}\n{user_info}\n📦 {sub_type}\n\n{instruction}"
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_cancel_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_cancel_keyboard())


@router.callback_query(F.data.startswith("renew_"))
async def renew_order(callback: types.CallbackQuery, bot: Bot) -> None:
    order = await _load_order(callback, "renew_")
    if order is None:
        return

    expires, delivered = await renew_and_notify(
        bot, order["id"], order["user_id"], order["subscription_type"]
    )
    if expires is None:
        await callback.answer(
            "⚠️ Подписка не найдена — используйте «Выдать заново»", show_alert=True
        )
        return

    icon = "✅" if delivered else "⚠️"
    tail = ("✅ Пользователь уведомлён." if delivered
            else "⚠️ Пользователь недоступен, но БД обновлена.")
    text = (f"{icon} Подписка продлена\n\n📦 Заказ #{order['id']}\n"
            f"{format_user(order['user_id'], order['username'])}\n"
            f"📅 {order['subscription_type']}\n⏳ до {expires}\n\n{tail}")
    try:
        await callback.message.edit_text(text)
    except Exception:
        await callback.message.answer(text)


# ── Приём ссылки и конфига ───────────────────────────────────────────────────

@router.message(AdminState.waiting_for_subscription_link)
async def process_subscription_link(
    message: types.Message, state: FSMContext, bot: Bot
) -> None:
    if not is_admin(message.from_user.id):
        return
    link = (message.text or "").strip()
    if "://" not in link:
        await message.answer("❌ Это не похоже на ссылку. Отправьте корректный URL:")
        return
    await _finish_activation(message, state, bot, link=link)


@router.message(AdminState.waiting_for_amnezia_config)
async def process_amnezia_config(
    message: types.Message, state: FSMContext, bot: Bot
) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.document:
        await message.answer("❌ Отправьте файл конфигурации (.conf):")
        return
    await _finish_activation(
        message, state, bot,
        config_file_id=message.document.file_id,
        config_file_name=message.document.file_name or "config.conf",
    )


async def _finish_activation(
    message: types.Message,
    state: FSMContext,
    bot: Bot,
    link: str | None = None,
    config_file_id: str | None = None,
    config_file_name: str | None = None,
) -> None:
    data = await state.get_data()
    if not all(data.get(k) for k in ("order_id", "user_id", "subscription_type")):
        await message.answer("❌ Состояние потеряно. Начните обработку заказа заново.")
        await state.clear()
        return

    try:
        action, expires, delivered = await activate_and_notify(
            bot,
            order_id=data["order_id"], user_id=data["user_id"],
            username=data.get("username"), first_name=data.get("first_name"),
            last_name=data.get("last_name"), sub_type=data["subscription_type"],
            link=link, config_file_id=config_file_id,
        )
    except Exception:
        logger.exception("Ошибка активации заказа %s", data.get("order_id"))
        await message.answer("❌ Ошибка при обработке. Попробуйте ещё раз.")
        await state.clear()
        return

    icon = "✅" if delivered else "⚠️"
    payload = f"📎 {config_file_name}" if config_file_id else f"🔗 {link}"
    tail = ("✅ Отправлено пользователю." if delivered
            else "⚠️ Пользователь недоступен, но подписка активна.")
    await message.answer(
        f"{icon} Подписка {action}\n\n📦 Заказ #{data['order_id']}\n"
        f"{format_user(data['user_id'], data.get('username'))}\n"
        f"📅 {data['subscription_type']}\n{payload}\n⏳ до {expires}\n\n{tail}",
        disable_web_page_preview=True,
    )
    await state.clear()


# ── Отмена ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Только администратор", show_alert=True)
        return
    await state.clear()
    text = "❌ Операция отменена."
    markup = get_main_menu(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)


@router.message(Command("cancel"))
async def cancel_command(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id) or await state.get_state() is None:
        return
    await state.clear()
    await message.answer("❌ Операция отменена.",
                         reply_markup=get_main_menu(message.from_user.id))


# ── Экспорт заказов ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "export_orders")
async def export_orders(callback: types.CallbackQuery, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Только администратор", show_alert=True)
        return

    rows = await queries.list_orders()
    if not rows:
        await callback.answer("📭 Заказов пока нет", show_alert=True)
        return

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Orders"
    sheet.append(list(rows[0].keys()))
    for row in rows:
        sheet.append([
            v.replace(tzinfo=None) if isinstance(v, datetime) else v
            for v in row.values()
        ])

    # Файл временный: выгрузка содержит персональные данные и не должна
    # оставаться на диске рядом с кодом — см. .gitignore
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(tempfile.gettempdir(), f"orders_{stamp}.xlsx")
    try:
        workbook.save(path)
        await bot.send_document(callback.from_user.id, FSInputFile(path))
        await callback.answer("✅ Файл отправлен", show_alert=True)
    except Exception:
        logger.exception("Не удалось выгрузить заказы")
        await callback.answer("❌ Не удалось отправить файл", show_alert=True)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ── Тексты ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "reload_texts")
async def reload_texts_button(callback: types.CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Только администратор", show_alert=True)
        return
    reload_texts()
    await callback.answer("♻️ Тексты обновлены", show_alert=True)
    text = "✅ Файлы about.txt и welcome.txt перезагружены."
    markup = get_main_menu(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)


@router.message(Command("reload_texts"))
async def reload_texts_command(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return
    reload_texts()
    await message.answer("♻️ Тексты перезагружены.",
                         reply_markup=get_main_menu(message.from_user.id))
