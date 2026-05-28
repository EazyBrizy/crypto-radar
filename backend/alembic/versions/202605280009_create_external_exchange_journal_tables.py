"""create external exchange journal tables

Revision ID: 202605280009
Revises: 202605280008
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280009"
down_revision = "202605280008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_exchange_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_order_id", sa.Text(), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=True),
        sa.Column("price", sa.Numeric(38, 18), nullable=True),
        sa.Column("created_exchange_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_exchange_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(trim(exchange_order_id)) > 0",
            name="ck_external_exchange_orders_exchange_order_id_not_blank",
        ),
        sa.CheckConstraint("length(trim(side)) > 0", name="ck_external_exchange_orders_side_not_blank"),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_external_exchange_orders_quantity_non_negative",
        ),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_external_exchange_orders_price_non_negative"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name="fk_external_exchange_orders_user_id"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["user_exchange_connections.id"],
            name="fk_external_exchange_orders_connection_id",
        ),
        sa.ForeignKeyConstraint(["pair_id"], ["market_pairs.id"], name="fk_external_exchange_orders_pair_id"),
        sa.UniqueConstraint(
            "connection_id",
            "exchange_order_id",
            name="uq_external_exchange_orders_connection_order",
        ),
    )
    op.create_index("ix_external_exchange_orders_user_id", "external_exchange_orders", ["user_id"])
    op.create_index("ix_external_exchange_orders_connection_id", "external_exchange_orders", ["connection_id"])
    op.create_index("ix_external_exchange_orders_pair_id", "external_exchange_orders", ["pair_id"])
    op.create_index("ix_external_exchange_orders_imported_at", "external_exchange_orders", ["imported_at"])

    op.create_table(
        "external_exchange_trades",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_trade_id", sa.Text(), nullable=False),
        sa.Column("exchange_order_id", sa.Text(), nullable=True),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee_amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("fee_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "length(trim(exchange_trade_id)) > 0",
            name="ck_external_exchange_trades_exchange_trade_id_not_blank",
        ),
        sa.CheckConstraint("length(trim(side)) > 0", name="ck_external_exchange_trades_side_not_blank"),
        sa.CheckConstraint("price > 0", name="ck_external_exchange_trades_price_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_external_exchange_trades_quantity_positive"),
        sa.CheckConstraint(
            "fee_amount IS NULL OR fee_amount >= 0",
            name="ck_external_exchange_trades_fee_non_negative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name="fk_external_exchange_trades_user_id"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["user_exchange_connections.id"],
            name="fk_external_exchange_trades_connection_id",
        ),
        sa.ForeignKeyConstraint(["pair_id"], ["market_pairs.id"], name="fk_external_exchange_trades_pair_id"),
        sa.ForeignKeyConstraint(
            ["fee_asset_id"],
            ["market_assets.id"],
            name="fk_external_exchange_trades_fee_asset_id",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "exchange_trade_id",
            name="uq_external_exchange_trades_connection_trade",
        ),
    )
    op.create_index("ix_external_exchange_trades_user_id", "external_exchange_trades", ["user_id"])
    op.create_index("ix_external_exchange_trades_connection_id", "external_exchange_trades", ["connection_id"])
    op.create_index("ix_external_exchange_trades_pair_id", "external_exchange_trades", ["pair_id"])
    op.create_index("ix_external_exchange_trades_fee_asset_id", "external_exchange_trades", ["fee_asset_id"])
    op.create_index("ix_external_exchange_trades_traded_at", "external_exchange_trades", ["traded_at"])
    op.create_index("ix_external_exchange_trades_imported_at", "external_exchange_trades", ["imported_at"])


def downgrade() -> None:
    op.drop_index("ix_external_exchange_trades_imported_at", table_name="external_exchange_trades")
    op.drop_index("ix_external_exchange_trades_traded_at", table_name="external_exchange_trades")
    op.drop_index("ix_external_exchange_trades_fee_asset_id", table_name="external_exchange_trades")
    op.drop_index("ix_external_exchange_trades_pair_id", table_name="external_exchange_trades")
    op.drop_index("ix_external_exchange_trades_connection_id", table_name="external_exchange_trades")
    op.drop_index("ix_external_exchange_trades_user_id", table_name="external_exchange_trades")
    op.drop_table("external_exchange_trades")
    op.drop_index("ix_external_exchange_orders_imported_at", table_name="external_exchange_orders")
    op.drop_index("ix_external_exchange_orders_pair_id", table_name="external_exchange_orders")
    op.drop_index("ix_external_exchange_orders_connection_id", table_name="external_exchange_orders")
    op.drop_index("ix_external_exchange_orders_user_id", table_name="external_exchange_orders")
    op.drop_table("external_exchange_orders")
