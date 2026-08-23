# Развёртывание OwnNetBot

Инструкции и конфигурации для всех серверов проекта. Монорепозиторий клонируется
целиком, но каждый сервер использует только свою часть.

## Карта инфраструктуры

| Компонент | Что делает | Домен | Клонирует репозиторий |
|---|---|---|---|
| **VPS-1** | бот, API, nginx, статика React | `своясеть.рокфактор.рф` | да |
| **VPS-2** | только PostgreSQL 16 | — | нет |
| **AWG-панель** | AlexisHW/amneziawg-web-ui | `ge01awg.rockfactor.ru` (`144.31.246.234`) | нет |
| **PasarGuard** | VLESS-панель, **ещё не установлена** | `own.rockfactor.ru` (`159.194.204.110`) | нет |

Серверы связаны приватной сетью Beget. Публично доступны только 80 и 443 на VPS-1.

```
                 интернет
                     │
                 443 │ TLS
                     ▼
        ┌────────────────────────┐
        │  VPS-1  (Ubuntu 24.04) │
        │  nginx ─┬─ бот :8080   │
        │         ├─ API  :8000  │
        │         └─ React (стат)│
        └───────────┬────────────┘
                    │ приватная сеть, 5432, hostssl
        ┌───────────▼────────────┐
        │  VPS-2  (Ubuntu 24.04) │
        │  PostgreSQL 16         │
        └────────────────────────┘
```

## Порядок

Строго в этом порядке — VPS-1 при установке проверяет доступность базы
и не запустится без неё.

### 1. VPS-2 — база данных

```bash
git clone https://github.com/rockfactor/onbot_site.git /tmp/onbot
cd /tmp/onbot/deploy/vps2-db
sudo bash setup-db.sh
sudo bash backup/install-backup.sh
```

Подробности: [`vps2-db/README.md`](vps2-db/README.md)

Сохраните пароль из вывода скрипта — он понадобится на следующем шаге
и больше нигде не отображается.

### 2. VPS-1 — приложение

Перед запуском убедитесь, что A-запись домена указывает на этот сервер:
скрипт проверит это сам и предупредит при расхождении.

```bash
git clone https://github.com/rockfactor/onbot_site.git /tmp/onbot
cd /tmp/onbot/deploy/vps1-app
sudo bash setup.sh
```

Подробности: [`vps1-app/README.md`](vps1-app/README.md)

### 3. Панели VPN

Ограничение доступа по IP: [`panels/README.md`](panels/README.md)

## Что скрипты спрашивают

Ничего не захардкожено — все значения вводятся при запуске.

| Параметр | Где спрашивается | Откуда взять |
|---|---|---|
| Приватный IP VPS-1 и VPS-2 | оба скрипта | панель Beget, раздел приватных сетей |
| Пароль роли БД | VPS-2 создаёт, VPS-1 принимает | вывод `setup-db.sh` |
| Домен | VPS-1 | ваш регистратор; можно вводить кириллицей |
| Email для Let's Encrypt | VPS-1 | ваш; на него придут письма об истечении |
| Токен бота, Telegram ID | VPS-1 | @BotFather и @userinfobot |

`WEBHOOK_SECRET` и `JWT_SECRET` генерируются автоматически через `openssl rand`.

## Кириллический домен

Основной домен записан кириллицей, а Telegram Bot API, Let's Encrypt и nginx
принимают только ASCII. Преобразование в punycode делается автоматически:

```
своясеть.рокфактор.рф  →  xn--b1ag0akch4eua.xn--80atbndhfop.xn--p1ai
```

В `.env` домен пишется кириллицей — `config.py` сам отдаёт punycode туда,
где он нужен. Вводить `xn--...` руками нигде не требуется.

## Проверка после развёртывания

```bash
# VPS-1
systemctl status ownnetbot-bot
journalctl -u ownnetbot-bot -n 50
curl -I https://ваш-домен/

# VPS-2
systemctl status postgresql
systemctl list-timers ownnetbot-backup.timer

# Вебхук зарегистрирован в Telegram
curl -s "https://api.telegram.org/bot<ТОКЕН>/getWebhookInfo"
```

В ответе `getWebhookInfo` поле `pending_update_count` должно быть нулевым,
а `last_error_message` — отсутствовать.

## Требования к безопасности

Проверить перед подключением ЮКассы — банк сканирует инфраструктуру
до заключения договора.

- [ ] TLS 1.2 минимум, SSLv2/3 и TLS 1.0/1.1 отключены — проверка на [SSL Labs](https://www.ssllabs.com/ssltest/)
- [ ] Порт 5432 недоступен из интернета — проверка с постороннего хоста
- [ ] Заголовки HSTS, CSP, `X-Frame-Options`, `X-Content-Type-Options` отдаются
- [ ] Статический IP и PTR-запись настроены
- [ ] Нет mixed content на страницах оплаты
- [ ] В футере сайта: ИНН/ОГРНИП, наименование, адреса, телефон, email
- [ ] Опубликованы политика конфиденциальности и оферта
- [ ] Сервер расположен в России (152-ФЗ) — Beget SPB подходит
- [ ] Логи хранятся не менее года

Пункты про футер, оферту и политику относятся к этапу 3, когда появится сайт.

## Обновление кода

```bash
cd /opt/ownnetbot
sudo -u ownnetbot git pull
sudo -u ownnetbot venv/bin/pip install -r requirements.txt
sudo -u ownnetbot venv/bin/alembic upgrade head
sudo systemctl restart ownnetbot-bot
```

Повторный запуск `setup.sh` тоже безопасен: он идемпотентен, а существующий
`.env` сохраняет в резервную копию перед перезаписью.
