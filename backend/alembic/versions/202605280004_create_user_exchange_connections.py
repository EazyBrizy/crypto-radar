"""create user exchange connections

Revision ID: 202605280004
Revises: 202605280003
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280004"
down_revision = "202605280003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_exchange_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False, server_default="spot"),
        sa.Column("key_ref", sa.Text(), nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(label)) > 0", name="ck_user_exchange_connections_label_not_blank"),
        sa.CheckConstraint(
            "length(trim(account_type)) > 0",
            name="ck_user_exchange_connections_account_type_not_blank",
        ),
        sa.CheckConstraint("length(trim(key_ref)) > 0", name="ck_user_exchange_connections_key_ref_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_user_exchange_connections_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["market_exchanges.id"],
            name="fk_user_exchange_connections_exchange_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "exchange_id",
            "label",
            name="uq_user_exchange_connections_user_exchange_label",
        ),
    )
    op.create_index("ix_user_exchange_connections_user_id", "user_exchange_connections", ["user_id"])
    op.create_index("ix_user_exchange_connections_exchange_id", "user_exchange_connections", ["exchange_id"])
    op.create_index("ix_user_exchange_connections_status", "user_exchange_connections", ["status"])


def downgrade() -> None:
    op.drop_index("ix_user_exchange_connections_status", table_name="user_exchange_connections")
    op.drop_index("ix_user_exchange_connections_exchange_id", table_name="user_exchange_connections")
    op.drop_index("ix_user_exchange_connections_user_id", table_name="user_exchange_connections")
    op.drop_table("user_exchange_connections")
