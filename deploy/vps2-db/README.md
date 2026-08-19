# VPS-2 — сервер базы данных

Ubuntu 24.04, только PostgreSQL 16. Приложение здесь не разворачивается,
репозиторий нужен исключительно ради этих скриптов.

## Что делает `setup-db.sh`

1. Ставит PostgreSQL 16 из репозиториев Ubuntu
2. Создаёт роль и базу; пароль передаёт через временный файл с правами 600,
   а не аргументом команды — аргументы видны всем в `ps aux`
3. Настраивает `listen_addresses` на localhost и приватный IP
4. Добавляет в `pg_hba.conf` строку `hostssl` только для IP сервера приложения
5. Включает `ufw`: 5432 открыт единственному адресу
6. Включает логирование с суточной ротацией

## Запуск

```bash
git clone https://github.com/rockfactor/onbot_site.git /tmp/onbot
cd /tmp/onbot/deploy/vps2-db
sudo bash setup-db.sh
```

Скрипт спросит приватные IP обоих серверов, имя базы, роль и пароль.
Пустой пароль означает автоматическую генерацию — он будет показан в конце
и больше нигде.

Затем бэкапы:

```bash
sudo bash backup/install-backup.sh
```

## Принятые решения

**`hostssl`, а не `host`.** Незашифрованные подключения отвергаются, даже внутри
приватной сети. Приватная сеть провайдера — это общий коммутатор, а не
доверенный периметр.

**`scram-sha-256`, а не `md5`.** MD5-аутентификация в PostgreSQL считается
устаревшей и уязвимой к перебору перехваченных хешей.

**Отдельный файл `conf.d/10-ownnetbot.conf`.** Правки не теряются при обновлении
пакета, в отличие от прямого редактирования `postgresql.conf`.

**Порт 5432 закрыт наружу.** Требование платёжных провайдеров: банк сканирует
IP перед подключением эквайринга и открытый порт БД — повод для отказа.

## Проверка

```bash
# Сервис работает
systemctl status postgresql

# Слушает только нужные адреса
sudo -u postgres psql -tAc 'SHOW listen_addresses'
ss -tlnp | grep 5432

# Firewall пропускает только VPS-1
sudo ufw status numbered
```

Снаружи, с любой посторонней машины, — соединение должно отваливаться
по таймауту:

```bash
nc -zv -w 5 ПУБЛИЧНЫЙ_IP_VPS2 5432
```

## Бэкапы

Ежедневно в 03:00 UTC через systemd timer, формат `custom` (`pg_dump -Fc`).
Каждый дамп проверяется через `pg_restore --list` — повреждённый файл удаляется
и в журнал пишется ошибка, потому что битый бэкап опаснее отсутствующего:
он создаёт ложную уверенность.

```bash
systemctl list-timers ownnetbot-backup.timer
journalctl -t ownnetbot-backup -n 20
ls -lh /var/backups/postgresql/
```

Восстановление:

```bash
sudo -u postgres pg_restore -d vpnbot --clean --if-exists \
    /var/backups/postgresql/vpnbot_20260819_030000.dump
```

Восстановление отдельной таблицы:

```bash
sudo -u postgres pg_restore -d vpnbot --data-only -t user_subscriptions ФАЙЛ.dump
```

**Бэкапы лежат на том же диске, что и база.** Потеря диска означает потерю всего.
Настройте выгрузку копий в S3 Beget — это отдельная задача этапа 2, когда
появятся ключи S3.

## Логи

PostgreSQL пишет в `/var/lib/postgresql/16/main/log/` с суточной ротацией
и без перезаписи старых файлов (`log_truncate_on_rotation = off`). Хранение
не ограничено по времени намеренно: требование к платёжной инфраструктуре —
минимум год.

Если диск начнёт заполняться, удаляйте файлы старше года:

```bash
sudo find /var/lib/postgresql/16/main/log -name 'postgresql-*.log' -mtime +400 -delete
```

## Диагностика

**Приложение не подключается.** Проверьте по порядку:

```bash
# 1. Слушает ли нужный адрес
sudo -u postgres psql -tAc 'SHOW listen_addresses'

# 2. Есть ли правило для IP приложения
sudo grep -A2 'ownnetbot' /etc/postgresql/16/main/pg_hba.conf

# 3. Пропускает ли firewall
sudo ufw status | grep 5432

# 4. Что в логах при попытке подключения
sudo tail -50 /var/lib/postgresql/16/main/log/postgresql-$(date +%F).log
```

Частая причина — приватный IP VPS-1 отличается от того, что указан
в `pg_hba.conf`. Уточните его на VPS-1 командой `ip -4 addr` и, если он
изменился, поправьте строку и выполните `sudo systemctl reload postgresql`.
