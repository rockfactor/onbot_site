"""
Единая конфигурация проекта OwnNetBot.

Используется всеми компонентами монорепозитория:
    bot/     — Telegram-бот (aiogram 3)
    api/     — FastAPI backend
    db/      — пул соединений asyncpg
    alembic/ — миграции схемы

Все значения читаются из .env в корне репозитория.

ВАЖНО: никогда не обращайтесь к os.getenv() напрямую в коде проекта —
только через `from config import settings`. Это единственная точка,
где определяются значения по умолчанию и правила валидации.

IDN: основной домен проекта — кириллический (своясеть.рокфактор.рф).
Telegram Bot API, Let's Encrypt и ЮКасса принимают только ASCII-имена,
поэтому все внешние URL отдаются в punycode-форме. В .env домен можно
писать кириллицей — преобразование делает свойство webhook_url.
"""
from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import quote, urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def to_punycode_url(url: str) -> str:
    """
    Привести хост в URL к ASCII (punycode), сохранив схему, порт и путь.

        https://своясеть.рокфактор.рф/webhook/bot
        -> https://xn--b1ag0akch4eua.xn--80atbndhfop.xn--p1ai/webhook/bot

    Для уже-ASCII доменов возвращает URL без изменений.
    """
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        # Некорректный или пустой хост — отдаём как есть,
        # ошибку поймает валидация или сам вызывающий сервис.
        ascii_host = host
    netloc = f"{ascii_host}:{parts.port}" if parts.port else ascii_host
    return parts._replace(netloc=netloc).geturl()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Окружение ────────────────────────────────────────────────────────────
    ENV: Literal["dev", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # ── Telegram ─────────────────────────────────────────────────────────────
    BOT_TOKEN: str
    ADMIN_ID: int
    CHANNEL_USERNAME: str = "own_netbot"
    SUPPORT_USERNAME: str = "rockfactor"
    SBER_URL: Optional[str] = None

    # ── PostgreSQL (VPS-2, приватная сеть) ───────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "vpnbot"
    DB_USER: str = "vpnbot_user"
    DB_PASSWORD: str = ""
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 10
    DB_COMMAND_TIMEOUT: float = 30.0
    DB_CONNECT_TIMEOUT: float = 10.0

    # ── Webhook (этап 1) ─────────────────────────────────────────────────────
    # WEBHOOK_HOST — схема + домен без завершающего слэша.
    # Можно писать кириллицей: https://своясеть.рокфактор.рф
    WEBHOOK_HOST: str = ""
    WEBHOOK_PATH: str = "/webhook/bot"
    WEBHOOK_SECRET: str = ""
    WEBAPP_HOST: str = "127.0.0.1"
    WEBAPP_PORT: int = 8080

    # ── JWT / авторизация (этап 3) ───────────────────────────────────────────
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30

    # ── ЮКасса (этап 2) ──────────────────────────────────────────────────────
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_RETURN_URL: str = ""

    # ── S3 Beget (этап 2) ────────────────────────────────────────────────────
    S3_ENDPOINT: str = ""
    S3_REGION: str = "ru-1"
    S3_BUCKET: str = "vpn-configs"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # ── VPN-панели (этапы 2–4) ───────────────────────────────────────────────
    # AWG: панель AlexisHW работает на HTTP Basic Auth, не на API-ключе
    AWG_API_URL: str = ""
    AWG_API_USER: str = ""
    AWG_API_PASSWORD: str = ""
    AWG_SERVER_ID: str = ""

    # PasarGuard: постоянный API-ключ из POST /api/api_key
    PASARGUARD_API_URL: str = ""
    PASARGUARD_API_KEY: str = ""

    # ── Вычисляемые свойства ─────────────────────────────────────────────────

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"

    @property
    def _credentials(self) -> str:
        """Логин:пароль с процентным экранированием (спецсимволы в пароле)."""
        user = quote(self.DB_USER, safe="")
        password = quote(self.DB_PASSWORD, safe="")
        return f"{user}:{password}"

    @property
    def asyncpg_dsn(self) -> str:
        """DSN для asyncpg (драйвер не понимает префикс +asyncpg)."""
        return (
            f"postgresql://{self._credentials}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def sqlalchemy_dsn(self) -> str:
        """DSN для SQLAlchemy/Alembic."""
        return (
            f"postgresql+asyncpg://{self._credentials}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def webhook_url(self) -> str:
        """
        URL вебхука в punycode — именно он передаётся в Telegram setWebhook.
        Bot API не принимает не-ASCII домены.
        """
        if not self.WEBHOOK_HOST:
            return ""
        return to_punycode_url(f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}")

    @property
    def webhook_url_display(self) -> str:
        """Тот же URL в исходном виде — для логов и сообщений админу."""
        if not self.WEBHOOK_HOST:
            return ""
        return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"

    @property
    def yookassa_return_url(self) -> str:
        """return_url для ЮКассы — тоже требует ASCII-домен."""
        return to_punycode_url(self.YOOKASSA_RETURN_URL)

    # ── Валидация ────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _check_prod_requirements(self) -> "Settings":
        """В проде часть значений обязательна — падаем на старте, а не в рантайме."""
        if self.ENV != "prod":
            return self
        missing: list[str] = []
        if not self.DB_PASSWORD:
            missing.append("DB_PASSWORD")
        if not self.WEBHOOK_HOST:
            missing.append("WEBHOOK_HOST")
        if not self.WEBHOOK_SECRET:
            missing.append("WEBHOOK_SECRET")
        if missing:
            raise ValueError(
                "ENV=prod, но не заданы обязательные переменные: "
                + ", ".join(missing)
            )
        if not self.WEBHOOK_HOST.startswith("https://"):
            raise ValueError("WEBHOOK_HOST должен начинаться с https:// (требование Telegram)")
        # Проверяем, что домен вообще преобразуется в ASCII —
        # иначе setWebhook упадёт уже в рантайме.
        if not self.webhook_url:
            raise ValueError("WEBHOOK_HOST не удалось привести к punycode")
        return self


settings = Settings()
