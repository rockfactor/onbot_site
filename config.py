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
"""
from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # WEBHOOK_HOST — схема + домен без завершающего слэша, напр. https://own-net.ru
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
    AWG_API_URL: str = ""
    AWG_API_KEY: str = ""
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
        """Полный URL вебхука, который регистрируется в Telegram."""
        if not self.WEBHOOK_HOST:
            return ""
        return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"

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
        if self.WEBHOOK_HOST and not self.WEBHOOK_HOST.startswith("https://"):
            raise ValueError("WEBHOOK_HOST должен начинаться с https:// (требование Telegram)")
        return self


settings = Settings()
