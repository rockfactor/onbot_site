"""
Загрузка текстов about.txt и welcome.txt с кэшированием в памяти.

Админ может обновить файлы на сервере и перечитать их командой
/reload_texts без перезапуска бота.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("ownnetbot")

BASE_DIR = Path(__file__).resolve().parents[2]

# Запасная кодировка: файлы правят на сервере, и «Блокнот» или вставка через
# терминал с однобайтовой кодировкой легко сохраняют их в CP1251.
FALLBACK_ENCODING = "cp1251"

_cache: dict[str, str | None] = {"about": None, "welcome": None}


def _decode(raw: bytes, filename: str) -> str | None:
    """Байты → текст. UTF-8, при неудаче — CP1251, иначе None.

    `utf-8-sig` прозрачно снимает BOM (его дописывает «Блокнот» в режиме
    «UTF-8 с BOM»); для файла без BOM результат тот же, что у `utf-8`.
    """
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text = raw.decode(FALLBACK_ENCODING)
    except UnicodeDecodeError:
        logger.error(
            "Файл %s не читается ни как UTF-8, ни как %s — текст не загружен",
            filename, FALLBACK_ENCODING)
        return None
    logger.warning(
        "Файл %s сохранён не в UTF-8, прочитан как %s. Пересохраните его "
        "в UTF-8, иначе часть символов может отображаться неверно",
        filename, FALLBACK_ENCODING)
    return text


def _read(filename: str) -> str | None:
    """Текст файла или None. Не бросает исключений: тексты не критичны,
    и битый about.txt не должен ронять бота на старте."""
    path = BASE_DIR / filename
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        logger.warning("Файл %s не найден (%s)", filename, path)
        return None
    except OSError:
        logger.exception("Ошибка чтения %s", filename)
        return None
    text = _decode(raw, filename)
    return text.strip() if text is not None else None


def get_about_text() -> str:
    if _cache["about"] is None:
        _cache["about"] = _read("about.txt")
    return _cache["about"] or "ℹ️ Информация о сервисе пока не заполнена."


def get_welcome_text(user_name: str) -> str:
    if _cache["welcome"] is None:
        _cache["welcome"] = _read("welcome.txt")
    template = _cache["welcome"]
    if template:
        return template.replace("{имя пользователя}", user_name)
    return f"🙋 Привет, {user_name}!"


def reload_texts() -> None:
    _cache["about"] = _read("about.txt")
    _cache["welcome"] = _read("welcome.txt")
    logger.info("♻️ Тексты перезагружены")
