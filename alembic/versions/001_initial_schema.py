"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-08-11

"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('user_id',    sa.BigInteger(), primary_key=True),
        sa.Column('username',   sa.Text(),        nullable=True),
        sa.Column('first_name', sa.Text(),        nullable=True),
        sa.Column('last_name',  sa.Text(),        nullable=True),
        sa.Column('first_start',sa.Boolean(),     server_default='true', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )

    # ── orders ───────────────────────────────────────────────────────────────
    op.create_table(
        'orders',
        sa.Column('id',                sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('user_id',           sa.BigInteger(), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('username',          sa.Text(),  nullable=True),
        sa.Column('first_name',        sa.Text(),  nullable=True),
        sa.Column('last_name',         sa.Text(),  nullable=True),
        sa.Column('subscription_type', sa.Text(),  nullable=False),
        sa.Column('amount',            sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status',            sa.Text(),  nullable=False, server_default='pending'),
        sa.Column('subscription_link', sa.Text(),  nullable=True),
        sa.Column('config_file_id',    sa.Text(),  nullable=True),
        sa.Column('created_at',        sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_orders_user_id', 'orders', ['user_id'])
    op.create_index('ix_orders_status',  'orders', ['status'])

    # ── user_subscriptions ───────────────────────────────────────────────────
    op.create_table(
        'user_subscriptions',
        sa.Column('id',                sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('user_id',           sa.BigInteger(), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('username',          sa.Text(),    nullable=True),
        sa.Column('first_name',        sa.Text(),    nullable=True),
        sa.Column('last_name',         sa.Text(),    nullable=True),
        sa.Column('subscription_type', sa.Text(),    nullable=False),
        sa.Column('subscription_link', sa.Text(),    nullable=True),
        sa.Column('config_file_id',    sa.Text(),    nullable=True),
        sa.Column('is_active',         sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('expires_at',        sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('notified_expiry',   sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at',        sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_usub_user_id',   'user_subscriptions', ['user_id'])
    op.create_index('ix_usub_is_active', 'user_subscriptions', ['is_active'])
    op.create_index('ix_usub_expires_at','user_subscriptions', ['expires_at'])

    # ── used_tests ───────────────────────────────────────────────────────────
    op.create_table(
        'used_tests',
        sa.Column('id',        sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('user_id',   sa.BigInteger(), sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('username',  sa.Text(),       nullable=True),
        sa.Column('test_type', sa.Text(),       nullable=False),
        sa.Column('used_at',   sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.UniqueConstraint('user_id', 'test_type', name='uq_used_tests_user_type'),
    )


def downgrade() -> None:
    op.drop_table('used_tests')
    op.drop_table('user_subscriptions')
    op.drop_table('orders')
    op.drop_table('users')
