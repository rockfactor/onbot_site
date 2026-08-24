"""
Адаптер панели AlexisHW/amneziawg-web-ui.

Панель работает на HTTP Basic Auth, а не на API-ключе, и отдаёт клиенту
готовый текст `.conf`. Развёртывание и ограничения панели описаны
в deploy/panels/awg/README.md.

Что делает адаптер сверх простого HTTP-клиента:

  1. Пытается подставить индивидуальные параметры мусорных пакетов
     (Jc/Jmin/Jmax) на каждую выдачу. Общие параметры (S1-S4, H1-H4)
     задаются при создании интерфейса и здесь не трогаются: их изменение
     отключает всех разом.

     ВНИМАНИЕ: на панели 1.8.5 это не работает — см. create_client()
     и раздел «Ограничение панели 1.8.5» в deploy/panels/awg/README.md.

  2. Переписывает `Endpoint` на доменное имя ноды. Панель подставляет туда
     свой публичный IP, а конфигурация живёт у клиента месяцами: с доменом
     переезд решается A-записью, с зашитым IP — перевыпуском конфигураций
     всем активным подписчикам.

ВНИМАНИЕ, требует проверки на живой панели. У проекта нет опубликованной
спецификации API, набор путей взят из таблицы операций в
deploy/panels/README.md и из README самой панели. Имена полей в запросах
и ответах собраны в константах ниже — если панель отвечает иначе, правка
нужна только там. Сверить можно так, из-под админского туннеля:

    curl -su api_bot:ПАРОЛЬ https://ge01awg.rockfactor.ru/api/servers | python3 -m json.tool
    curl -su api_bot:ПАРОЛЬ -X POST -H 'Content-Type: application/json' \\
         -d '{"name":"probe_delete_me"}' \\
         https://ge01awg.rockfactor.ru/api/servers/SID/clients | python3 -m json.tool

Второй запрос создаёт настоящего клиента — после сверки его надо удалить.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp

from vpn_api.awg_obfuscation import generate_client_junk
from vpn_api.base import (
    ClientRef,
    ConfigRewriteError,
    IssuedClient,
    NodeSpec,
    PanelAuthError,
    PanelError,
    PanelNotFoundError,
    PanelUnavailableError,
    VPNPanelAdapter,
)
from vpn_api.wg_config import has_section, replace_peer_endpoint

logger = logging.getLogger("ownnetbot.vpn.awg")

# ── Форма ответов панели ─────────────────────────────────────────────────────
# Собрано в одном месте намеренно: это единственное, что придётся править,
# если панель сменит формат. Ключи перебираются по порядку — берётся первый
# непустой, поэтому список терпим к вариациям между версиями.

CLIENT_ID_KEYS = ("id", "client_id", "uuid", "cid")
CLIENT_NAME_KEYS = ("name", "client_name", "title")
CONFIG_KEYS = ("config", "conf", "client_config", "configuration", "file", "text")
CLIENT_LIST_KEYS = ("clients", "items", "data", "results")

DEFAULT_TIMEOUT = 20.0


def _first(payload: dict[str, Any], keys: tuple[str, ...]) -> Optional[Any]:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


class AmneziaWGAdapter(VPNPanelAdapter):
    """Адаптер одной ноды AWG. Учётные данные передаются снаружи, не читаются
    из настроек внутри: так адаптер тестируется без окружения."""

    def __init__(
        self,
        node: NodeSpec,
        *,
        user: str,
        password: str,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        super().__init__(node)
        if not node.panel_server_id:
            raise PanelError(
                f"Нода {node.name}: не задан panel_server_id — "
                f"без идентификатора интерфейса панель не знает, куда селить клиента"
            )
        self._base = node.api_url.rstrip("/")
        self._sid = node.panel_server_id
        self._auth = aiohttp.BasicAuth(user, password)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._owns_session = session is None

    # ── Транспорт ────────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session is not None and self._owns_session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Один HTTP-вызов с приведением ошибок к типам из base.

        Тела запросов и ответов не логируются: в них приватные ключи клиентов.
        """
        url = f"{self._base}{path}"
        session = await self._get_session()
        try:
            async with session.request(
                method, url, json=json_body, auth=self._auth, timeout=self._timeout
            ) as resp:
                if resp.status in (401, 403):
                    raise PanelAuthError(
                        f"Панель {self.node.name} отклонила учётные данные ({resp.status}). "
                        f"Проверьте AWG_API_USER/AWG_API_PASSWORD и вайтлист nginx: "
                        f"запрос должен приходить с адреса VPS-1 или из админского туннеля"
                    )
                if resp.status == 404:
                    raise PanelNotFoundError(f"{method} {path}: объект не найден")
                if resp.status >= 500:
                    raise PanelUnavailableError(
                        f"Панель {self.node.name} ответила {resp.status} на {method} {path}"
                    )
                if resp.status >= 400:
                    # 4xx кроме перечисленных — наша ошибка в запросе,
                    # повторять бессмысленно. Первые 200 символов тела берём
                    # в текст ошибки: конфигураций в ответах на 4xx не бывает.
                    detail = (await resp.text())[:200]
                    raise PanelError(f"{method} {path} -> {resp.status}: {detail}")

                if resp.status == 204 or not (await resp.read()):
                    return None
                try:
                    return await resp.json(content_type=None)
                except ValueError:
                    return await resp.text()

        except asyncio.TimeoutError as exc:
            raise PanelUnavailableError(
                f"Таймаут {self._timeout.total} с при {method} {path} к {self.node.name}"
            ) from exc
        except aiohttp.ClientError as exc:
            raise PanelUnavailableError(
                f"Сетевая ошибка при {method} {path} к {self.node.name}: {exc}"
            ) from exc

    # ── Операции ─────────────────────────────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            await self._request("GET", "/api/servers")
            return True
        except PanelError:
            logger.exception("Healthcheck ноды %s не прошёл", self.node.name)
            return False

    async def find_client(self, name: str) -> Optional[ClientRef]:
        payload = await self._request("GET", f"/api/servers/{self._sid}/clients")
        for item in self._as_client_list(payload):
            if _first(item, CLIENT_NAME_KEYS) == name:
                client_id = _first(item, CLIENT_ID_KEYS)
                if client_id is None:
                    raise PanelError(
                        f"Панель вернула клиента {name} без идентификатора — "
                        f"сверьте CLIENT_ID_KEYS с фактическим ответом"
                    )
                return ClientRef(client_id=str(client_id), name=name)
        return None

    async def create_client(self, name: str) -> IssuedClient:
        # ТРЕБУЕТ РЕШЕНИЯ. Проверено на живой панели 23.08.2026: поле
        # i_settings задаёт только I1–I5, а Jc/Jmin/Jmax панель копирует
        # клиенту из параметров сервера. То есть эта передача профиля
        # ни на что не влияет: у всех клиентов интерфейса он одинаковый.
        # Разнести профили можно только по разным интерфейсам (мультисервер).
        junk = generate_client_junk()
        payload = await self._request(
            "POST",
            f"/api/servers/{self._sid}/clients",
            json_body={"name": name, "i_settings": junk.as_dict()},
        )
        if not isinstance(payload, dict):
            raise PanelError(
                f"Ожидался объект в ответе на создание клиента {name}, "
                f"получено {type(payload).__name__}"
            )

        client_id = _first(payload, CLIENT_ID_KEYS)
        if client_id is None:
            raise PanelError(
                f"Панель не вернула идентификатор созданного клиента {name}. "
                f"Клиент, возможно, создан — проверьте панель вручную"
            )

        config_text = self._extract_config(payload, name)
        if self.node.client_endpoint:
            config_text = replace_peer_endpoint(config_text, self.node.client_endpoint)

        logger.info(
            "Клиент %s создан на ноде %s (Jc=%s)", name, self.node.name, junk.Jc
        )
        return IssuedClient(
            client_id=str(client_id),
            name=name,
            config_text=config_text,
            extra={"junk": junk.as_dict()},
        )

    async def suspend(self, client_id: str) -> None:
        await self._request("POST", f"/api/servers/{self._sid}/clients/{client_id}/suspend")
        logger.info("Клиент %s отключён на ноде %s", client_id, self.node.name)

    async def activate(self, client_id: str) -> None:
        # Вызывается явно и всегда: снятие suspend_at само по себе
        # не реактивирует клиента — поведение из CHANGELOG панели 1.7.1.
        await self._request("POST", f"/api/servers/{self._sid}/clients/{client_id}/activate")
        logger.info("Клиент %s включён на ноде %s", client_id, self.node.name)

    async def set_expiry(self, client_id: str, expires_at: Optional[datetime]) -> None:
        if expires_at is not None and expires_at.tzinfo is None:
            raise ValueError(
                "expires_at должен быть timezone-aware: в проекте все "
                "временные значения — TIMESTAMPTZ и datetime с таймзоной"
            )
        value = (
            expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if expires_at
            else None
        )
        await self._request(
            "PUT",
            f"/api/servers/{self._sid}/clients/{client_id}/suspend-time",
            json_body={"suspend_at": value},
        )

    async def delete(self, client_id: str) -> None:
        try:
            await self._request("DELETE", f"/api/servers/{self._sid}/clients/{client_id}")
        except PanelNotFoundError:
            # Удаление отсутствующего клиента — не ошибка: цель достигнута.
            # Иначе повторный отзыв после сбоя ронял бы обработку.
            logger.info("Клиент %s уже отсутствует на ноде %s", client_id, self.node.name)
            return
        logger.info("Клиент %s удалён с ноды %s", client_id, self.node.name)

    # ── Разбор ответов ───────────────────────────────────────────────────────

    @staticmethod
    def _as_client_list(payload: Any) -> list[dict[str, Any]]:
        """Список клиентов может прийти голым массивом или обёрнутым в объект."""
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = _first(payload, CLIENT_LIST_KEYS) or []
        else:
            items = []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _extract_config(payload: dict[str, Any], name: str) -> str:
        """
        Достать текст конфигурации и убедиться, что это действительно она.

        Проверка на секции — не паранойя: если панель вернёт сообщение об
        ошибке в поле `config`, без проверки оно уедет пользователю файлом.
        """
        raw = _first(payload, CONFIG_KEYS)
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigRewriteError(
                f"Панель не вернула текст конфигурации для {name}. "
                f"Клиент создан — удалите его вручную и сверьте CONFIG_KEYS "
                f"с фактическим ответом панели"
            )
        if not (has_section(raw, "Interface") and has_section(raw, "Peer")):
            raise ConfigRewriteError(
                f"Ответ панели для {name} не похож на конфигурацию WireGuard: "
                f"нет секций [Interface] и [Peer]"
            )
        return raw
