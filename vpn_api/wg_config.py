"""
Правка текста конфигурации WireGuard/AmneziaWG.

Вынесено отдельным модулем без сетевых зависимостей: это чистые функции
над текстом, их можно проверять без панели и без базы.

Единственная операция, которая нам нужна, — подмена `Endpoint`. Панель
подставляет в конфигурацию собственный публичный IP, а клиенту должен уйти
домен: конфигурация живёт на устройстве месяцами, и при блокировке адреса
переезд решается A-записью вместо перевыпуска конфигураций всем активным
подписчикам. Оговорка, которую стоит помнить: WireGuard резолвит `Endpoint`
один раз, при поднятии интерфейса, — после переезда пользователю надо
выключить и включить подключение.

Почему правка только внутри `[Peer]`: в `[Interface]` у AmneziaWG лежат
параметры обфускации (S1-S4, H1-H4, Jc/Jmin/Jmax). Расхождение хотя бы
в одном значении между клиентом и сервером — соединение не устанавливается,
поэтому секцию `[Interface]` не трогаем вообще.
"""
from __future__ import annotations

import re

from vpn_api.base import ConfigRewriteError

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")

# Ключи в конфигурации WireGuard регистронезависимы — парсер wg-quick
# принимает и `Endpoint`, и `endpoint`. Панель может отдать любой вариант.
_ENDPOINT_RE = re.compile(r"^(?P<indent>[ \t]*)endpoint[ \t]*=", re.IGNORECASE)

# Хост:порт. Хост — домен или IP, пробелов быть не должно ни в одном виде:
# строка с пробелом молча ломает разбор конфигурации на клиенте.
_ENDPOINT_VALUE_RE = re.compile(r"^[^\s:]+:\d{1,5}$")


def validate_endpoint(endpoint: str) -> None:
    """Проверить формат `хост:порт` до того, как он попадёт в файл клиента."""
    if not _ENDPOINT_VALUE_RE.match(endpoint or ""):
        raise ConfigRewriteError(
            f"Endpoint должен иметь вид 'хост:порт' без пробелов, получено {endpoint!r}"
        )
    port = int(endpoint.rsplit(":", 1)[1])
    if not 1 <= port <= 65535:
        raise ConfigRewriteError(f"Недопустимый порт в Endpoint: {port}")


def replace_peer_endpoint(config_text: str, endpoint: str) -> str:
    """
    Заменить `Endpoint` в секции `[Peer]` на переданный адрес.

    Падает, если строка `Endpoint` не найдена или найдена больше одного раза.
    Это осознанно: конфигурация неизвестной формы означает, что панель
    изменила формат ответа, и молча выдать такой файл хуже, чем не выдать
    ничего — сломанный конфиг вернётся жалобой в поддержку через сутки,
    и связать её с этой выдачей будет уже нечем.

    Переводы строк и отступы исходного файла сохраняются: конфигурация
    может уехать пользователю как есть, и лишние отличия в ней ни к чему.
    """
    validate_endpoint(endpoint)

    lines = config_text.splitlines(keepends=True)
    section: str | None = None
    targets: list[int] = []

    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")

        header = _SECTION_RE.match(line)
        if header:
            section = header.group("name").strip().lower()
            continue

        if section == "peer" and _ENDPOINT_RE.match(line):
            targets.append(i)

    if len(targets) != 1:
        raise ConfigRewriteError(
            f"В секции [Peer] ожидалась ровно одна строка Endpoint, "
            f"найдено {len(targets)}. Формат ответа панели изменился — "
            f"конфигурация не выдана."
        )

    i = targets[0]
    raw = lines[i]
    indent = _ENDPOINT_RE.match(raw.rstrip("\r\n")).group("indent")
    newline = raw[len(raw.rstrip("\r\n")):]
    lines[i] = f"{indent}Endpoint = {endpoint}{newline}"

    return "".join(lines)


def has_section(config_text: str, name: str) -> bool:
    """Есть ли в конфигурации секция с таким именем (регистр не важен)."""
    target = name.strip().lower()
    for raw in config_text.splitlines():
        header = _SECTION_RE.match(raw)
        if header and header.group("name").strip().lower() == target:
            return True
    return False
