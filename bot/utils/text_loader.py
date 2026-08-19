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

_cache: dict[str, str | None] = {"about": None, "welcome": None}


def _read(filename: str) -> str | None:
    path = BASE_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("Файл %s не найден (%s)", filename, path)
        return None
    except OSError:
        logger.exception("Ошибка чтения %s", filename)
        return None


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
