"""vpn_nodes

Revision ID: 002
Revises: 001
Create Date: 2026-08-24

Таблица VPN-нод: где именно выдаётся конфигурация клиенту.

Принцип из README: добавление ноды — это INSERT в БД, а не правка кода.
Одно исключение, сделанное сознательно: учётные данные панели здесь
не хранятся. В таблице лежит только `credentials_key` — имя набора
переменных в .env (AWG -> AWG_API_USER/AWG_API_PASSWORD,
PASARGUARD -> PASARGUARD_API_KEY). Причина: база уезжает в резервные копии
и на VPS-2, а пароль от панели даёт доступ к приватным ключам всех клиентов
сервиса. Разделение носителей здесь дороже удобства.

Практически это значит: вторая нода на уже известной панели — чистый INSERT;
панель нового типа — INSERT плюс один набор переменных в .env.

Колонки `user_subscriptions.node_id` и `panel_client_id` появятся отдельной
миграцией вместе с интеграцией выдачи в бота: их форма зависит от того,
будет ли строка подписки одна на все устройства тарифа или по одной
на устройство, а это решается при переводе выдачи на автоматику.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vpn_nodes',
        sa.Column('id',              sa.BigInteger(), primary_key=True, autoincrement=True),

        # Человекочитаемое имя ноды: 'ge01awg-awg0'. Уникально — по нему
        # нода ищется в логах и в админке.
        sa.Column('name',            sa.Text(),  nullable=False, unique=True),

        # Какой адаптер обслуживает ноду. Значение выбирает класс в vpn_api/.
        sa.Column('panel_type',      sa.Text(),  nullable=False),

        # Продуктовая линейка: под какой тариф отдаётся эта нода.
        sa.Column('product',         sa.Text(),  nullable=False),

        # Базовый URL панели, всегда https и всегда по доменному имени —
        # сертификат выписан на имя, а не на адрес.
        sa.Column('api_url',         sa.Text(),  nullable=False),

        # Имя набора переменных с учётными данными в .env. См. докстринг.
        sa.Column('credentials_key', sa.Text(),  nullable=False),

        # Идентификатор интерфейса внутри панели: у AWG это id сервера
        # из GET /api/servers. У панелей без такого понятия — NULL.
        sa.Column('panel_server_id', sa.Text(),  nullable=True),

        # Адрес, который должен попасть клиенту в конфигурацию, — 'домен:порт'.
        # Панель подставляет туда свой публичный IP, а нам нужен домен: при
        # блокировке адреса переезд решается A-записью, без перевыпуска
        # конфигураций всем активным подписчикам.
        sa.Column('client_endpoint', sa.Text(),  nullable=True),

        # Общие параметры обфускации AmneziaWG (S1-S4, H1-H4) — те, с которыми
        # интерфейс был создан. Хранятся, чтобы знать, какой интерфейс чем
        # настроен, и уметь воспроизвести конфигурацию при восстановлении.
        # Менять после выдачи первого конфига нельзя: отвалятся все клиенты.
        sa.Column('obfuscation',     postgresql.JSONB(), nullable=True),

        # Два независимых флага, и это не избыточность, а механика ротации
        # обфускации: интерфейс со скомпрометированным профилем перестаёт
        # принимать новых клиентов (accepts_new = false), но продолжает
        # обслуживать выданных, пока у них не истекут подписки
        # (is_active = true). Один флаг такое состояние не выражает.
        sa.Column('is_active',       sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('accepts_new',     sa.Boolean(), nullable=False, server_default='true'),

        # Для будущего роутера: меньше значение — выше приоритет выдачи.
        sa.Column('priority',        sa.Integer(), nullable=False, server_default='100'),

        # Потолок клиентов на ноде. NULL — без ограничения.
        sa.Column('max_clients',     sa.Integer(), nullable=True),

        # Страна выхода трафика. Нужна и для витрины, и для будущей
        # geo-маршрутизации; для российских нод сразу видно, что зарубежные
        # сервисы через них не открываются.
        sa.Column('country',         sa.Text(),    nullable=True),

        sa.Column('created_at',      sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',      sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),

        # Ограничения на уровне БД, а не только в коде: нода с опечаткой
        # в panel_type не должна попасть в таблицу вообще — иначе выдача
        # упадёт уже в рантайме, на живом клиенте.
        sa.CheckConstraint(
            "panel_type IN ('amneziawg', 'pasarguard')",
            name='ck_vpn_nodes_panel_type',
        ),
        sa.CheckConstraint(
            "product IN ('awg', 'vless')",
            name='ck_vpn_nodes_product',
        ),
        sa.CheckConstraint(
            "api_url LIKE 'https://%'",
            name='ck_vpn_nodes_api_url_https',
        ),
        sa.CheckConstraint(
            'max_clients IS NULL OR max_clients > 0',
            name='ck_vpn_nodes_max_clients',
        ),
    )

    # Основной запрос выдачи: «дай ноды под этот продукт, куда можно селить
    # новых, по приоритету». Индекс частичный — строки, не принимающие
    # новых клиентов, в него не попадают.
    op.create_index(
        'ix_vpn_nodes_pick',
        'vpn_nodes',
        ['product', 'priority'],
        postgresql_where=sa.text('is_active AND accepts_new'),
    )


def downgrade() -> None:
    op.drop_index('ix_vpn_nodes_pick', table_name='vpn_nodes')
    op.drop_table('vpn_nodes')
