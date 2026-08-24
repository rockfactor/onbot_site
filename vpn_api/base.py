"""
Общий контракт адаптеров VPN-панелей.

Панели устроены по-разному во всём: AlexisHW/amneziawg-web-ui авторизуется
Basic Auth и отдаёт готовый файл `.conf`, PasarGuard — постоянным API-ключом
и ссылкой-подпиской. Различается и жизненный цикл: у AWG отключение и включение
клиента — два отдельных вызова, причём снятие `suspend_at` НЕ реактивирует
клиента автоматически (CHANGELOG 1.7.1), у PasarGuard есть нативный `expire`.

Задача этого модуля — свести различия к одному набору операций, чтобы бот
не знал, на какой панели живёт подписка. Набор взят из таблицы «Соответствие
операций» в deploy/panels/README.md, а не придуман заново.

Идемпотентность. Ни одна из панелей не поддерживает ключ идемпотентности —
в отличие от ЮКассы. Повтор запроса после таймаута создаст второго клиента,
то есть лишний конфиг и расхождение с базой. Поэтому имя клиента
детерминировано (`client_name`), а перед созданием вызывается `find_client`.
Это часть контракта, а не деталь реализации: адаптер, который не умеет искать
клиента по имени, не может быть безопасно использован при выдаче.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ── Ошибки ───────────────────────────────────────────────────────────────────
# Разделены по тому, что с ними делать вызывающему коду, а не по коду ответа.

class PanelError(Exception):
    """Базовая ошибка работы с панелью."""


class PanelAuthError(PanelError):
    """401/403: неверные учётные данные или отозванный ключ. Повтор не поможет."""


class PanelNotFoundError(PanelError):
    """404: объекта нет. Для удаления это обычно не ошибка, для выдачи — ошибка."""


class PanelUnavailableError(PanelError):
    """Сеть, таймаут, 5xx. Единственный класс, где осмысленно повторить позже."""


class ConfigRewriteError(PanelError):
    """
    Конфигурация от панели не в том виде, который мы умеем править.

    Осознанно фатальна: лучше не выдать конфигурацию, чем выдать сломанную —
    клиент со сломанным файлом придёт в поддержку через сутки, и связать
    его проблему с этой выдачей будет уже нечем.
    """


# ── Значения ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NodeSpec:
    """
    Нода в том виде, в каком её нужно знать адаптеру.

    Отдельный тип, а не asyncpg.Record: адаптеры не должны зависеть от того,
    что ноды хранятся в PostgreSQL, и тестируются без базы.
    """
    id: int
    name: str
    panel_type: str
    product: str
    api_url: str
    credentials_key: str
    panel_server_id: Optional[str] = None
    client_endpoint: Optional[str] = None
    obfuscation: Optional[dict[str, int]] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "NodeSpec":
        """
        Собрать из строки таблицы vpn_nodes.

        Принимает любой Mapping, а не только asyncpg.Record, — адаптеры
        не должны зависеть от драйвера базы.

        JSONB заслуживает отдельной строки: asyncpg по умолчанию отдаёт его
        строкой, а не словарём, и без разбора obfuscation приехал бы
        в адаптер текстом.
        """
        obfuscation = row.get("obfuscation")
        if isinstance(obfuscation, (str, bytes)):
            obfuscation = json.loads(obfuscation)

        return cls(
            id=row["id"],
            name=row["name"],
            panel_type=row["panel_type"],
            product=row["product"],
            api_url=row["api_url"],
            credentials_key=row["credentials_key"],
            panel_server_id=row.get("panel_server_id"),
            client_endpoint=row.get("client_endpoint"),
            obfuscation=obfuscation,
        )


@dataclass(frozen=True)
class ClientRef:
    """
    Ссылка на существующего в панели клиента.

    Отдельный тип от IssuedClient не случайно: при поиске по имени панель
    возвращает только идентификатор и имя, но не конфигурацию — она отдаётся
    один раз, в момент создания. Если конфигурация нужна снова, клиента
    удаляют и создают заново под тем же именем; выдать «ту же самую» нельзя.
    """
    client_id: str
    name: str


@dataclass(frozen=True)
class IssuedClient:
    """
    Результат выдачи. Ровно один из способов доставки заполнен.

    AWG отдаёт текст конфигурации — его отправляют файлом.
    PasarGuard отдаёт ссылку-подписку — её вставляют в клиент.
    """
    client_id: str
    name: str
    config_text: Optional[str] = None
    subscription_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        filled = [bool(self.config_text), bool(self.subscription_url)]
        if sum(filled) != 1:
            raise PanelError(
                "IssuedClient должен нести ровно один способ доставки: "
                "либо config_text, либо subscription_url"
            )


def client_name(user_id: int, sub_id: int, device_no: int = 1) -> str:
    """
    Детерминированное имя клиента в панели: tg_{user_id}_{sub_id}_d{device_no}.

    Заменяет отсутствующий у панелей ключ идемпотентности: по этому имени
    клиента находят перед созданием, продлевают, отключают и отзывают.
    Все операции над подпиской работают по префиксу `tg_{user_id}_{sub_id}_`.
    """
    if device_no < 1:
        raise ValueError(f"Номер устройства начинается с 1, получено {device_no}")
    return f"tg_{user_id}_{sub_id}_d{device_no}"


def subscription_prefix(user_id: int, sub_id: int) -> str:
    """Префикс всех устройств одной подписки — для массовых операций."""
    return f"tg_{user_id}_{sub_id}_"


# ── Контракт ─────────────────────────────────────────────────────────────────

class VPNPanelAdapter(ABC):
    """
    Адаптер одной ноды. Экземпляр привязан к конкретной `NodeSpec`.

    Реализация обязана:
      * поднимать PanelUnavailableError на сетевых сбоях и 5xx — только их
        имеет смысл повторять;
      * не логировать учётные данные и тела конфигураций (в них приватные ключи);
      * быть закрываемой: соединения живут в пуле сессии, её надо освобождать.
    """

    def __init__(self, node: NodeSpec) -> None:
        self.node = node

    # ── Жизненный цикл ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "VPNPanelAdapter":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    @abstractmethod
    async def close(self) -> None:
        """Освободить сетевые ресурсы."""

    # ── Операции ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Панель отвечает и учётные данные приняты."""

    @abstractmethod
    async def find_client(self, name: str) -> Optional[ClientRef]:
        """
        Найти клиента по детерминированному имени.

        Вызывается перед созданием: панели не поддерживают идемпотентность,
        и повтор после таймаута иначе создаст дубль. Возвращает только ссылку —
        конфигурацию панель отдаёт единожды, при создании.
        """

    @abstractmethod
    async def create_client(self, name: str) -> IssuedClient:
        """Создать клиента и вернуть готовую к выдаче конфигурацию."""

    @abstractmethod
    async def suspend(self, client_id: str) -> None:
        """Отключить клиента — при истечении подписки."""

    @abstractmethod
    async def activate(self, client_id: str) -> None:
        """
        Включить клиента — при продлении.

        Вызывать явно даже после снятия срока отключения: у AWG-панели
        снятие `suspend_at` не реактивирует клиента, это задокументированное
        поведение, а не ошибка.
        """

    @abstractmethod
    async def set_expiry(self, client_id: str, expires_at: Optional[datetime]) -> None:
        """
        Плановое отключение в заданный момент. None — снять срок.

        Не заменяет `suspend`/`activate`: это подстраховка на случай, если
        планировщик бота не отработает вовремя.
        """

    @abstractmethod
    async def delete(self, client_id: str) -> None:
        """Отозвать клиента насовсем."""
