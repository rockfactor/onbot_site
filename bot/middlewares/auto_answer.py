from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class AutoAnswerCallbackMiddleware(BaseMiddleware):
    """
    Автоматически отвечает на callback-запрос, если хендлер не сделал это сам.

    Без этого у пользователя крутится «часики» на кнопке до таймаута.
    """

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
