"""Старт, главное меню, проверка подписки на канал, «О нас»."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router, types
from aiogram.filters import Command

from bot.keyboards.main import get_back_menu, get_channel_gate, get_main_menu
from bot.utils.helpers import check_channel_subscription, get_user_info
from bot.utils.text_loader import get_about_text, get_welcome_text
from db import queries

router = Router()
logger = logging.getLogger("ownnetbot")

MENU_TEXT = "👋 Добро пожаловать!\nВыберите действие:"


async def _edit_or_send(event: types.CallbackQuery, text: str, **kwargs) -> None:
    """
    Отредактировать сообщение, а если нельзя — отправить новое.

    Редактирование падает, если предыдущее сообщение было документом
    или текст не изменился; для пользователя это не должно быть заметно.
    """
    try:
        await event.message.edit_text(text, **kwargs)
    except Exception:
        await event.message.answer(text, **kwargs)


@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot) -> None:
    user_id, username, first_name, last_name = get_user_info(message.from_user)

    if not await check_channel_subscription(bot, user_id):
        await message.answer(
            "📢 Подпишитесь на канал, чтобы пользоваться ботом:",
            reply_markup=get_channel_gate(),
        )
        return

    first_start = await queries.ensure_user(user_id, username, first_name, last_name)

    if first_start:
        welcome = get_welcome_text(message.from_user.first_name or "пользователь")
        try:
            await message.answer(welcome, parse_mode="Markdown",
                                 disable_web_page_preview=True)
        except Exception:
            await message.answer(welcome, disable_web_page_preview=True)
        await queries.mark_started(user_id)

    await message.answer(MENU_TEXT, reply_markup=get_main_menu(user_id))


@router.callback_query(F.data.in_({"main_menu", "back_to_main"}))
async def back_to_main(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, "🏠 Главное меню:",
                        reply_markup=get_main_menu(callback.from_user.id))


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery, bot: Bot) -> None:
    if not await check_channel_subscription(bot, callback.from_user.id):
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        return

    user_id, username, first_name, last_name = get_user_info(callback.from_user)
    await queries.ensure_user(user_id, username, first_name, last_name)
    await _edit_or_send(callback, MENU_TEXT, reply_markup=get_main_menu(user_id))


@router.callback_query(F.data == "about")
async def show_about(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, get_about_text(), reply_markup=get_back_menu())
