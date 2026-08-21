"""Инструкции по установке и настройке клиента INCY (Vless и Amnezia WG)."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.types import FSInputFile

from bot.keyboards.instructions import (
    INCY_PLATFORMS, INCY_PROTOCOLS, get_instructions_main_menu,
    get_protocol_menu, get_steps_back_menu,
)

router = Router()
logger = logging.getLogger("ownnetbot")

IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

CALLBACK_PREFIX = "instr_incy_"
# Telegram обрезает подпись к фото на 1024 символах — тексты шагов держим короче.
CAPTION_LIMIT = 1024

INTRO = ("📘 *INCY* — единственное приложение, которое понадобится для подключения.\n\n"
         "Оно принимает оба типа доступа, которые выдаёт бот:\n"
         "🔹 *Vless* — ссылка-подписка\n"
         "🔸 *Amnezia WG* — файл .conf\n\n"
         "Оба добавляются в один список серверов — переключаться между ними можно "
         "одним нажатием, без второго приложения и без переустановки.\n\n"
         "Выберите вашу платформу:")

# Шаги расписаны по реальному интерфейсу INCY v3.5.4. Мобильная и десктопная
# версии отличаются: на телефоне «Добавить» открывает шторку снизу, на ПК —
# отдельный экран, и порядок иконок в нём другой.
STEPS: dict[str, dict[str, str]] = {
    "mobile": {
        "vless": ("1️⃣ Скопируйте ссылку-подписку, которую прислал бот "
                  "(долгое нажатие на сообщение → «Копировать»).\n\n"
                  "2️⃣ Откройте INCY и на главном экране нажмите «📋 Вставить» — "
                  "сервер добавится в список автоматически.\n\n"
                  "3️⃣ Нажмите большую круглую кнопку в центре — пойдёт подключение.\n\n"
                  "При первом запуске система попросит разрешить создание "
                  "VPN-профиля — согласитесь."),
        "awg": ("1️⃣ Сохраните файл .conf, который прислал бот, к себе на устройство.\n\n"
                "2️⃣ Откройте INCY, нажмите «➕ Добавить», затем в открывшемся окне — "
                "иконку папки 📁 и выберите сохранённый файл .conf.\n\n"
                "3️⃣ Нажмите большую круглую кнопку в центре — пойдёт подключение.\n\n"
                "При первом запуске система попросит разрешить создание "
                "VPN-профиля — согласитесь."),
    },
    "desktop": {
        "vless": ("1️⃣ Скопируйте ссылку-подписку, которую прислал бот.\n\n"
                  "2️⃣ В INCY нажмите «📋 Вставить» (п. 2 на скриншоте) — "
                  "сервер добавится в список автоматически.\n\n"
                  "3️⃣ Нажмите круглую кнопку в центре (п. 3) — пойдёт подключение.\n\n"
                  "Режим *TUN* вверху оставьте включённым: он ведёт через VPN весь "
                  "трафик, а «Системный прокси» — только те программы, которые умеют "
                  "работать через прокси."),
        "awg": ("1️⃣ Сохраните файл .conf, который прислал бот.\n\n"
                "2️⃣ В INCY нажмите «➕ Добавить» (п. 1), затем иконку папки 📁 "
                "(п. 4 на нижнем скриншоте) и выберите сохранённый файл .conf.\n\n"
                "3️⃣ Вернитесь на «Главную» и нажмите круглую кнопку (п. 3) — "
                "пойдёт подключение.\n\n"
                "Режим *TUN* вверху оставьте включённым: он ведёт через VPN весь трафик."),
    },
}

FOOTER: dict[str, str] = {
    "mobile": ("\n\n💡 Все ваши серверы — вкладка «Сервера» внизу. "
               "Там же переключение между Vless и Amnezia WG."),
    "desktop": ("\n\n💡 Все ваши серверы — раздел «Сервера» в меню слева. "
                "Там же переключение между Vless и Amnezia WG."),
}


def _find_image(protocol: str, platform: str, family: str) -> Path | None:
    """Скриншот: сначала под платформу, потом под семейство, потом общий.

    Позволяет позже положить, например, incy_vless_macos.png с особенностями
    macOS — код подхватит его без правок; пока такого файла нет, берётся
    incy_vless_desktop.png.
    """
    for stem in (f"incy_{protocol}_{platform}", f"incy_{protocol}_{family}",
                 f"incy_{protocol}"):
        for ext in (".png", ".jpg", ".jpeg"):
            path = IMAGES_DIR / f"{stem}{ext}"
            if path.exists():
                return path
    logger.warning("Скриншот не найден: %s / %s / %s", protocol, platform, family)
    return None


async def _edit_or_send(event: types.CallbackQuery, text: str, **kwargs) -> None:
    try:
        await event.message.edit_text(text, **kwargs)
    except Exception:
        await event.message.answer(text, **kwargs)


@router.callback_query(F.data == "instructions")
async def show_instructions_main(callback: types.CallbackQuery) -> None:
    await _edit_or_send(callback, INTRO, parse_mode="Markdown",
                        reply_markup=get_instructions_main_menu())


@router.callback_query(F.data.startswith(CALLBACK_PREFIX))
async def show_incy_step(callback: types.CallbackQuery, bot: Bot) -> None:
    rest = callback.data[len(CALLBACK_PREFIX):]

    # Уровень 2: выбрана платформа — ссылка на установку и выбор протокола.
    if rest in INCY_PLATFORMS:
        platform = INCY_PLATFORMS[rest]
        text = (f"{platform['label']} — установка INCY\n"
                f"{platform['store_label']}:\n{platform['download']}\n\n"
                "После установки выберите, что именно вам выдал бот:")
        await _edit_or_send(callback, text, reply_markup=get_protocol_menu(rest),
                            disable_web_page_preview=True)
        return

    # Уровень 3: платформа + протокол — пошаговая инструкция со скриншотом.
    platform_key, _, protocol_key = rest.rpartition("_")
    if platform_key not in INCY_PLATFORMS or protocol_key not in INCY_PROTOCOLS:
        await callback.answer("❌ Раздел не найден", show_alert=True)
        return

    family = INCY_PLATFORMS[platform_key]["family"]
    text = (f"*{INCY_PROTOCOLS[protocol_key]['title']}*\n\n"
            f"{STEPS[family][protocol_key]}{FOOTER[family]}")
    markup = get_steps_back_menu(platform_key)
    image = _find_image(protocol_key, platform_key, family)

    if image is not None and len(text) <= CAPTION_LIMIT:
        try:
            await callback.message.answer_photo(
                FSInputFile(image), caption=text, parse_mode="Markdown",
                reply_markup=markup)
            return
        except Exception as e:
            logger.warning("Не удалось отправить %s: %s", image.name, e)

    # Скриншота нет (или он не отправился, или подпись длиннее лимита) —
    # инструкция всё равно должна дойти до пользователя.
    if image is not None:
        try:
            await callback.message.answer_photo(FSInputFile(image))
        except Exception as e:
            logger.warning("Не удалось отправить %s: %s", image.name, e)
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=markup)


@router.callback_query(
    F.data.startswith("instr_vless") | F.data.startswith("instr_awg")
    | (F.data == "back_to_instructions_main"))
async def legacy_instruction_buttons(callback: types.CallbackQuery) -> None:
    """Кнопки старых инструкций (Happ / нативный AmneziaWG).

    Сообщения бота живут в переписке вечно, и пользователь может нажать кнопку
    из сообщения, отправленного до перехода на INCY. Без этого хендлера такая
    кнопка молча не работала бы — вместо этого ведём человека в новое меню.
    """
    await callback.answer("Инструкции обновлены — теперь одно приложение INCY",
                          show_alert=False)
    await _edit_or_send(callback, INTRO, parse_mode="Markdown",
                        reply_markup=get_instructions_main_menu())
