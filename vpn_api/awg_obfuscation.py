"""
Генерация и проверка параметров обфускации AmneziaWG.

РАЗДЕЛЕНИЕ ПАРАМЕТРОВ — основа всей логики:

    Общие для сервера и клиента (менять нельзя после выдачи ключей):
        S1, S2, S3, S4, H1, H2, H3, H4
        Участвуют в разборе рукопожатия. Расхождение хотя бы в одном
        значении = соединение не устанавливается вообще.

    Индивидуальные для клиента (можно и нужно варьировать):
        Jc, Jmin, Jmax
        Управляют мусорными пакетами, которые клиент шлёт ДО рукопожатия.
        Сервер их просто игнорирует, поэтому у каждого клиента может
        быть свой профиль — это и есть защита от универсального
        DPI-правила по размеру и числу пакетов.

Использование в адаптере панели AlexisHW:

    POST /api/servers                     -> obfuscation_params = ServerParams
    POST /api/servers/{sid}/clients       -> i_settings = ClientJunk

Ограничения взяты из amnezia-vpn/amneziawg-linux-kernel-module (issue #119)
и docs.amnezia.org. Все расчёты исходят из MTU 1280.
"""
from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass

MTU = 1280

# Размеры пакетов WireGuard до добавления мусора
INIT_SIZE = 148
RESP_SIZE = 92

# ── Границы, зафиксированные протоколом ──────────────────────────────────────
JC_MIN, JC_MAX = 1, 128
JC_RECOMMENDED = (4, 12)

JUNK_SIZE_MAX = MTU                    # Jmin < Jmax <= 1280
S1_LIMIT = MTU - INIT_SIZE             # 1132
S2_LIMIT = MTU - RESP_SIZE             # 1188
S_RECOMMENDED = (15, 150)

S3_MAX = 64                            # AWG 2.0, префикс cookie-пакета
S4_MAX = 32                            # AWG 2.0, префикс пакета данных

H_MIN, H_MAX = 5, 2_147_483_647        # 1–4 заняты штатными типами WireGuard


class ObfuscationError(ValueError):
    """Параметры нарушают ограничения протокола."""


@dataclass(frozen=True)
class ServerParams:
    """Общие параметры. Одинаковы у сервера и всех его клиентов."""
    S1: int
    S2: int
    S3: int
    S4: int
    H1: int
    H2: int
    H3: int
    H4: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ClientJunk:
    """Индивидуальный профиль мусорных пакетов клиента."""
    Jc: int
    Jmin: int
    Jmax: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


# ── Проверка ─────────────────────────────────────────────────────────────────

def validate_server_params(p: ServerParams) -> None:
    """Падаем до отправки в панель, а не после выдачи сломанных конфигов."""
    if not 0 <= p.S1 <= S1_LIMIT:
        raise ObfuscationError(f"S1 должен быть в диапазоне 0..{S1_LIMIT}, получено {p.S1}")
    if not 0 <= p.S2 <= S2_LIMIT:
        raise ObfuscationError(f"S2 должен быть в диапазоне 0..{S2_LIMIT}, получено {p.S2}")

    # Ключевое ограничение протокола: при S1 + 56 == S2 размер пакета
    # инициализации совпадает с размером ответа, и обфускация теряет смысл —
    # DPI снова видит пару пакетов одинаковой длины.
    if p.S1 + 56 == p.S2:
        raise ObfuscationError(
            f"Нарушено S1 + 56 != S2: S1={p.S1}, S2={p.S2}. "
            f"Размеры init и response совпадут."
        )

    if not 0 <= p.S3 <= S3_MAX:
        raise ObfuscationError(f"S3 должен быть в диапазоне 0..{S3_MAX}, получено {p.S3}")
    if not 0 <= p.S4 <= S4_MAX:
        raise ObfuscationError(f"S4 должен быть в диапазоне 0..{S4_MAX}, получено {p.S4}")

    headers = [p.H1, p.H2, p.H3, p.H4]
    for name, value in zip(("H1", "H2", "H3", "H4"), headers):
        if not H_MIN <= value <= H_MAX:
            raise ObfuscationError(
                f"{name} должен быть в диапазоне {H_MIN}..{H_MAX}, получено {value}. "
                f"Значения 1–4 заняты штатными типами WireGuard."
            )
    if len(set(headers)) != 4:
        raise ObfuscationError(f"H1–H4 должны различаться, получено {headers}")


def validate_client_junk(j: ClientJunk) -> None:
    if not JC_MIN <= j.Jc <= JC_MAX:
        raise ObfuscationError(f"Jc должен быть в диапазоне {JC_MIN}..{JC_MAX}, получено {j.Jc}")
    if j.Jmin >= j.Jmax:
        raise ObfuscationError(f"Требуется Jmin < Jmax, получено {j.Jmin} и {j.Jmax}")
    if j.Jmax > JUNK_SIZE_MAX:
        raise ObfuscationError(f"Jmax не должен превышать {JUNK_SIZE_MAX}, получено {j.Jmax}")


# ── Генерация ────────────────────────────────────────────────────────────────

def _rand(low: int, high: int) -> int:
    """Криптостойкий выбор в диапазоне включительно."""
    return low + secrets.randbelow(high - low + 1)


def generate_server_params() -> ServerParams:
    """
    Сгенерировать общие параметры для нового сервера панели.

    Вызывается ОДИН раз при создании интерфейса. После выдачи первого
    конфига менять их нельзя: все ранее выданные клиенты перестанут
    подключаться разом.

    Если параметры понадобится сменить (DPI научился их распознавать),
    ротация делается через мультисервер панели: создаётся новый интерфейс
    awg1 со свежими значениями, новые клиенты выдаются на нём, а awg0
    живёт, пока не истекут старые подписки.
    """
    s1 = _rand(*S_RECOMMENDED)

    # Подбираем S2, пока не уйдём от запрещённого равенства
    s2 = _rand(*S_RECOMMENDED)
    while s1 + 56 == s2:
        s2 = _rand(*S_RECOMMENDED)

    # Заголовки берём из непересекающихся четвертей диапазона:
    # так исключены совпадения и значения выходят непохожими друг на друга
    quarter = (H_MAX - H_MIN) // 4
    headers = [
        _rand(H_MIN + quarter * i, H_MIN + quarter * (i + 1) - 1)
        for i in range(4)
    ]

    params = ServerParams(
        S1=s1, S2=s2,
        S3=_rand(8, S3_MAX),
        S4=_rand(4, S4_MAX),
        H1=headers[0], H2=headers[1], H3=headers[2], H4=headers[3],
    )
    validate_server_params(params)
    return params


def generate_client_junk() -> ClientJunk:
    """
    Индивидуальный профиль мусорных пакетов.

    Вызывается на КАЖДУЮ выдачу конфигурации. Значения различаются
    от клиента к клиенту, поэтому по числу и размеру пакетов перед
    рукопожатием нельзя построить одно правило DPI на весь сервис.

    Безопасно менять в любой момент: сервер эти пакеты не разбирает.
    """
    jmin = _rand(20, 120)
    jmax = jmin + _rand(40, 400)
    if jmax > JUNK_SIZE_MAX:
        jmax = JUNK_SIZE_MAX

    junk = ClientJunk(Jc=_rand(*JC_RECOMMENDED), Jmin=jmin, Jmax=jmax)
    validate_client_junk(junk)
    return junk


def packet_sizes(p: ServerParams) -> dict[str, int]:
    """Итоговые размеры пакетов — для диагностики и логов."""
    return {
        "init": INIT_SIZE + p.S1,
        "response": RESP_SIZE + p.S2,
        "cookie": 64 + p.S3,
        "data_overhead": p.S4,
    }
