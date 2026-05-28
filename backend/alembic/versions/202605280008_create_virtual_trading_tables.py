"""create virtual trading tables

Revision ID: 202605280008
Revises: 202605280007
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280008"
down_revision = "202605280007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_currency", sa.Text(), nullable=False, server_default="USDT"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("type IN ('virtual', 'live')", name="ck_portfolios_type"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_portfolios_name_not_blank"),
        sa.CheckConstraint("length(trim(base_currency)) > 0", name="ck_portfolios_base_currency_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_portfolios_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"])
    op.create_index("ix_portfolios_status", "portfolios", ["status"])

    op.create_table(
        "portfolio_balances",
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("available", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("locked", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("available >= 0", name="ck_portfolio_balances_available_non_negative"),
        sa.CheckConstraint("locked >= 0", name="ck_portfolio_balances_locked_non_negative"),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="fk_portfolio_balances_portfolio_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["market_assets.id"],
            name="fk_portfolio_balances_asset_id",
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "asset_id", name="pk_portfolio_balances"),
    )
    op.create_index("ix_portfolio_balances_asset_id", "portfolio_balances", ["asset_id"])

    op.create_table(
        "portfolio_balance_ledger",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delta_available", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("delta_locked", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("ref_type", sa.Text(), nullable=True),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_portfolio_balance_ledger_reason_not_blank"),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="fk_portfolio_balance_ledger_portfolio_id",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["market_assets.id"],
            name="fk_portfolio_balance_ledger_asset_id",
        ),
    )
    op.execute(
        "CREATE INDEX ix_portfolio_balance_ledger_portfolio_time "
        "ON portfolio_balance_ledger (portfolio_id, created_at DESC)"
    )
    op.create_index("ix_portfolio_balance_ledger_asset_id", "portfolio_balance_ledger", ["asset_id"])

    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=True),
        sa.Column("stop_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("time_in_force", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("mode IN ('virtual', 'live')", name="ck_orders_mode"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
        sa.CheckConstraint("order_type IN ('market', 'limit', 'stop', 'take_profit')", name="ck_orders_order_type"),
        sa.CheckConstraint(
            "status IN ('created', 'submitted', 'partially_filled', 'filled', 'cancelled', 'rejected')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="ck_orders_idempotency_key_not_blank"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name="fk_orders_user_id"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], name="fk_orders_portfolio_id"),
        sa.ForeignKeyConstraint(["signal_id"], ["trading_signals.id"], name="fk_orders_signal_id"),
        sa.ForeignKeyConstraint(["exchange_id"], ["market_exchanges.id"], name="fk_orders_exchange_id"),
        sa.ForeignKeyConstraint(["pair_id"], ["market_pairs.id"], name="fk_orders_pair_id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency_key"),
    )
    op.create_index("ix_orders_portfolio_id", "orders", ["portfolio_id"])
    op.create_index("ix_orders_signal_id", "orders", ["signal_id"])
    op.create_index("ix_orders_pair_id", "orders", ["pair_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "order_fills",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee_amount", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("fee_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("liquidity", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("liquidity IN ('maker', 'taker', 'simulated')", name="ck_order_fills_liquidity"),
        sa.CheckConstraint("price > 0", name="ck_order_fills_price_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_order_fills_quantity_positive"),
        sa.CheckConstraint("fee_amount >= 0", name="ck_order_fills_fee_amount_non_negative"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_fills_order_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fee_asset_id"],
            ["market_assets.id"],
            name="fk_order_fills_fee_asset_id",
        ),
    )
    op.create_index("ix_order_fills_order_id", "order_fills", ["order_id"])
    op.create_index("ix_order_fills_fee_asset_id", "order_fills", ["fee_asset_id"])
    op.create_index("ix_order_fills_filled_at", "order_fills", ["filled_at"])

    op.create_table(
        "positions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_avg_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("exit_avg_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("stop_loss", sa.Numeric(38, 18), nullable=True),
        sa.Column(
            "take_profit",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(38, 18), nullable=True, server_default="0"),
        sa.Column("fees_total", sa.Numeric(38, 18), nullable=True, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("mode IN ('virtual', 'live')", name="ck_positions_mode"),
        sa.CheckConstraint("side IN ('long', 'short')", name="ck_positions_side"),
        sa.CheckConstraint("status IN ('open', 'closed', 'liquidated')", name="ck_positions_status"),
        sa.CheckConstraint("quantity > 0", name="ck_positions_quantity_positive"),
        sa.CheckConstraint("entry_avg_price > 0", name="ck_positions_entry_avg_price_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name="fk_positions_user_id"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], name="fk_positions_portfolio_id"),
        sa.ForeignKeyConstraint(["signal_id"], ["trading_signals.id"], name="fk_positions_signal_id"),
        sa.ForeignKeyConstraint(["pair_id"], ["market_pairs.id"], name="fk_positions_pair_id"),
    )
    op.create_index("ix_positions_user_id", "positions", ["user_id"])
    op.create_index("ix_positions_portfolio_id", "positions", ["portfolio_id"])
    op.create_index("ix_positions_signal_id", "positions", ["signal_id"])
    op.create_index("ix_positions_pair_id", "positions", ["pair_id"])
    op.create_index("ix_positions_status", "positions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_positions_status", table_name="positions")
    op.drop_index("ix_positions_pair_id", table_name="positions")
    op.drop_index("ix_positions_signal_id", table_name="positions")
    op.drop_index("ix_positions_portfolio_id", table_name="positions")
    op.drop_index("ix_positions_user_id", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_order_fills_filled_at", table_name="order_fills")
    op.drop_index("ix_order_fills_fee_asset_id", table_name="order_fills")
    op.drop_index("ix_order_fills_order_id", table_name="order_fills")
    op.drop_table("order_fills")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_pair_id", table_name="orders")
    op.drop_index("ix_orders_signal_id", table_name="orders")
    op.drop_index("ix_orders_portfolio_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_portfolio_balance_ledger_asset_id", table_name="portfolio_balance_ledger")
    op.drop_index("ix_portfolio_balance_ledger_portfolio_time", table_name="portfolio_balance_ledger")
    op.drop_table("portfolio_balance_ledger")
    op.drop_index("ix_portfolio_balances_asset_id", table_name="portfolio_balances")
    op.drop_table("portfolio_balances")
    op.drop_index("ix_portfolios_status", table_name="portfolios")
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.drop_table("portfolios")
