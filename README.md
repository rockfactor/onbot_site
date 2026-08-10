# OwnNetBot

Telegram-бот + веб-сайт для продажи VPN-подписок.
Два продукта: **Amnezia WG** (конфиг `.conf` через S3) и **Vless** (ссылка подписки).
Целевая аудитория — 50–200 клиентов на старте.

## Стек

| Слой | Технологии |
|------|-----------|
| Бот | Python 3.11+, aiogram 3, APScheduler |
| Бэкенд | FastAPI, Uvicorn, Nginx |
| Фронтенд | React (Vite) |
| БД | PostgreSQL 16.4 (asyncpg), Alembic |
| Хранилище | Beget S3 (aioboto3) |
| Платежи | ЮKassa (webhook), СБП (ручной режим) |
| VPN-панели | AlexisHW/amneziawg-web-ui, PasarGuard/panel |

## Инфраструктура (Beget, Санкт-Петербург)

```
VPS-1 (App)          VPS-2 (DB)            S3 (Beget)
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Telegram Bot │     │ PostgreSQL   │     │ vpn-configs/ │
│ FastAPI      │────▶│ 16.4         │     │  awg/{uid}/  │
│ Nginx        │     │ port 5432    │     │  {sub}.conf  │
│ React SPA    │     └──────────────┘     └──────────────┘
└──────────────┘       приватная сеть
        │
        ▼
  VPN-панели (отдельные серверы)
  ├── AWG Panel
  └── PasarGuard Panel
```

## Текущее состояние репозитория

Проект находится в начале **Этапа 1**. Сейчас в репозитории:

```
onbot_site/
├── bot.py                  # монолит 77 КБ — рабочий бот (polling + SQLite)
├── setup_structure.py      # скрипт создания модульной структуры (30 файлов)
├── alembic/                # инициализирован, миграций нет
│   ├── env.py
│   └── versions/
├── alembic.ini
├── requirements.txt        # старый (aiogram, aiosqlite, dotenv, apscheduler, openpyxl)
├── images/                 # скриншоты для инструкций в боте
├── about.txt               # текст «О нас» для бота
├── welcome.txt             # приветственное сообщение
└── .gitignore
```

**`setup_structure.py`** при запуске из корня создаст модульную структуру:

```
├── config.py                     # pydantic-settings, все переменные из .env
├── .env.example                  # шаблон переменных окружения
├── requirements.txt              # обновлённый (+ asyncpg, fastapi, alembic, pyjwt…)
├── bot/
│   ├── main.py                   # точка входа: Bot + Dispatcher + APScheduler
│   ├── states.py                 # FSM-состояния (AdminState)
│   ├── handlers/
│   │   ├── start.py              # /start, проверка подписки на канал, «О нас»
│   │   ├── subscription.py       # покупка, выбор тарифа, «Мои подписки»
│   │   ├── instructions.py       # инструкции по платформам (Vless / AWG)
│   │   └── admin.py              # одобрение заказов, продление, экспорт, бэкап
│   ├── keyboards/
│   │   ├── main.py               # главное меню
│   │   ├── subscription.py       # клавиатуры тарифов и админ-кнопки
│   │   └── instructions.py       # навигация по инструкциям
│   ├── middlewares/
│   │   └── auto_answer.py        # авто-ответ на callback_query
│   ├── services/
│   │   ├── subscription.py       # бизнес-логика активации/продления
│   │   └── scheduler.py          # бэкап БД, проверка истечения подписок
│   └── utils/
│       ├── helpers.py            # вспомогательные функции, цены Amnezia
│       └── text_loader.py        # загрузка about.txt / welcome.txt
├── db/
│   ├── sqlite_legacy.py          # init_db для SQLite (временный)
│   └── pool.py                   # asyncpg connection pool (заглушка)
├── vpn_api/                      # VPN-адаптеры — заглушка
├── payments/                     # ЮKassa — заглушка
├── s3/                           # Beget S3 клиент — заглушка
└── auth/                         # JWT + OTP — заглушка
```

> После запуска скрипта и проверки — удалить `bot.py` и `setup_structure.py`.

## Что сейчас работает

- Telegram-бот в режиме polling (через `bot.py`)
- SQLite (`orders2.db`): таблицы `orders`, `user_subscriptions`, `users`, `used_tests`
- Ручные платежи через СБП (ссылка в кнопке)
- Ручная выдача конфигов/ссылок администратором
- Проверка подписки на Telegram-канал
- Инструкции с картинками (Vless: Android/iOS/Windows, AWG: Android/iOS/Windows)
- Планировщик: бэкап БД (ежедневно), проверка истечения подписок (каждый час), уведомление за 3 дня
- Экспорт заказов в Excel
- Тестовые периоды (Vless — 3 дня, AWG — 1 день, однократно)

## Дорожная карта

### Этап 1 — Миграция (текущий)

Три параллельных задачи:

1. **Реструктуризация** — `setup_structure.py` → запуск → проверка → удаление монолита
2. **SQLite → PostgreSQL** — `config.py` → `db/pool.py` → переписать все `aiosqlite.connect()` на asyncpg → Alembic миграции
3. **Polling → Webhook** — Nginx reverse proxy → Uvicorn → `dp.start_polling()` заменить на webhook-обработчик

Порядок: `config.py` → `db/pool.py` → хендлеры на asyncpg → Alembic → webhook → тест.

### Этап 2 — Автоматизация платежей и VPN

- ЮKassa: webhook `payment.succeeded`, автосоздание заказа
- AWG-адаптер: `VPNPanelAdapter` ABC → `AmneziaWGAdapter`
- S3-интеграция: загрузка/выдача `.conf` через aioboto3

### Этап 3 — Веб-сайт и личный кабинет

- FastAPI бэкенд (`/api/v1/`)
- React фронтенд (Vite)
- Двусторонняя авторизация (Telegram ↔ email/пароль)
- JWT (access 15 мин / refresh 30 дней httpOnly)
- OTP по email (6 цифр, SHA-256, TTL 10 мин)
- Правило доступа к VPN: `tg_id IS NOT NULL`

Страницы:
- Публичные: `/`, `/pricing`, `/instructions`, `/about`, `/auth/*`
- Кабинет: `/dashboard`, `/dashboard/subscriptions`, `/dashboard/configs`, `/dashboard/payments`, `/dashboard/profile`
- Админка: `/admin`, `/admin/users`, `/admin/orders`, `/admin/nodes`, `/admin/broadcast`

### Этап 4 — Мультипанельность

- PasarGuard адаптер
- `VPNRouter` (round-robin → least-connections → geo)
- Таблица `vpn_nodes` — добавление ноды = добавление строки в БД

### Этап 5 — Мониторинг и масштабирование

- Prometheus `/metrics`
- structlog (JSON-логи)
- `feature_flags` в БД
- API versioning (`/api/v1/`)

## Тарифы

**Vless (5 устройств):**

| Период | Цена |
|--------|------|
| Тест 3 дня | бесплатно |
| 1 месяц | 320 ₽ |
| 3 месяца | 770 ₽ |

**Amnezia WG:**

| Устройства | 1 мес | 2 мес | 3 мес | 6 мес | 12 мес |
|-----------|-------|-------|-------|-------|--------|
| 1 | 187 ₽ | 340 ₽ | 505 ₽ | 898 ₽ | 1 571 ₽ |
| 3 | 449 ₽ | 842 ₽ | 1 178 ₽ | 2 020 ₽ | 3 366 ₽ |
| 5 | 655 ₽ | 1 216 ₽ | 1 683 ₽ | 2 805 ₽ | 4 488 ₽ |

Тест AWG — 1 день, бесплатно, однократно.

## Быстрый старт (текущая версия)

```bash
git clone https://github.com/rockfactor/onbot_site.git
cd onbot_site

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Создать .env с переменными:
# BOT_TOKEN, ADMIN_ID, CHANNEL_USERNAME, SBER_URL

python bot.py
```

## Быстрый старт (после реструктуризации)

```bash
python3 setup_structure.py    # создаёт модульную структуру
cp .env.example .env          # заполнить значения
pip install -r requirements.txt
python -m bot.main            # запуск через новую точку входа
# После проверки: удалить bot.py и setup_structure.py
```

## Ключевые архитектурные решения

- **Bot instance** передаётся через DI aiogram 3, не глобальная переменная
- **`notify_admin_about_order(bot, ...)`** — `bot` первый параметр
- **Scheduler jobs** передают `args=[bot]` для функций, отправляющих сообщения
- **Все настройки** через `config.settings` (pydantic-settings), никогда `os.getenv()` напрямую
- **VPN-адаптеры** — паттерн ABC (`VPNPanelAdapter`), добавление панели = новый класс
- **VPN-ноды** — таблица `vpn_nodes`, добавление ноды = INSERT в БД

## Лицензия

MIT © 2025
