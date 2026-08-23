"""
Выбор адаптера по типу панели.

Единственное место, где `panel_type` из базы превращается в класс. Бот и API
работают с `VPNPanelAdapter` и не знают, какая панель обслуживает подписку.

Учётные данные берутся из настроек по имени набора (`credentials_key`),
а не из таблицы нод. Причина в миграции 002: база уезжает в резервные копии,
а пароль от панели открывает приватные ключи всех клиентов сервиса.
"""
from __future__ import annotations

from config import settings
from vpn_api.base import NodeSpec, PanelAuthError, PanelError, VPNPanelAdapter


def adapter_for(node: NodeSpec) -> VPNPanelAdapter:
    """
    Построить адаптер для ноды. Соединение открывается лениво, при первом
    запросе, поэтому вызов дёшев и не требует await.

    Использовать как контекстный менеджер — иначе сессия останется висеть:

        async with adapter_for(node) as panel:
            issued = await panel.create_client(name)
    """
    if node.panel_type == "amneziawg":
        # Импорт внутри ветки: он тянет aiohttp, а миграции, запросы к базе
        # и разбор конфигураций должны работать без сетевого стека.
        from vpn_api.amnezia import AmneziaWGAdapter

        user = _setting(node, "API_USER")
        password = _setting(node, "API_PASSWORD")
        if not user or not password:
            raise PanelAuthError(
                f"Нода {node.name}: не заданы {node.credentials_key}_API_USER "
                f"и {node.credentials_key}_API_PASSWORD в .env"
            )
        return AmneziaWGAdapter(node, user=user, password=password)

    if node.panel_type == "pasarguard":
        raise NotImplementedError(
            f"Нода {node.name}: адаптер PasarGuard ещё не написан. "
            f"Панель разворачивается по deploy/panels/pasarguard/README.md"
        )

    raise PanelError(
        f"Нода {node.name}: неизвестный тип панели {node.panel_type!r}. "
        f"Допустимые значения ограничены проверкой в миграции 002"
    )


def _setting(node: NodeSpec, suffix: str) -> str:
    """Значение вида AWG_API_USER — по имени набора из строки ноды."""
    return getattr(settings, f"{node.credentials_key}_{suffix}", "") or ""
