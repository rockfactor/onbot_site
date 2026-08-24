#!/usr/bin/env bash
#
# Настройка PostgreSQL 16 на VPS-2 (Ubuntu 24.04).
#
# Скрипт идемпотентен: повторный запуск не ломает уже настроенное.
# Все значения запрашиваются интерактивно, ничего не захардкожено.
#
#   sudo bash setup-db.sh
#
set -euo pipefail

BOLD=$'\e[1m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'

info()  { echo "${GREEN}==>${RESET} $*"; }
warn()  { echo "${YELLOW}!!${RESET}  $*"; }
die()   { echo "${RED}ОШИБКА:${RESET} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускайте через sudo: sudo bash setup-db.sh"

# ── Ввод параметров ──────────────────────────────────────────────────────────

echo "${BOLD}Настройка PostgreSQL для OwnNetBot (VPS-2)${RESET}"
echo

read -rp "Приватный IP этого сервера (VPS-2), напр. 10.0.0.2: " DB_BIND_IP
[[ -n "$DB_BIND_IP" ]] || die "IP не может быть пустым"

read -rp "Приватный IP сервера приложения (VPS-1), напр. 10.0.0.1: " APP_IP
[[ -n "$APP_IP" ]] || die "IP не может быть пустым"

read -rp "Имя базы данных [vpnbot]: " DB_NAME
DB_NAME="${DB_NAME:-vpnbot}"

read -rp "Имя роли [vpnbot_user]: " DB_USER
DB_USER="${DB_USER:-vpnbot_user}"

echo
echo "Пароль роли. Оставьте пустым, чтобы сгенерировать автоматически."
read -rsp "Пароль: " DB_PASSWORD; echo
if [[ -z "$DB_PASSWORD" ]]; then
    DB_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"
    GENERATED=1
else
    GENERATED=0
fi

echo
echo "${BOLD}Проверьте параметры:${RESET}"
echo "  Слушать на:        $DB_BIND_IP (+ localhost)"
echo "  Доступ разрешён:   $APP_IP"
echo "  База:              $DB_NAME"
echo "  Роль:              $DB_USER"
echo "  Пароль:            $([[ $GENERATED -eq 1 ]] && echo '(сгенерирован, будет показан в конце)' || echo '(введён вручную)')"
echo
read -rp "Всё верно? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || die "Отменено пользователем"

# ── Установка ────────────────────────────────────────────────────────────────

info "Устанавливаю PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y postgresql postgresql-contrib openssl >/dev/null

PG_VERSION="$(ls /etc/postgresql/ | sort -V | tail -1)"
PG_CONF_DIR="/etc/postgresql/${PG_VERSION}/main"
[[ -d "$PG_CONF_DIR" ]] || die "Не найден каталог конфигурации PostgreSQL"
info "Версия PostgreSQL: $PG_VERSION"

systemctl enable --now postgresql >/dev/null 2>&1 || true

# ── Роль и база ──────────────────────────────────────────────────────────────

info "Создаю роль и базу"

ROLE_EXISTS="$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'")"

# Пароль уходит через временный файл с правами 600, а не аргументом команды:
# аргументы видны всем в `ps aux`, а переменные окружения может вырезать
# env_reset в sudoers. Файл удаляется в любом случае через trap.
SQL_TMP="$(mktemp)"
chmod 600 "$SQL_TMP"
cleanup_sql() { [[ -f "$SQL_TMP" ]] && shred -u "$SQL_TMP" 2>/dev/null || rm -f "$SQL_TMP"; }
trap cleanup_sql EXIT

# Пароль экранируется удвоением одинарных кавычек — единственный спецсимвол,
# способный сломать строковый литерал PostgreSQL
DB_PASSWORD_SQL="${DB_PASSWORD//\'/\'\'}"

if [[ "$ROLE_EXISTS" == "1" ]]; then
    warn "Роль ${DB_USER} уже существует — обновляю пароль"
    echo "ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD_SQL}';" > "$SQL_TMP"
else
    echo "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD_SQL}';" > "$SQL_TMP"
fi

chown postgres "$SQL_TMP"
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -f "$SQL_TMP" \
    || die "Не удалось создать или обновить роль ${DB_USER}"
cleanup_sql
trap - EXIT

DB_EXISTS="$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")"

if [[ "$DB_EXISTS" == "1" ]]; then
    warn "База ${DB_NAME} уже существует — пропускаю создание"
else
    sudo -u postgres createdb -O "$DB_USER" -E UTF8 --locale=C.UTF-8 -T template0 "$DB_NAME"
fi

# Роль не должна иметь прав на создание чего-либо в других базах
sudo -u postgres psql -q -d "$DB_NAME" -c \
    "REVOKE ALL ON SCHEMA public FROM PUBLIC;" \
    -c "GRANT ALL ON SCHEMA public TO ${DB_USER};"

# ── postgresql.conf ──────────────────────────────────────────────────────────

info "Настраиваю listen_addresses и логирование"

CONF_D="${PG_CONF_DIR}/conf.d"
mkdir -p "$CONF_D"

# Отдельный файл вместо правки postgresql.conf — переживает обновления пакета
cat > "${CONF_D}/10-ownnetbot.conf" <<CONF
# Управляется deploy/vps2-db/setup-db.sh — не редактировать вручную

# Слушаем только localhost и приватную сеть. Публичный интерфейс не трогаем:
# требование безопасности, банк проверяет открытые порты перед подключением.
listen_addresses = 'localhost,${DB_BIND_IP}'
port = 5432

max_connections = 100
shared_buffers = 256MB
work_mem = 8MB
maintenance_work_mem = 128MB

# Все соединения только по TLS: в pg_hba.conf стоит hostssl, незашифрованные
# отвергаются. Сертификат берётся из умолчаний пакета Debian/Ubuntu —
# самоподписанный ssl-cert-snakeoil. Это даёт шифрование канала, но не
# аутентификацию сервера: клиент его не проверяет. Для приватной сети между
# двумя своими машинами достаточно; при выносе базы за её пределы сюда
# понадобятся собственные ssl_cert_file/ssl_key_file и sslmode=verify-full
# на стороне клиента.
ssl = on

# Логи: минимум год хранения — требование для платёжной инфраструктуры.
# Ротацию делает сам PostgreSQL, суффикс по дате.
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_rotation_age = 1d
log_rotation_size = 0
log_truncate_on_rotation = off
log_min_duration_statement = 1000
log_connections = on
log_disconnections = on
log_line_prefix = '%m [%p] %q%u@%d '
timezone = 'UTC'
CONF

# Проверка привязана к началу строки: без якоря grep нашёл бы и закомментированный
# `#include_dir = 'conf.d'`, решил бы, что подключать нечего, и весь файл выше
# молча не применился бы — а падения при этом не будет, база просто останется
# слушать localhost.
grep -Eq "^[[:space:]]*include_dir[[:space:]]*=[[:space:]]*'conf\.d'" \
    "${PG_CONF_DIR}/postgresql.conf" \
    || echo "include_dir = 'conf.d'" >> "${PG_CONF_DIR}/postgresql.conf"

# ── pg_hba.conf ──────────────────────────────────────────────────────────────

info "Настраиваю pg_hba.conf"

HBA="${PG_CONF_DIR}/pg_hba.conf"
MARK_START="# >>> ownnetbot >>>"
MARK_END="# <<< ownnetbot <<<"

# Убираем прошлый блок, если скрипт запускается повторно
if grep -qF "$MARK_START" "$HBA"; then
    sed -i "/${MARK_START}/,/${MARK_END}/d" "$HBA"
fi

cp "$HBA" "${HBA}.bak.$(date +%Y%m%d_%H%M%S)"

cat >> "$HBA" <<HBA_BLOCK
${MARK_START}
# Доступ только с сервера приложения по приватной сети, только scram-sha-256.
# hostssl (не host) — незашифрованные соединения отвергаются.
hostssl ${DB_NAME}   ${DB_USER}   ${APP_IP}/32   scram-sha-256
${MARK_END}
HBA_BLOCK

# scram-sha-256 вместо md5: md5 считается устаревшим и слабым
grep -q "^password_encryption" "${CONF_D}/10-ownnetbot.conf" \
    || echo "password_encryption = scram-sha-256" >> "${CONF_D}/10-ownnetbot.conf"

# ── Firewall ─────────────────────────────────────────────────────────────────

info "Настраиваю firewall"

# ВНИМАНИЕ: reset стирает ВСЕ существующие правила ufw, а не только наши.
# Это единственное место, где скрипт не идемпотентен по-настоящему: если
# на сервере есть правила, добавленные помимо него, при повторном запуске
# они будут потеряны. Проверьте `ufw status numbered` перед перезапуском.
apt-get install -y ufw >/dev/null
if ufw status 2>/dev/null | grep -q '^Status: active'; then
    warn "ufw уже активен — правила будут сброшены и заданы заново"
    ufw status numbered || true
fi
ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow from "${APP_IP}" to any port 5432 proto tcp >/dev/null
ufw --force enable >/dev/null

warn "Порт 5432 открыт ТОЛЬКО для ${APP_IP}. Наружу он закрыт — это обязательное"
warn "требование: платёжные провайдеры сканируют IP перед подключением."

# ── Перезапуск и проверка ────────────────────────────────────────────────────

info "Перезапускаю PostgreSQL"
systemctl restart postgresql
sleep 2

systemctl is-active --quiet postgresql || die "PostgreSQL не запустился, смотрите: journalctl -u postgresql -n 50"

# Проверяем, а не просто печатаем: если conf.d по какой-то причине не подключился,
# база останется на localhost, скрипт отрапортует «Готово», а обнаружится это
# только на VPS-1 сообщением «PostgreSQL недоступен» с четырьмя ложными версиями
# причины. Лучше упасть здесь, где видно настоящую.
LISTEN="$(sudo -u postgres psql -tAc 'SHOW listen_addresses')"
if [[ ",${LISTEN// /}," != *",${DB_BIND_IP},"* ]]; then
    die "PostgreSQL слушает '${LISTEN}', адреса ${DB_BIND_IP} среди них нет.
Проверьте, что ${PG_CONF_DIR}/postgresql.conf содержит активную строку
include_dir = 'conf.d' и что файл ${CONF_D}/10-ownnetbot.conf на месте."
fi
info "listen_addresses = ${LISTEN}"

HBA_OK="$(sudo -u postgres psql -tAc \
    "SELECT count(*) FROM pg_hba_file_rules WHERE '${DB_USER}' = ANY(user_name) AND error IS NULL")"
if [[ "$HBA_OK" == "0" ]]; then
    die "Правило для роли ${DB_USER} не попало в pg_hba.conf или содержит ошибку. Смотрите:
sudo -u postgres psql -c 'SELECT * FROM pg_hba_file_rules WHERE error IS NOT NULL'"
fi
info "Правило pg_hba для ${DB_USER} принято"

# ── Итог ─────────────────────────────────────────────────────────────────────

echo
echo "${GREEN}${BOLD}Готово.${RESET}"
echo
echo "${BOLD}Строки для .env на VPS-1:${RESET}"
echo "  DB_HOST=${DB_BIND_IP}"
echo "  DB_PORT=5432"
echo "  DB_NAME=${DB_NAME}"
echo "  DB_USER=${DB_USER}"
echo "  DB_PASSWORD=${DB_PASSWORD}"
echo
warn "Сохраните пароль сейчас — повторно он нигде не отображается."
echo
echo "${BOLD}Дальше:${RESET}"
echo "  1. Настройте бэкапы:  sudo bash backup/install-backup.sh"
echo "  2. Переходите к VPS-1: deploy/vps1-app/README.md"
