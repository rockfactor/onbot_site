#!/usr/bin/env bash
#
# Развёртывание OwnNetBot на VPS-1 (Ubuntu 24.04).
#
# Ставит Python-окружение, systemd-юниты, nginx и сертификат Let's Encrypt.
# Все значения запрашиваются интерактивно. Скрипт идемпотентен.
#
#   sudo bash deploy/vps1-app/setup.sh
#
# Требования: VPS-2 уже настроен (deploy/vps2-db/setup-db.sh),
# A-запись домена указывает на этот сервер.
#
set -euo pipefail

BOLD=$'\e[1m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'
info() { echo "${GREEN}==>${RESET} $*"; }
warn() { echo "${YELLOW}!!${RESET}  $*"; }
die()  { echo "${RED}ОШИБКА:${RESET} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускайте через sudo: sudo bash deploy/vps1-app/setup.sh"

APP_USER="ownnetbot"
APP_DIR="/opt/ownnetbot"
WEB_ROOT="/var/www/ownnetbot"
REPO_URL="https://github.com/rockfactor/onbot_site.git"

# Каталог, откуда запущен скрипт (deploy/vps1-app)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "${BOLD}Развёртывание OwnNetBot на сервере приложения (VPS-1)${RESET}"
echo

# ── Ввод параметров ──────────────────────────────────────────────────────────

read -rp "Домен сайта (можно кириллицей), напр. своясеть.рокфактор.рф: " DOMAIN_UTF
[[ -n "$DOMAIN_UTF" ]] || die "Домен не может быть пустым"

# Telegram, Let's Encrypt и nginx понимают только ASCII.
# Преобразование делаем здесь, чтобы руками xn--... не вводить.
DOMAIN_PUNY="$(python3 -c "
import sys
try:
    print(sys.argv[1].strip().encode('idna').decode('ascii'))
except Exception as e:
    print('IDNA_ERROR', e, file=sys.stderr); sys.exit(1)
" "$DOMAIN_UTF")" || die "Не удалось преобразовать домен в punycode"

if [[ "$DOMAIN_PUNY" != "$DOMAIN_UTF" ]]; then
    info "Домен в ASCII: ${DOMAIN_PUNY}"
fi

read -rp "Email для Let's Encrypt (уведомления об истечении): " LE_EMAIL
[[ "$LE_EMAIL" == *@* ]] || die "Некорректный email"

echo
read -rp "Приватный IP сервера БД (VPS-2), напр. 10.0.0.2: " DB_HOST
[[ -n "$DB_HOST" ]] || die "IP не может быть пустым"

read -rp "Имя базы [vpnbot]: " DB_NAME
DB_NAME="${DB_NAME:-vpnbot}"
read -rp "Роль БД [vpnbot_user]: " DB_USER
DB_USER="${DB_USER:-vpnbot_user}"
read -rsp "Пароль роли БД (из вывода setup-db.sh): " DB_PASSWORD; echo
[[ -n "$DB_PASSWORD" ]] || die "Пароль обязателен"

echo
read -rp "Токен бота от @BotFather: " BOT_TOKEN
[[ "$BOT_TOKEN" == *:* ]] || die "Токен должен быть в формате 123456789:AA..."
read -rp "Ваш Telegram ID (администратор): " ADMIN_ID
[[ "$ADMIN_ID" =~ ^[0-9]+$ ]] || die "ID должен быть числом"

read -rp "Канал для обязательной подписки, без @ [own_netbot]: " CHANNEL_USERNAME
CHANNEL_USERNAME="${CHANNEL_USERNAME:-own_netbot}"
read -rp "Username поддержки, без @ [rockfactor]: " SUPPORT_USERNAME
SUPPORT_USERNAME="${SUPPORT_USERNAME:-rockfactor}"
read -rp "Ссылка на оплату СБП (можно оставить пустой): " SBER_URL

WEBHOOK_SECRET="$(openssl rand -hex 32)"
JWT_SECRET="$(openssl rand -hex 32)"

echo
echo "${BOLD}Проверьте параметры:${RESET}"
echo "  Домен:        ${DOMAIN_UTF}"
echo "  В ASCII:      ${DOMAIN_PUNY}"
echo "  Вебхук:       https://${DOMAIN_PUNY}/webhook/bot"
echo "  База:         ${DB_USER}@${DB_HOST}/${DB_NAME}"
echo "  Админ:        ${ADMIN_ID}"
echo "  Каталог:      ${APP_DIR}"
echo
read -rp "Всё верно? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || die "Отменено пользователем"

# ── Проверка DNS до выпуска сертификата ──────────────────────────────────────

info "Проверяю A-запись домена"
apt-get update -qq
apt-get install -y dnsutils curl >/dev/null

SERVER_IP="$(curl -s --max-time 10 https://api.ipify.org || echo '')"
DOMAIN_IP="$(dig +short A "$DOMAIN_PUNY" | tail -1)"

if [[ -z "$DOMAIN_IP" ]]; then
    warn "A-запись для ${DOMAIN_PUNY} не найдена."
    warn "Let's Encrypt не сможет выпустить сертификат."
    read -rp "Продолжить без сертификата? [y/N] " SKIP_SSL_CONFIRM
    [[ "$SKIP_SSL_CONFIRM" =~ ^[Yy]$ ]] || die "Настройте DNS и запустите снова"
    SKIP_SSL=1
elif [[ -n "$SERVER_IP" && "$DOMAIN_IP" != "$SERVER_IP" ]]; then
    warn "A-запись указывает на ${DOMAIN_IP}, а IP этого сервера — ${SERVER_IP}"
    read -rp "Продолжить всё равно? [y/N] " IP_CONFIRM
    [[ "$IP_CONFIRM" =~ ^[Yy]$ ]] || die "Поправьте DNS и запустите снова"
    SKIP_SSL=1
else
    info "A-запись указывает на этот сервер (${DOMAIN_IP})"
    SKIP_SSL=0
fi

# ── Пакеты ───────────────────────────────────────────────────────────────────

info "Устанавливаю пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y \
    python3 python3-venv python3-pip git nginx ufw \
    certbot python3-certbot-nginx openssl >/dev/null

# ── Пользователь и каталоги ──────────────────────────────────────────────────

if ! id "$APP_USER" &>/dev/null; then
    info "Создаю системного пользователя ${APP_USER}"
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR" "$WEB_ROOT" /var/www/certbot

# ── Код ──────────────────────────────────────────────────────────────────────

if [[ -d "${APP_DIR}/.git" ]]; then
    info "Обновляю код"
    git -C "$APP_DIR" fetch origin
    git -C "$APP_DIR" reset --hard origin/main
else
    info "Клонирую репозиторий"
    git clone "$REPO_URL" "$APP_DIR"
fi

# ── Виртуальное окружение ────────────────────────────────────────────────────
# Ubuntu 24.04 запрещает pip install в системный Python (PEP 668),
# поэтому venv обязателен, а не «желателен»

info "Собираю виртуальное окружение"
[[ -d "${APP_DIR}/venv" ]] || python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

# ── .env ─────────────────────────────────────────────────────────────────────

ENV_FILE="${APP_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
    cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    warn "Существующий .env сохранён в резервную копию"
fi

info "Записываю .env"
cat > "$ENV_FILE" <<ENVFILE
# Создан deploy/vps1-app/setup.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)
ENV=prod
LOG_LEVEL=INFO

BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
CHANNEL_USERNAME=${CHANNEL_USERNAME}
SUPPORT_USERNAME=${SUPPORT_USERNAME}
SBER_URL=${SBER_URL}

DB_HOST=${DB_HOST}
DB_PORT=5432
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_POOL_MIN=2
DB_POOL_MAX=10
DB_COMMAND_TIMEOUT=30
DB_CONNECT_TIMEOUT=10

WEBHOOK_HOST=https://${DOMAIN_UTF}
WEBHOOK_PATH=/webhook/bot
WEBHOOK_SECRET=${WEBHOOK_SECRET}
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8080

JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_TTL_MIN=15
REFRESH_TOKEN_TTL_DAYS=30

YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://${DOMAIN_UTF}/dashboard/payments

S3_ENDPOINT=
S3_REGION=ru-1
S3_BUCKET=vpn-configs
S3_ACCESS_KEY=
S3_SECRET_KEY=

AWG_API_URL=
AWG_API_USER=
AWG_API_PASSWORD=
AWG_SERVER_ID=

PASARGUARD_API_URL=
PASARGUARD_API_KEY=
ENVFILE

# .env содержит токен бота и пароль БД — доступ только владельцу
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$ENV_FILE"
chown root:root "$WEB_ROOT"

# ── Проверка связи с БД до запуска бота ──────────────────────────────────────

info "Проверяю доступность PostgreSQL на ${DB_HOST}"

# Вывод проверки сохраняем и показываем при отказе. Раньше он уходил
# в /dev/null, и любая причина — неверный пароль, отказ TLS, недоступный
# порт, ошибка импорта — выглядела одинаково: список из четырёх версий,
# из которых верна одна. Настоящее сообщение asyncpg называет причину сразу.
DB_CHECK_LOG="$(mktemp)"
chmod 600 "$DB_CHECK_LOG"
if sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && venv/bin/python -c '
import asyncio, sys
from db.pool import healthcheck
sys.exit(0 if asyncio.run(healthcheck()) else 1)
'" >"$DB_CHECK_LOG" 2>&1; then
    info "PostgreSQL отвечает"
    rm -f "$DB_CHECK_LOG"
else
    DB_CHECK_OUT="$(cat "$DB_CHECK_LOG")"
    rm -f "$DB_CHECK_LOG"
    warn "Ответ проверки:"
    # Пароль вырезаем подстановкой bash, а не sed: в нём могут быть символы,
    # которые sed примет за синтаксис. Кавычки вокруг переменной обязательны —
    # без них шаблон разбирается как глоб, и пароль со звёздочкой или обратной
    # косой чертой сопоставился бы не с собой.
    printf '%s\n' "${DB_CHECK_OUT//"$DB_PASSWORD"/***}" | sed 's/^/    /' >&2
    die "PostgreSQL недоступен. Сообщение выше называет причину; типичные:
  - 'password authentication failed' — пароль не тот, что выдал setup-db.sh
  - 'no pg_hba.conf entry' — в pg_hba.conf стоит другой приватный IP VPS-1
  - 'Connection refused' / таймаут — база слушает только localhost
    либо порт 5432 закрыт в ufw на VPS-2
  - 'no encryption' / ошибка SSL — сервер требует hostssl, клиент не согласовал TLS"
fi

# ── Миграции ─────────────────────────────────────────────────────────────────

info "Применяю миграции Alembic"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && venv/bin/alembic upgrade head" \
    || die "Миграции не применились"

# ── systemd ──────────────────────────────────────────────────────────────────

info "Устанавливаю systemd-юниты"
install -m 644 "${SCRIPT_DIR}/systemd/ownnetbot-bot.service" /etc/systemd/system/
install -m 644 "${SCRIPT_DIR}/systemd/ownnetbot-api.service" /etc/systemd/system/

# Логи журнала: минимум год хранения — требование для платёжной инфраструктуры
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/ownnetbot.conf <<'JOURNAL'
# Управляется deploy/vps1-app/setup.sh
[Journal]
Storage=persistent
MaxRetentionSec=1year
SystemMaxUse=2G
JOURNAL
systemctl restart systemd-journald

systemctl daemon-reload
systemctl enable ownnetbot-bot.service >/dev/null
# ownnetbot-api намеренно не включаем: каталога api/ ещё нет (этап 3)

# ── nginx ────────────────────────────────────────────────────────────────────

info "Настраиваю nginx"

NGINX_CONF="/etc/nginx/sites-available/ownnetbot.conf"
sed -e "s|{{DOMAIN_PUNY}}|${DOMAIN_PUNY}|g" \
    -e "s|{{DOMAIN_UTF}}|${DOMAIN_UTF}|g" \
    -e "s|{{WEBHOOK_PATH}}|/webhook/bot|g" \
    "${SCRIPT_DIR}/nginx/ownnetbot.conf.tmpl" > "$NGINX_CONF"

# Если IPv6 в системе нет, listen [::] уронит nginx при старте
if [[ ! -f /proc/net/if_inet6 ]]; then
    warn "IPv6 не обнаружен — отключаю строки listen [::]"
    sed -i 's|^\(\s*\)listen \[::\]|\1# listen [::]|' "$NGINX_CONF"
fi

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/ownnetbot.conf
rm -f /etc/nginx/sites-enabled/default

install -m 644 "${SCRIPT_DIR}/logrotate/ownnetbot-nginx" /etc/logrotate.d/ownnetbot-nginx

# ── Сертификат ───────────────────────────────────────────────────────────────

if [[ "$SKIP_SSL" -eq 0 ]]; then
    info "Выпускаю сертификат Let's Encrypt"

    # Временный HTTP-конфиг: certbot должен пройти проверку до того,
    # как основной конфиг потребует несуществующие файлы сертификата
    cat > /etc/nginx/sites-enabled/ownnetbot-acme.conf <<ACME
server {
    listen 80;
    server_name ${DOMAIN_PUNY};
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 404; }
}
ACME
    rm -f /etc/nginx/sites-enabled/ownnetbot.conf
    nginx -t >/dev/null && systemctl restart nginx

    if certbot certonly --webroot -w /var/www/certbot \
        -d "$DOMAIN_PUNY" --email "$LE_EMAIL" \
        --agree-tos --non-interactive --keep-until-expiring; then
        info "Сертификат получен"
    else
        warn "Certbot не справился. Основной конфиг nginx не будет включён."
        warn "Проверьте DNS и запустите: certbot certonly --webroot -w /var/www/certbot -d ${DOMAIN_PUNY}"
        SKIP_SSL=1
    fi

    rm -f /etc/nginx/sites-enabled/ownnetbot-acme.conf
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/ownnetbot.conf
fi

if [[ "$SKIP_SSL" -eq 1 ]]; then
    warn "Сертификата нет — конфиг nginx оставлен выключенным"
    rm -f /etc/nginx/sites-enabled/ownnetbot.conf
fi

# ── Firewall ─────────────────────────────────────────────────────────────────

info "Настраиваю firewall"

# reset стирает ВСЕ правила ufw, не только наши. Если на сервере появится
# что-то помимо этого скрипта — админский туннель, доступ к базе, — при
# повторном запуске правила будут потеряны.
if ufw status 2>/dev/null | grep -q '^Status: active'; then
    warn "ufw уже активен — правила будут сброшены и заданы заново"
    ufw status numbered || true
fi
ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# Порты 8080 и 8000 наружу не открываются: они слушают только 127.0.0.1
# и доступны исключительно через nginx

# ── Запуск ───────────────────────────────────────────────────────────────────

if [[ "$SKIP_SSL" -eq 0 ]]; then
    info "Запускаю nginx и бота"
    nginx -t >/dev/null || die "Конфигурация nginx не прошла проверку"
    systemctl restart nginx
    systemctl restart ownnetbot-bot.service
    sleep 4

    if systemctl is-active --quiet ownnetbot-bot; then
        info "Бот запущен"
    else
        warn "Бот не поднялся. Смотрите: journalctl -u ownnetbot-bot -n 50"
    fi
else
    warn "Бот не запущен: без HTTPS вебхук работать не будет"
fi

# ── Итог ─────────────────────────────────────────────────────────────────────

echo
echo "${GREEN}${BOLD}Развёртывание завершено.${RESET}"
echo
echo "${BOLD}Проверка:${RESET}"
echo "  systemctl status ownnetbot-bot"
echo "  journalctl -u ownnetbot-bot -f"
echo "  curl -I https://${DOMAIN_PUNY}/"
echo
echo "${BOLD}Вебхук:${RESET} https://${DOMAIN_PUNY}/webhook/bot"
echo "  Проверить регистрацию в Telegram:"
echo "  curl -s 'https://api.telegram.org/bot<ТОКЕН>/getWebhookInfo'"
echo
echo "${BOLD}Осталось сделать вручную:${RESET}"
echo "  1. Заполнить в ${APP_DIR}/.env реквизиты ЮКассы, S3 и VPN-панелей"
echo "  2. Внести публичный IP этого сервера в вайтлист панелей:"
echo "     ${SERVER_IP:-<IP этого сервера>} — см. deploy/panels/README.md"
echo "  3. Проверить TLS: https://www.ssllabs.com/ssltest/analyze.html?d=${DOMAIN_PUNY}"
echo
echo "  about.txt и welcome.txt приезжают вместе с репозиторием — класть"
echo "  их отдельно не нужно."
echo
warn "После правки .env: sudo systemctl restart ownnetbot-bot"
