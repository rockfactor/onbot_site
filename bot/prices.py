"""
Единственный источник правды по тарифам.

Подписи кнопок и списываемые суммы берутся отсюда, поэтому разойтись
они не могут. В старом монолите это было продублировано в двух местах
и разошлось: кнопка показывала 550 ₽, а списывалось 320 ₽.
"""
from __future__ import annotations

from typing import NamedTuple

# ── Amnezia WG: {устройств: {месяцев: цена}} ─────────────────────────────────
AMNEZIA_PRICES: dict[int, dict[int, int]] = {
    1: {1: 187, 2: 340,  3: 505,  6: 898,  12: 1571},
    3: {1: 449, 2: 842,  3: 1178, 6: 2020, 12: 3366},
    5: {1: 655, 2: 1216, 3: 1683, 6: 2805, 12: 4488},
}

# ── Vless: {месяцев: цена} ───────────────────────────────────────────────────
VLESS_PRICES: dict[int, int] = {1: 320, 3: 770}

MONTH_LABELS: dict[int, str] = {
    1: "1 месяц", 2: "2 месяца", 3: "3 месяца",
    6: "6 месяцев", 12: "12 месяцев",
}

DEVICE_LABELS: dict[int, str] = {
    1: "1 устройство", 3: "3 устройства", 5: "5 устройств",
}

# ── Длительность тестовых периодов, дней ─────────────────────────────────────
TEST_DAYS_VLESS = 3
TEST_DAYS_AWG = 1

VLESS_NAME = "Vless для работы (5 устройств)"
AWG_NAME = "Amnezia WG"


class Tariff(NamedTuple):
    """Разобранный тариф — то, что уходит в заказ."""
    sub_type: str
    amount: int
    days: int
    is_test: bool
    note: str


def _months_to_days(months: int) -> int:
    """12 месяцев считаем годом, остальное — по 30 дней."""
    return 365 if months == 12 else months * 30


def vless_test() -> Tariff:
    return Tariff(
        sub_type=f"{VLESS_NAME} - Тест {TEST_DAYS_VLESS} дня",
        amount=0, days=TEST_DAYS_VLESS, is_test=True,
        note="Подписка действует для 5 устройств без лимита трафика.",
    )


def vless_plan(months: int) -> Tariff:
    return Tariff(
        sub_type=f"{VLESS_NAME} - {MONTH_LABELS[months]}",
        amount=VLESS_PRICES[months], days=_months_to_days(months), is_test=False,
        note="Подписка действует для 5 устройств без лимита трафика.",
    )


def awg_test() -> Tariff:
    return Tariff(
        sub_type=f"{AWG_NAME} - Тест {TEST_DAYS_AWG} день",
        amount=0, days=TEST_DAYS_AWG, is_test=True,
        note="Подписка действует без лимита трафика.",
    )


def awg_plan(devices: int, months: int) -> Tariff:
    return Tariff(
        sub_type=f"{AWG_NAME} ({DEVICE_LABELS[devices]}) - {MONTH_LABELS[months]}",
        amount=AMNEZIA_PRICES[devices][months],
        days=_months_to_days(months),
        is_test=False,
        note="Подписка действует без лимита трафика.",
    )


def is_amnezia(sub_type: str) -> bool:
    return AWG_NAME in sub_type


def is_test_type(sub_type: str) -> bool:
    return "Тест" in sub_type


def days_for(sub_type: str) -> int:
    """
    Срок подписки по её названию — используется при продлении,
    когда исходный Tariff уже не под рукой.
    """
    if is_test_type(sub_type):
        return TEST_DAYS_AWG if is_amnezia(sub_type) else TEST_DAYS_VLESS
    for months in (12, 6, 3, 2, 1):
        if MONTH_LABELS[months] in sub_type:
            return _months_to_days(months)
    return 30


def test_kind(sub_type: str) -> str:
    """Ключ для таблицы used_tests."""
    return "bypass" if is_amnezia(sub_type) else "work"
