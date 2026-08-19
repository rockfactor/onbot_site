#!/usr/bin/env bash
#
# Ежедневный pg_dump с ротацией. Ставится на VPS-2 после setup-db.sh.
#
#   sudo bash install-backup.sh
#
# Бэкап живёт на стороне БД намеренно: бот не должен отвечать за
# сохранность чужого сервера, а pg_dump локально не нагружает сеть.
#
set -euo pipefail

GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; RESET=$'\e[0m'
info() { echo "${GREEN}==>${RESET} $*"; }
warn() { echo "${YELLOW}!!${RESET}  $*"; }
die()  { echo "${RED}ОШИБКА:${RESET} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускайте через sudo"

read -rp "Имя базы для бэкапа [vpnbot]: " DB_NAME
DB_NAME="${DB_NAME:-vpnbot}"

read -rp "Сколько дней хранить бэкапы [30]: " KEEP_DAYS
KEEP_DAYS="${KEEP_DAYS:-30}"

read -rp "Каталог для бэкапов [/var/backups/postgresql]: " BACKUP_DIR
BACKUP_DIR="${BACKUP_DIR:-/var/backups/postgresql}"

info "Создаю каталог ${BACKUP_DIR}"
mkdir -p "$BACKUP_DIR"
chown postgres:postgres "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

info "Устанавливаю скрипт бэкапа"
cat > /usr/local/bin/ownnetbot-pg-backup <<SCRIPT
#!/usr/bin/env bash
# Управляется deploy/vps2-db/backup/install-backup.sh
set -euo pipefail

DB_NAME="${DB_NAME}"
BACKUP_DIR="${BACKUP_DIR}"
KEEP_DAYS=${KEEP_DAYS}

STAMP="\$(date -u +%Y%m%d_%H%M%S)"
FILE="\${BACKUP_DIR}/\${DB_NAME}_\${STAMP}.dump"

# Формат custom (-Fc): сжатый, позволяет восстановить отдельные таблицы через pg_restore
pg_dump -Fc -d "\$DB_NAME" -f "\$FILE"
chmod 600 "\$FILE"

# Проверяем, что дамп читается — битый бэкап хуже отсутствующего
if ! pg_restore --list "\$FILE" >/dev/null 2>&1; then
    logger -t ownnetbot-backup "ОШИБКА: дамп \$FILE повреждён"
    rm -f "\$FILE"
    exit 1
fi

find "\$BACKUP_DIR" -name "\${DB_NAME}_*.dump" -type f -mtime +\${KEEP_DAYS} -delete

SIZE="\$(du -h "\$FILE" | cut -f1)"
logger -t ownnetbot-backup "Бэкап создан: \$FILE (\$SIZE)"
SCRIPT

chmod 700 /usr/local/bin/ownnetbot-pg-backup

info "Настраиваю systemd timer"

cat > /etc/systemd/system/ownnetbot-backup.service <<'UNIT'
[Unit]
Description=OwnNetBot PostgreSQL backup
After=postgresql.service
Requires=postgresql.service

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/local/bin/ownnetbot-pg-backup
UNIT

cat > /etc/systemd/system/ownnetbot-backup.timer <<'UNIT'
[Unit]
Description=Ежедневный бэкап базы OwnNetBot

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now ownnetbot-backup.timer

info "Пробный запуск"
if systemctl start ownnetbot-backup.service; then
    sleep 2
    ls -lh "$BACKUP_DIR" | tail -3
else
    die "Пробный бэкап не удался, смотрите: journalctl -u ownnetbot-backup -n 30"
fi

echo
echo "${GREEN}Готово.${RESET}"
echo "  Расписание:   ежедневно в 03:00 UTC"
echo "  Каталог:      ${BACKUP_DIR}"
echo "  Хранение:     ${KEEP_DAYS} дней"
echo
echo "Проверка:       systemctl list-timers ownnetbot-backup.timer"
echo "Логи:           journalctl -t ownnetbot-backup"
echo "Восстановление: pg_restore -d ${DB_NAME} --clean /путь/к/файлу.dump"
echo
warn "Бэкапы лежат на том же сервере, что и база. Настройте выгрузку копий"
warn "на внешнее хранилище (S3 Beget) — иначе потеря диска означает потерю всего."
