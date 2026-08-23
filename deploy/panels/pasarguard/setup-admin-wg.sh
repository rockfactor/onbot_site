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
# Дополнительно скрипт умеет поднять DNS-резолвер внутри туннеля (спросит
# в диалоге). Он нужен, чтобы панель открывалась по доменному имени с любого
# устройства — подробности в разделе «Резолвер туннеля» ниже.
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
WG_SUBNET="${WG_NET}.0/24"
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

# ── Резолвер туннеля: спрашиваем, но не навязываем ───────────────────────────
# Панель закрыта вайтлистом и отвечает только на ${SERVER_WG_IP}, а сертификат
# выписан на публичное имя. Открывать её надо по имени — по IP браузер упрётся
# в несовпадение сертификата. Значит, имя должно резолвиться в адрес туннеля.
# Либо это делает резолвер на сервере, либо запись в hosts на каждом устройстве
# (на телефоне такой возможности нет).

echo
echo "${BOLD}DNS-резолвер внутри туннеля${RESET}"
echo "Панель отвечает только на ${SERVER_WG_IP}, но сертификат выписан"
echo "на публичное имя, поэтому открывать её надо по имени."
echo "Скрипт может поднять dnsmasq, привязанный строго к ${WG_IF}: имя панели"
echo "он резолвит в ${SERVER_WG_IP}, остальные запросы форвардит наружу."
echo "Отказ — рабочий вариант, но тогда имя придётся прописывать в hosts"
echo "на каждом устройстве вручную, а на телефоне это обычно невозможно."
read -rp "Поднять резолвер? [y/N] " DNS_ANSWER
if [[ "$DNS_ANSWER" =~ ^[Yy]$ ]]; then
    PANEL_DNS="yes"
    read -rp "Доменное имя панели (например own.rockfactor.ru): " PANEL_DOMAIN
    [[ "$PANEL_DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]] \
        || die "Не похоже на доменное имя: ${PANEL_DOMAIN}"
else
    PANEL_DNS="no"
fi

echo
echo "${BOLD}Проверьте:${RESET}"
echo "  Внешний адрес:   ${SERVER_PUBLIC_IP}:${WG_PORT}"
echo "  Подсеть туннеля: ${WG_SUBNET}"
echo "  Сервер получит:  ${SERVER_WG_IP}"
echo "  Устройств:       ${PEER_COUNT}"
if [[ "$PANEL_DNS" == "yes" ]]; then
    echo "  Резолвер:        ${PANEL_DOMAIN} → ${SERVER_WG_IP}, только на ${WG_IF}"
else
    echo "  Резолвер:        не поднимаем, имя панели — через hosts"
fi
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

    # AllowedIPs у клиента: только подсеть туннеля.
    #
    # Публичный адрес сервера сюда класть НЕЛЬЗЯ, хотя соблазн есть — панель
    # открывается по имени, которое резолвится именно в него. По тому же
    # адресу лежит и Endpoint. Клиент строит для каждого префикса из AllowedIPs
    # маршрут в туннель, и в маршрут ${SERVER_PUBLIC_IP}/32 попадают собственные
    # UDP-пакеты WireGuard, адресованные ${SERVER_PUBLIC_IP}:${WG_PORT}: пакет,
    # который должен уйти наружу, чтобы туннель поднялся, отправляется внутрь
    # ещё не поднятого туннеля. Петля — рукопожатия нет, панель не открывается.
    # На Android и iOS такая конфигурация работает, но только потому, что
    # система сама исключает сокет туннеля из его маршрутов; wg-quick
    # и десктопные клиенты этого не делают.
    #
    # Имя панели резолвится в адрес внутри туннеля: либо резолвером на сервере
    # (строка DNS ниже), либо записью в hosts на устройстве.
    #
    # Это split-tunnel: через туннель идёт только ${WG_SUBNET}, остальной
    # трафик устройства — напрямую.
    cat > "${WG_DIR}/clients/device${i}.conf" <<CONF
[Interface]
PrivateKey = ${PEER_PRIV}
Address = ${PEER_IP}/32
CONF

    if [[ "$PANEL_DNS" == "yes" ]]; then
        echo "DNS = ${SERVER_WG_IP}" >> "${WG_DIR}/clients/device${i}.conf"
    fi

    cat >> "${WG_DIR}/clients/device${i}.conf" <<CONF

[Peer]
PublicKey = ${SERVER_PUB}
PresharedKey = ${PEER_PSK}
Endpoint = ${SERVER_PUBLIC_IP}:${WG_PORT}
AllowedIPs = ${WG_SUBNET}
PersistentKeepalive = 25
CONF
    chmod 600 "${WG_DIR}/clients/device${i}.conf"
done

chmod 600 "${WG_DIR}/${WG_IF}.conf"

# ── Обратный путь ────────────────────────────────────────────────────────────
# Раньше здесь включался loose rp_filter (режим 2) на всех интерфейсах: пакет
# приходил через ${WG_IF}, но был адресован публичному IP сервера, и строгая
# проверка обратного пути отбрасывала его как поддельный.
#
# После того как публичный адрес убран из AllowedIPs, такого пакета больше нет:
# трафик к панели идёт на ${SERVER_WG_IP} с адреса ${WG_NET}.x, обратный
# маршрут для него — тот же ${WG_IF}, строгая проверка проходит. Ослаблять
# защиту от спуфинга на всём хосте больше незачем, поэтому старый файл убираем.

if [[ -f /etc/sysctl.d/99-panel-admin-wg.conf ]]; then
    info "Убираю больше не нужный loose rp_filter"
    rm -f /etc/sysctl.d/99-panel-admin-wg.conf
    sysctl -q --system
fi

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

# ── Резолвер туннеля ─────────────────────────────────────────────────────────
# dnsmasq отдаёт имя панели как ${SERVER_WG_IP} и форвардит всё остальное.
# Так панель открывается по имени с любого устройства — сертификат сходится,
# а запрос приходит с адреса ${WG_NET}.x, который стоит в вайтлисте nginx.
#
# КРИТИЧНО: резолвер обязан слушать только туннель. Открытый в интернет DNS
# сканеры находят за часы и используют для амплификации — короткий запрос
# с подменённым адресом источника превращается в большой ответ в сторону
# жертвы, то есть сервер становится оружием в чужой атаке. Отсюда три меры:
# interface= + bind-dynamic (сокет только на адресе туннеля, причём
# bind-dynamic переживает пересоздание интерфейса, в отличие
# от bind-interfaces), except-interface=lo и правило ufw, привязанное
# к интерфейсу, а не просто к порту 53.

if [[ "$PANEL_DNS" == "yes" ]]; then
    info "Поднимаю DNS-резолвер на ${WG_IF}"

    # Конфигурацию кладём ДО установки пакета: свежепоставленный dnsmasq
    # стартует на всех интерфейсах, а нам этого не нужно даже на секунду.
    mkdir -p /etc/dnsmasq.d
    cat > "/etc/dnsmasq.d/${WG_IF}-panel.conf" <<DNSMASQ
# Резолвер админского туннеля
# Создан setup-admin-wg.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)

# Слушаем строго туннель. Публичный интерфейс — никогда: открытый резолвер
# используют для DNS-амплификации.
interface=${WG_IF}
bind-dynamic
except-interface=lo

# Имя панели — внутрь туннеля. Сертификат выписан на это имя, поэтому
# открывать панель по IP нельзя.
address=/${PANEL_DOMAIN}/${SERVER_WG_IP}

# Остальное форвардим наружу. no-resolv обязателен: в /etc/resolv.conf
# может стоять локальный stub systemd-resolved, и запрос вернётся в петлю.
no-resolv
server=1.1.1.1
server=8.8.8.8
domain-needed
bogus-priv
DNSMASQ

    apt-get install -y dnsmasq >/dev/null
    systemctl enable dnsmasq >/dev/null 2>&1 || true
    systemctl restart dnsmasq
    sleep 1
    systemctl is-active --quiet dnsmasq \
        || die "dnsmasq не поднялся: journalctl -u dnsmasq -n 30"

    if command -v ufw >/dev/null; then
        # Правило привязано к интерфейсу. "ufw allow 53/udp" открыл бы
        # резолвер всему интернету — ровно то, чего делать нельзя.
        ufw allow in on "${WG_IF}" to any port 53 proto udp >/dev/null 2>&1 || true
        ufw allow in on "${WG_IF}" to any port 53 proto tcp >/dev/null 2>&1 || true
    fi

    # Проверяем, что сокет не висит на 0.0.0.0 или на публичном адресе.
    BAD_BIND="$(ss -uln 2>/dev/null | awk '$5 ~ /:53$/ { print $5 }' \
        | grep -E "^(0\.0\.0\.0|\*|\[::\]|${SERVER_PUBLIC_IP//./\\.}):53$" || true)"
    if [[ -n "$BAD_BIND" ]]; then
        warn "Резолвер слушает не только туннель: ${BAD_BIND}"
        warn "Разберитесь до того, как открывать доступ: проверьте"
        warn "/etc/dnsmasq.conf и остальные файлы в /etc/dnsmasq.d/"
    else
        info "Резолвер слушает только ${SERVER_WG_IP}:53"
    fi
elif [[ -f "/etc/dnsmasq.d/${WG_IF}-panel.conf" ]]; then
    # Резолвер поднимали в прошлый запуск, сейчас отказались: конфигурации
    # устройств уже без строки DNS, а dnsmasq всё ещё отвечает в туннеле.
    warn "Остался прежний резолвер: /etc/dnsmasq.d/${WG_IF}-panel.conf"
    warn "Если он больше не нужен: rm этот файл и systemctl stop dnsmasq"
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
echo "${BOLD}Как открывать панель:${RESET}"
if [[ "$PANEL_DNS" == "yes" ]]; then
    echo "  Подключите туннель и откройте https://${PANEL_DOMAIN}/"
    echo "  Имя резолвится в ${SERVER_WG_IP} резолвером на этом сервере,"
    echo "  в конфигурациях устройств для этого стоит DNS = ${SERVER_WG_IP}."
    echo "  Проверка с подключённого устройства:"
    echo "    dig +short ${PANEL_DOMAIN}   # ожидаем ${SERVER_WG_IP}"
else
    echo "  Панель отвечает только на ${SERVER_WG_IP}, а сертификат выписан"
    echo "  на публичное имя — по IP браузер покажет ошибку сертификата."
    echo "  Резолвер вы не поднимали, поэтому на каждом устройстве добавьте"
    echo "  в hosts строку вида:"
    echo "    ${SERVER_WG_IP}  имя.панели"
    echo "  На телефоне это обычно невозможно — тогда перезапустите скрипт"
    echo "  и согласитесь поднять резолвер."
fi
echo
warn "Файлы содержат приватные ключи. Передавайте только по scp или QR,"
warn "не через мессенджеры и не по почте."
