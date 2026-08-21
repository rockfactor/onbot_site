# PasarGuard — развёртывание для OwnNetBot

Панель и ноды для линейки «Vless для работы (5 устройств)». Инструкция написана
под конкретную инфраструктуру проекта, а не как общий мануал.

## Что где находится

| Роль | Сервер | Адреса | Домен |
|---|---|---|---|
| Бот и сайт | VPS-1, Beget SPB | `217.114.2.219` / `10.16.0.3` | `своясеть.рокфактор.рф` |
| **Панель** | PG-panel-SITE, Beget SPB | `159.194.204.110` / `10.16.0.4` | `own.rockfactor.ru` |
| **Нода RU** | hip.hosting MSK | `93.115.203.130` | `ru01.rockfactor.ru` |

Панель и VPS-1 в одной приватной сети Beget — этим мы воспользуемся, чтобы
бот ходил к API вообще без выхода в интернет.

```
   клиенты ────── /sub/ ──────┐
                              ▼
   админ ──WG──→ 10.10.0.0/24 ──→ [ nginx 443 ] ──→ панель 127.0.0.1:8000
                              ▲                          │
   бот  ──приватная сеть──────┘                          │ mTLS
        10.16.0.3                                        ▼
                                              нода ru01 (Москва)
```

## Ключевой принцип: панель нельзя закрыть целиком

Ссылка-подписка — это то, что покупатель вставляет в Happ или v2rayNG, и она
обязана открываться с любого устройства из любой точки. Закрыть панель
вайтлистом целиком означает сломать VLESS у всех клиентов.

Поэтому доступ разделён по путям:

| Путь | Кто | Как ограничен |
|---|---|---|
| `/sub/` | клиенты | публично, лимит частоты |
| `/api/` | бот, админ | `10.16.0.3` + `10.10.0.0/24` |
| `/dashboard/`, `/statics/` | админ | `10.10.0.0/24` |
| `/docs`, `/openapi.json` | админ | `10.10.0.0/24` + флаг в `.env` |
| всё прочее | — | `404` |

Отдаём `404`, а не `403`: код 403 подтверждает сканеру, что путь существует.

---

## Шаг 0. DNS

До начала работ:

| Запись | Значение |
|---|---|
| `own.rockfactor.ru` A | `159.194.204.110` |
| `ru01.rockfactor.ru` A | `93.115.203.130` |

Проверить с панельного сервера:

```bash
dig +short A own.rockfactor.ru
curl -s https://api.ipify.org
```

Адреса должны совпасть. Раньше времени за сертификатом не ходим — у Let's
Encrypt лимит на неудачные попытки.

---

## Шаг 1. Базовая настройка панельного сервера

```bash
ssh root@159.194.204.110

apt-get update && apt-get upgrade -y
apt-get install -y ufw curl git

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

Порт панели `8000` наружу не открываем — она будет слушать только `127.0.0.1`.

---

## Шаг 2. Админский WireGuard

Домашний IP динамический, поэтому вайтлист по внешнему адресу не годится:
у мобильного оператора это ещё и CGNAT, то есть внесённый адрес откроет
панель тысячам абонентов того же сегмента.

Решение — собственный туннель с фиксированными внутренними адресами.

```bash
cd /tmp
git clone https://github.com/rockfactor/onbot_site.git onbot
cd onbot/deploy/panels/pasarguard
sudo bash setup-admin-wg.sh
```

Скрипт спросит порт и число устройств, сгенерирует ключи и создаст
конфигурации в `/etc/wireguard/clients/`.

**Телефон** — показать QR и навести камеру в приложении WireGuard:

```bash
sudo qrencode -t ansiutf8 < /etc/wireguard/clients/device2.conf
```

**Ноутбук** — забрать файл:

```bash
scp root@159.194.204.110:/etc/wireguard/clients/device1.conf .
```

### Почему в AllowedIPs два адреса

```
AllowedIPs = 10.10.0.1/32, 159.194.204.110/32
```

Панель открывается по имени `own.rockfactor.ru`, которое резолвится
в публичный адрес. Без второй строки запрос ушёл бы мимо туннеля, и nginx
увидел бы домашний IP вместо `10.10.0.x` — то есть отказал бы в доступе.

Это split-tunnel: через туннель идёт только трафик к панели, остальное
на устройстве работает напрямую.

### Проверка

Подключись с телефона и убедись, что туннель живой:

```bash
sudo wg show wg-admin
```

В выводе должен появиться `latest handshake` у соответствующего пира.

---

## Шаг 3. Установка панели

```bash
sudo bash -c "$(curl -fsSL https://github.com/PasarGuard/scripts/raw/main/pasarguard.sh)" @ install --database postgresql
```

Установщик поднимает Docker Compose со связкой панель + PostgreSQL.

**Почему не облачная БД Beget:** панель — стороннее ПО под AGPL-3.0, и держать
её данные в одной базе с нашими заказами и платежами неправильно ни с точки
зрения изоляции, ни с точки зрения восстановления. У панели свой цикл
обновлений и свои миграции.

После установки:

- файлы: `/opt/pasarguard/`
- конфигурация: `/opt/pasarguard/.env`
- данные: `/var/lib/pasarguard/`

### Привязать панель к localhost

Правим `/opt/pasarguard/.env`:

```bash
UVICORN_HOST=127.0.0.1
UVICORN_PORT=8000

# Схема API раскрывает полный список эндпоинтов — выключаем.
# В nginx этот путь тоже закрыт, но дублирование защиты оправдано:
# при обновлении флаг может вернуться к значению по умолчанию.
DOCS=false
DEBUG=false
```

Точные имена переменных сверь с файлом, который создал установщик, — набор
меняется между версиями. Ориентир: `UVICORN_HOST` должен стать `127.0.0.1`,
а документация API — выключенной.

Перезапуск:

```bash
pasarguard restart
ss -tlnp | grep 8000
```

В выводе `ss` должно быть `127.0.0.1:8000`, а не `0.0.0.0:8000`. Если панель
слушает все интерфейсы, порт доступен снаружи в обход nginx.

---

## Шаг 4. nginx и сертификат

```bash
apt-get install -y nginx certbot
mkdir -p /var/www/certbot
```

Временный конфиг для проверки Let's Encrypt:

```bash
cat > /etc/nginx/sites-enabled/acme.conf <<'EOF'
server {
    listen 80;
    server_name own.rockfactor.ru;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 404; }
}
EOF
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

certbot certonly --webroot -w /var/www/certbot \
    -d own.rockfactor.ru --email ВАШ_EMAIL --agree-tos --non-interactive
```

Боевой конфиг из шаблона:

```bash
cd /tmp/onbot/deploy/panels/pasarguard

sed -e 's|{{PANEL_DOMAIN}}|own.rockfactor.ru|g' \
    -e 's|{{BOT_PRIVATE_IP}}|10.16.0.3|g' \
    -e 's|{{ADMIN_WG_NET}}|10.10.0.0/24|g' \
    nginx/pasarguard.conf.tmpl > /etc/nginx/sites-available/pasarguard.conf

rm -f /etc/nginx/sites-enabled/acme.conf
ln -sf /etc/nginx/sites-available/pasarguard.conf /etc/nginx/sites-enabled/

nginx -t && systemctl reload nginx
```

---

## Шаг 5. Owner-аккаунт и API-ключ

Подключись к админскому WireGuard, затем на сервере:

```bash
pasarguard cli generate-temp-key
```

Открой `https://own.rockfactor.ru/dashboard/` и введи ключ — он одноразовый
и создаёт владельца панели.

Дальше в интерфейсе создай **постоянный API-ключ** для бота.

Почему ключ, а не JWT администратора: ключ не истекает, отзывается точечно
и не требует хранить пароль владельца в `.env` бота. Если ключ утечёт, его
отзыв не затронет твой собственный доступ.

---

## Шаг 6. Нода в Москве

На сервере `93.115.203.130`:

```bash
sudo bash -c "$(curl -sL https://github.com/PasarGuard/scripts/raw/main/pg-node.sh)" @ install
```

Связь панель ↔ нода защищена взаимным TLS: панель выдаёт сертификат, который
прописывается на ноде. Порядок действий и точные поля — в документации
`docs.pasarguard.org/en/node/`, они меняются между версиями.

### Ограничение доступа к ноде

Порт управления нодой должен быть открыт **только для панели**:

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH

# порт из вывода установщика — подставить фактический
ufw allow from 159.194.204.110 to any port ПОРТ_НОДЫ proto tcp

# порты, на которых нода принимает клиентов VLESS — открыты всем
ufw allow 443/tcp

ufw --force enable
```

Порт управления наружу открывать нельзя: он даёт контроль над конфигурацией
Xray, то есть над трафиком всех клиентов этой ноды.

### Про российскую локацию

`ru01` выходит в интернет в Москве. Для клиентов, которым нужен доступ
к зарубежным сервисам, такая нода бесполезна — трафик покидает VPN там же,
где и без него. Это первая из нескольких; схема подключения последующих нод
не зависит от страны, меняются только адреса и домены.

---

## Шаг 7. Подключение к боту

На **VPS-1** добавляем в `/etc/hosts`:

```bash
echo "10.16.0.4  own.rockfactor.ru" | sudo tee -a /etc/hosts
```

Это ключевой приём: бот обращается по имени `own.rockfactor.ru`, поэтому
TLS-сертификат совпадает и проверка проходит, но пакеты идут по приватной
сети Beget и в интернет не выходят. Получаем шифрование и изоляцию сразу.

В `/opt/ownnetbot/.env`:

```bash
PASARGUARD_API_URL=https://own.rockfactor.ru
PASARGUARD_API_KEY=<постоянный ключ из шага 5>
```

Без суффикса `/pg-panel` — на новой установке API живёт в корне.

Проверка с VPS-1:

```bash
# Идёт ли трафик по приватной сети
getent hosts own.rockfactor.ru

# Отвечает ли API
curl -s -o /dev/null -w '%{http_code}\n' \
    -H "Authorization: Bearer КЛЮЧ" \
    https://own.rockfactor.ru/api/system
```

`getent` должен вернуть `10.16.0.4`. Код ответа — `200`.

Перезапуск бота: `sudo systemctl restart ownnetbot-bot`

---

## Проверка изоляции

С постороннего хоста — не с VPS-1, не из-под WireGuard:

```bash
curl -m 5 -o /dev/null -w '/sub/       %{http_code}\n' https://own.rockfactor.ru/sub/test
curl -m 5 -o /dev/null -w '/api/       %{http_code}\n' https://own.rockfactor.ru/api/system
curl -m 5 -o /dev/null -w '/dashboard/ %{http_code}\n' https://own.rockfactor.ru/dashboard/
curl -m 5 -o /dev/null -w '/openapi    %{http_code}\n' https://own.rockfactor.ru/openapi.json
curl -m 5 -o /dev/null -w 'порт 8000   %{http_code}\n' http://159.194.204.110:8000/
```

Ожидаемо:

| Проверка | Код |
|---|---|
| `/sub/` | `200` или `404` от панели — путь открыт |
| `/api/` | `403` |
| `/dashboard/` | `403` |
| `/openapi.json` | `403` |
| порт 8000 | таймаут |

Если `/dashboard/` отдаёт форму входа — вайтлист не работает, разбираться
до того, как заводить клиентов.

TLS отдельно: `https://www.ssllabs.com/ssltest/analyze.html?d=own.rockfactor.ru`,
ожидаемая оценка A или A+.

---

## Обслуживание

### Бэкапы

Состояние панели — это база в `/var/lib/pasarguard/` плюс `.env` и конфигурация
Xray. Потеря означает, что все выданные подписки перестают работать,
а восстановить их из нашей базы нельзя: там хранятся только ссылки.

```bash
tar czf /root/pasarguard_$(date +%F).tar.gz \
    /opt/pasarguard/.env /var/lib/pasarguard/
```

Поставь в cron рядом с бэкапом основной базы и выгружай копии в S3 —
локальный бэкап не переживёт потерю диска.

### Обновление

```bash
pasarguard update
```

После каждого обновления проверяй два пункта: `UVICORN_HOST` не вернулся
к `0.0.0.0` и документация API осталась выключенной. Установщики нередко
перезаписывают `.env` значениями по умолчанию.

### Логи

```bash
pasarguard logs
tail -f /var/log/nginx/pasarguard.access.log
```

По access-логу видно, кто и куда стучится, — полезно, чтобы заметить перебор
или сканирование.

---

## Лицензия

PasarGuard распространяется под **AGPL-3.0**. Копилефт распространяется
на сетевое использование: если модифицировать исходники панели, изменения
придётся раскрывать пользователям сервиса.

Пока панель используется как есть, без правок кода, а бот общается с ней
по HTTP как отдельный процесс, обязательств раскрывать код бота не возникает.
Модифицировать панель без юридической проверки не стоит.

Это не юридическая консультация — при сомнениях нужен профильный специалист.
