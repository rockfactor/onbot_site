#!/usr/bin/env bash
#
# Админский WireGuard на панельном сервере.
#
#   sudo bash setup-admin-wg.sh
#
# Используется и для PasarGuard, и для AWG-панели.
# ВНИМАНИЕ: на сервере AWG-панели указывайте порт 51900, а не значение
# по умолчанию — панель публикует диапазон 51820-51830/udp под клиентские
# интерфейсы, и туннель на 51830 столкнётся с ним.
#
# Зачем отдельный туннель, а не WireGuard самой панели:
#   1. Кольцевая зависимость. Если доступ идёт через WG, который раздаёт
#      панель, её падение закрывает вход именно тогда, когда надо чинить.
#   2. Смешение периметров. WG панели — продуктовая функция для клиентов;
#      правка клиентского профиля не должна ронять админский доступ.
#   3. Порядок развёртывания. Чтобы поднять WG из панели, надо сначала
#      в неё войти — а входа ещё нет.
#
# Туннель админский, не клиентский: через него ходит только управление.
#
set -euo pipefail

BOLD=$'\e[1m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'
info() { echo "${GREEN}==>${RESET} $*"; }
warn() { echo "${YELLOW}!!${RESET}  $*"; }
die()  { echo "${RED}ОШИБКА:${RESET} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускайте через sudo"

WG_IF="wg-admin"
WG_DIR="/etc/wireguard"
WG_NET="10.10.0"
SERVER_WG_IP="${WG_NET}.1"

echo "${BOLD}Админский WireGuard для доступа к панели${RESET}"
echo

read -rp "Публичный IP этого сервера [автоопределение]: " SERVER_PUBLIC_IP
if [[ -z "$SERVER_PUBLIC_IP" ]]; then
    SERVER_PUBLIC_IP="$(curl -s --max-time 10 https://api.ipify.org || true)"
    [[ -n "$SERVER_PUBLIC_IP" ]] || die "Не удалось определить IP, укажите вручную"
    info "Определён: ${SERVER_PUBLIC_IP}"
fi

read -rp "Порт WireGuard [51830]: " WG_PORT
WG_PORT="${WG_PORT:-51830}"

read -rp "Сколько устройств подключить (ноутбук, телефон...) [2]: " PEER_COUNT
PEER_COUNT="${PEER_COUNT:-2}"
[[ "$PEER_COUNT" =~ ^[0-9]+$ ]] && (( PEER_COUNT >= 1 && PEER_COUNT <= 20 )) \
    || die "Укажите число от 1 до 20"

echo
echo "${BOLD}Проверьте:${RESET}"
echo "  Внешний адрес:   ${SERVER_PUBLIC_IP}:${WG_PORT}"
echo "  Подсеть туннеля: ${WG_NET}.0/24"
echo "  Сервер получит:  ${SERVER_WG_IP}"
echo "  Устройств:       ${PEER_COUNT}"
echo
read -rp "Всё верно? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || die "Отменено"

# ── Установка ────────────────────────────────────────────────────────────────

info "Устанавливаю WireGuard"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y wireguard qrencode curl >/dev/null

mkdir -p "$WG_DIR/clients"
chmod 700 "$WG_DIR" "$WG_DIR/clients"

if [[ -f "${WG_DIR}/${WG_IF}.conf" ]]; then
    warn "Конфигурация уже существует — сохраняю копию"
    cp "${WG_DIR}/${WG_IF}.conf" "${WG_DIR}/${WG_IF}.conf.bak.$(date +%Y%m%d_%H%M%S)"
    systemctl stop "wg-quick@${WG_IF}" 2>/dev/null || true
fi

# ── Ключи сервера ────────────────────────────────────────────────────────────

info "Генерирую ключи"
umask 077
SERVER_PRIV="$(wg genkey)"
SERVER_PUB="$(echo "$SERVER_PRIV" | wg pubkey)"

# ── Конфигурация сервера ─────────────────────────────────────────────────────
# Форвардинг НЕ включаем: туннель нужен только для доступа к самому
# серверу, выпускать через него трафик в интернет не требуется.
# Меньше функций — меньше поверхность атаки.

cat > "${WG_DIR}/${WG_IF}.conf" <<CONF
# Админский туннель к панели
# Создан setup-admin-wg.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)
#
# Только управление. Клиентский трафик через него не ходит.

[Interface]
Address = ${SERVER_WG_IP}/24
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIV}
CONF

# ── Клиенты ──────────────────────────────────────────────────────────────────

for i in $(seq 1 "$PEER_COUNT"); do
    PEER_IP="${WG_NET}.$((i + 1))"
    PEER_PRIV="$(wg genkey)"
    PEER_PUB="$(echo "$PEER_PRIV" | wg pubkey)"
    PEER_PSK="$(wg genpsk)"

    cat >> "${WG_DIR}/${WG_IF}.conf" <<CONF

[Peer]
# устройство ${i}
PublicKey = ${PEER_PUB}
PresharedKey = ${PEER_PSK}
AllowedIPs = ${PEER_IP}/32
CONF

    # AllowedIPs у клиента: адрес сервера в туннеле плюс его публичный IP.
    # Второе обязательно: панель открывается по доменному имени, которое
    # резолвится в публичный адрес. Без этой строки запрос уйдёт мимо
    # туннеля и nginx увидит домашний IP вместо ${WG_NET}.x.
    # Это split-tunnel: остальной трафик устройства идёт напрямую.
    cat > "${WG_DIR}/clients/device${i}.conf" <<CONF
[Interface]
PrivateKey = ${PEER_PRIV}
Address = ${PEER_IP}/32

[Peer]
PublicKey = ${SERVER_PUB}
PresharedKey = ${PEER_PSK}
Endpoint = ${SERVER_PUBLIC_IP}:${WG_PORT}
AllowedIPs = ${SERVER_WG_IP}/32, ${SERVER_PUBLIC_IP}/32
PersistentKeepalive = 25
CONF
    chmod 600 "${WG_DIR}/clients/device${i}.conf"
done

chmod 600 "${WG_DIR}/${WG_IF}.conf"

# ── Обратный путь ────────────────────────────────────────────────────────────
# Пакет приходит через wg-admin, но адресован публичному IP сервера.
# При строгом rp_filter ядро такой пакет отбросит как поддельный.
# Режим 2 (loose) принимает его, оставаясь защитой от очевидного спуфинга.

info "Настраиваю rp_filter"
cat > /etc/sysctl.d/99-panel-admin-wg.conf <<'SYSCTL'
# Управляется setup-admin-wg.sh
# Loose reverse path filtering: пакет из туннеля, адресованный
# публичному IP того же хоста, должен приниматься.
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2
SYSCTL
sysctl -q --system

# ── Запуск ───────────────────────────────────────────────────────────────────

info "Запускаю ${WG_IF}"
systemctl enable --now "wg-quick@${WG_IF}" >/dev/null 2>&1
sleep 2
systemctl is-active --quiet "wg-quick@${WG_IF}" \
    || die "Туннель не поднялся: journalctl -u wg-quick@${WG_IF} -n 30"

info "Открываю порт ${WG_PORT}/udp"
if command -v ufw >/dev/null; then
    ufw allow "${WG_PORT}/udp" >/dev/null 2>&1 || true
fi

# ── Итог ─────────────────────────────────────────────────────────────────────

echo
echo "${GREEN}${BOLD}Туннель поднят.${RESET}"
wg show "$WG_IF" | head -5
echo
echo "${BOLD}Конфигурации устройств:${RESET} ${WG_DIR}/clients/"
echo
echo "Для телефона — QR-код (наведите камеру в приложении WireGuard):"
echo "  sudo qrencode -t ansiutf8 < ${WG_DIR}/clients/device2.conf"
echo
echo "Для ноутбука — скопировать файл к себе:"
echo "  scp root@${SERVER_PUBLIC_IP}:${WG_DIR}/clients/device1.conf ."
echo
warn "Файлы содержат приватные ключи. Передавайте только по scp или QR,"
warn "не через мессенджеры и не по почте."
