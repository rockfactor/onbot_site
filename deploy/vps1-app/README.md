# VPS-1 — сервер приложения

Ubuntu 24.04. Здесь живут бот, будущий API, nginx и статика React.

## Перед запуском

- VPS-2 настроен, пароль роли БД на руках
- A-запись домена указывает на публичный IP этого сервера
- Известен приватный IP VPS-2

Проверить DNS заранее:

```bash
dig +short A xn--b1ag0akch4eua.xn--80atbndhfop.xn--p1ai
curl -s https://api.ipify.org
```

Два адреса должны совпасть. Скрипт проверяет это сам, но лучше знать заранее:
Let's Encrypt ограничивает число неудачных попыток выпуска.

## Запуск

```bash
git clone https://github.com/rockfactor/onbot_site.git /tmp/onbot
cd /tmp/onbot/deploy/vps1-app
sudo bash setup.sh
```

Скрипт спросит домен (кириллицей — преобразует сам), email для Let's Encrypt,
параметры БД, токен бота и Telegram ID администратора.

## Что делает скрипт

1. Проверяет A-запись и сверяет её с IP сервера
2. Ставит Python, nginx, certbot, ufw
3. Создаёт системного пользователя `ownnetbot` без права входа
4. Клонирует репозиторий в `/opt/ownnetbot`, собирает venv
5. Генерирует `.env` с правами 600 и секретами из `openssl rand`
6. **Проверяет связь с PostgreSQL и останавливается, если её нет**
7. Применяет миграции Alembic
8. Ставит systemd-юниты, настраивает хранение журнала на год
9. Собирает конфиг nginx из шаблона, подставляя punycode-домен
10. Выпускает сертификат Let's Encrypt
11. Настраивает ufw: наружу только 22, 80, 443
12. Запускает бота

Шаг 6 намеренно стоит до всего остального: без базы бот всё равно не поднимется,
и лучше увидеть внятную ошибку сразу, чем разбирать падение в журнале.

## Структура на сервере

```
/opt/ownnetbot/          код, venv, .env (владелец ownnetbot, .env — 600)
/var/www/ownnetbot/      статика React (этап 3)
/var/www/certbot/        ACME-проверки Let's Encrypt
/etc/nginx/sites-available/ownnetbot.conf
/etc/systemd/system/ownnetbot-bot.service
/etc/systemd/system/ownnetbot-api.service   (этап 3, не включён)
```

## Порты

| Порт | Слушает | Наружу |
|---|---|---|
| 80 | nginx | да, только редирект и ACME |
| 443 | nginx | да |
| 8080 | бот (aiohttp) | **нет**, только 127.0.0.1 |
| 8000 | API (uvicorn) | **нет**, только 127.0.0.1 |

Бот и API недоступны напрямую: TLS терминирует nginx, он же ограничивает
частоту запросов и добавляет заголовки безопасности.

## Управление

```bash
systemctl status ownnetbot-bot
systemctl restart ownnetbot-bot
journalctl -u ownnetbot-bot -f
journalctl -u ownnetbot-bot --since '1 hour ago'
```

Логи идут в journald, а не в файл. Файлового лога нет намеренно:
`purchases.log` в рабочем каталоге однажды уже попал в публичный git
вместе с идентификаторами покупателей.

## Вебхук

Регистрируется автоматически при старте бота. Проверка:

```bash
source /opt/ownnetbot/.env
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool
```

Что должно быть в ответе:

- `url` — ваш домен в punycode с путём `/webhook/bot`
- `pending_update_count` — 0
- `last_error_message` — отсутствует

Если `last_error_message` содержит `SSL error` или `Connection refused`, значит,
Telegram не может достучаться: проверьте сертификат и работу nginx.

Вебхук защищён секретным токеном в заголовке `X-Telegram-Bot-Api-Secret-Token`,
который проверяет aiogram. Скрытность URL защитой не считается.

## Режимы работы

`config.py` выбирает режим по `WEBHOOK_HOST`:

- значение заполнено → webhook, aiohttp на `127.0.0.1:8080` за nginx
- значение пустое → polling, для локальной разработки

На сервере `setup.sh` всегда прописывает домен, то есть webhook.

## Переключение на polling для отладки

Иногда удобно временно уйти с вебхука — например, чтобы понять,
доходят ли апдейты вообще:

```bash
sudo systemctl stop ownnetbot-bot
cd /opt/ownnetbot
sudo -u ownnetbot bash -c 'WEBHOOK_HOST= venv/bin/python -m bot.main'
```

`Ctrl+C` для выхода, затем `sudo systemctl start ownnetbot-bot`.

## Обновление

```bash
cd /opt/ownnetbot
sudo -u ownnetbot git pull
sudo -u ownnetbot venv/bin/pip install -r requirements.txt
sudo -u ownnetbot venv/bin/alembic upgrade head
sudo systemctl restart ownnetbot-bot
```

## Сертификат

Certbot ставит таймер обновления автоматически. Проверка:

```bash
systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

Сертификат выпускается на punycode-имя — это нормально, браузер покажет
пользователю кириллицу.

## Тексты бота

Файлы `about.txt` и `welcome.txt` кладутся в `/opt/ownnetbot/`. В `welcome.txt`
подстановка `{имя пользователя}` заменяется на имя из Telegram.

```bash
sudo -u ownnetbot nano /opt/ownnetbot/about.txt
```

Перезапуск не нужен: в боте есть команда `/reload_texts` и кнопка
«Обновить тексты» в админском меню.

## Диагностика

**Бот не стартует.** Первым делом — журнал:

```bash
journalctl -u ownnetbot-bot -n 50 --no-pager
```

`PostgreSQL недоступен` — проверьте `DB_HOST` в `.env` и firewall на VPS-2.
`Unauthorized` — неверный `BOT_TOKEN`.
`WEBHOOK_HOST должен начинаться с https://` — поправьте `.env`.

**nginx не запускается.** Почти всегда это отсутствующий сертификат
или IPv6 на сервере без IPv6:

```bash
sudo nginx -t
```

Скрипт определяет отсутствие IPv6 и отключает строки `listen [::]`, но если
IPv6 отключили после установки, закомментируйте их вручную.

**Telegram не шлёт апдейты.** Проверьте `getWebhookInfo` и убедитесь, что
443 открыт: `sudo ufw status`.

## Что осталось вручную после установки

1. Заполнить в `/opt/ownnetbot/.env` реквизиты ЮКассы, S3 и VPN-панелей
2. Положить `about.txt` и `welcome.txt`
3. Ограничить доступ к панелям по IP этого сервера — см. `../panels/README.md`
4. Прогнать проверку TLS на SSL Labs

После любой правки `.env`: `sudo systemctl restart ownnetbot-bot`
