"""create risk management tables

Revision ID: 202605280012
Revises: 202605280011
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280012"
down_revision = "202605280011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("instrument_type", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "blockers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result_snapshot",
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
        sa.CheckConstraint("mode IN ('virtual', 'real')", name="ck_risk_decisions_mode"),
        sa.CheckConstraint(
            "instrument_type IN ('spot', 'futures', 'virtual')",
            name="ck_risk_decisions_instrument_type",
        ),
        sa.CheckConstraint(
            "stage IN ('preview', 'pre_execution', 'post_execution', 'confirm')",
            name="ck_risk_decisions_stage",
        ),
        sa.CheckConstraint("status IN ('passed', 'warning', 'failed')", name="ck_risk_decisions_status"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_risk_decisions_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["trading_signals.id"],
            name="fk_risk_decisions_signal_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="fk_risk_decisions_portfolio_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_risk_decisions_order_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            name="fk_risk_decisions_position_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_risk_decisions_user_id", "risk_decisions", ["user_id"])
    op.create_index("ix_risk_decisions_signal_id", "risk_decisions", ["signal_id"])
    op.create_index("ix_risk_decisions_portfolio_id", "risk_decisions", ["portfolio_id"])
    op.create_index("ix_risk_decisions_order_id", "risk_decisions", ["order_id"])
    op.create_index("ix_risk_decisions_position_id", "risk_decisions", ["position_id"])
    op.execute("CREATE INDEX idx_risk_decisions_user_time ON risk_decisions (user_id, created_at DESC)")
    op.execute("CREATE INDEX idx_risk_decisions_signal_time ON risk_decisions (signal_id, created_at DESC)")
    op.execute("CREATE INDEX idx_risk_decisions_status_time ON risk_decisions (status, created_at DESC)")
    op.execute("CREATE INDEX idx_risk_decisions_position_time ON risk_decisions (position_id, created_at DESC)")

    op.create_table(
        "position_risk_snapshots",
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("risk_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("risk_amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("risk_percent", sa.Numeric(18, 8), nullable=False),
        sa.Column("adjusted_risk_amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("rr", sa.Numeric(18, 8), nullable=True),
        sa.Column("leverage", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("margin_mode", sa.Text(), nullable=False, server_default=sa.text("'spot'")),
        sa.Column("liquidation_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("liquidation_buffer_percent", sa.Numeric(18, 8), nullable=True),
        sa.Column("correlation_group", sa.Text(), nullable=True),
        sa.Column("strategy_multiplier", sa.Numeric(18, 8), nullable=False),
        sa.Column("signal_multiplier", sa.Numeric(18, 8), nullable=False),
        sa.Column("fee_estimate", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column("slippage_estimate", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column("funding_buffer", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "risk_amount >= 0",
            name="ck_position_risk_snapshots_risk_amount_non_negative",
        ),
        sa.CheckConstraint(
            "risk_percent >= 0",
            name="ck_position_risk_snapshots_risk_percent_non_negative",
        ),
        sa.CheckConstraint(
            "adjusted_risk_amount >= 0",
            name="ck_position_risk_snapshots_adjusted_risk_amount_non_negative",
        ),
        sa.CheckConstraint("rr IS NULL OR rr >= 0", name="ck_position_risk_snapshots_rr_non_negative"),
        sa.CheckConstraint("leverage >= 1", name="ck_position_risk_snapshots_leverage_positive"),
        sa.CheckConstraint(
            "margin_mode IN ('spot', 'isolated', 'cross', 'unknown')",
            name="ck_position_risk_snapshots_margin_mode",
        ),
        sa.CheckConstraint(
            "liquidation_price IS NULL OR liquidation_price > 0",
            name="ck_position_risk_snapshots_liquidation_price_positive",
        ),
        sa.CheckConstraint(
            "liquidation_buffer_percent IS NULL OR liquidation_buffer_percent >= 0",
            name="ck_position_risk_snapshots_liquidation_buffer_non_negative",
        ),
        sa.CheckConstraint(
            "strategy_multiplier >= 0",
            name="ck_position_risk_snapshots_strategy_multiplier_non_negative",
        ),
        sa.CheckConstraint(
            "signal_multiplier >= 0",
            name="ck_position_risk_snapshots_signal_multiplier_non_negative",
        ),
        sa.CheckConstraint(
            "fee_estimate >= 0",
            name="ck_position_risk_snapshots_fee_estimate_non_negative",
        ),
        sa.CheckConstraint(
            "slippage_estimate >= 0",
            name="ck_position_risk_snapshots_slippage_estimate_non_negative",
        ),
        sa.CheckConstraint(
            "funding_buffer >= 0",
            name="ck_position_risk_snapshots_funding_buffer_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            name="fk_position_risk_snapshots_position_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["risk_decision_id"],
            ["risk_decisions.id"],
            name="fk_position_risk_snapshots_risk_decision_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("position_id", name="pk_position_risk_snapshots"),
    )
    op.create_index(
        "ix_position_risk_snapshots_risk_decision_id",
        "position_risk_snapshots",
        ["risk_decision_id"],
    )

    op.create_table(
        "exchange_instrument_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("min_order_size", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_order_size", sa.Numeric(38, 18), nullable=True),
        sa.Column("min_notional", sa.Numeric(38, 18), nullable=True),
        sa.Column("qty_step", sa.Numeric(38, 18), nullable=True),
        sa.Column("tick_size", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_leverage", sa.Integer(), nullable=True),
        sa.Column("funding_interval_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'exchange'")),
        sa.Column(
            "fetched_at",
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
        sa.CheckConstraint(
            "length(trim(symbol)) > 0",
            name="ck_exchange_instrument_rules_symbol_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(category)) > 0",
            name="ck_exchange_instrument_rules_category_not_blank",
        ),
        sa.CheckConstraint(
            "min_order_size IS NULL OR min_order_size >= 0",
            name="ck_exchange_instrument_rules_min_order_size_non_negative",
        ),
        sa.CheckConstraint(
            "max_order_size IS NULL OR max_order_size >= 0",
            name="ck_exchange_instrument_rules_max_order_size_non_negative",
        ),
        sa.CheckConstraint(
            "min_notional IS NULL OR min_notional >= 0",
            name="ck_exchange_instrument_rules_min_notional_non_negative",
        ),
        sa.CheckConstraint(
            "qty_step IS NULL OR qty_step > 0",
            name="ck_exchange_instrument_rules_qty_step_positive",
        ),
        sa.CheckConstraint(
            "tick_size IS NULL OR tick_size > 0",
            name="ck_exchange_instrument_rules_tick_size_positive",
        ),
        sa.CheckConstraint(
            "max_leverage IS NULL OR max_leverage >= 1",
            name="ck_exchange_instrument_rules_max_leverage_positive",
        ),
        sa.CheckConstraint(
            "funding_interval_minutes IS NULL OR funding_interval_minutes >= 0",
            name="ck_exchange_instrument_rules_funding_interval_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["market_exchanges.id"],
            name="fk_exchange_instrument_rules_exchange_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"],
            ["market_pairs.id"],
            name="fk_exchange_instrument_rules_pair_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "exchange_id",
            "category",
            "symbol",
            name="uq_exchange_instrument_rules_exchange_category_symbol",
        ),
    )
    op.create_index("ix_exchange_instrument_rules_exchange_id", "exchange_instrument_rules", ["exchange_id"])
    op.create_index("ix_exchange_instrument_rules_pair_id", "exchange_instrument_rules", ["pair_id"])
    op.create_index(
        "idx_exchange_instrument_rules_pair",
        "exchange_instrument_rules",
        ["pair_id", "category"],
    )

    op.create_table(
        "asset_risk_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_code", sa.Text(), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
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
        sa.CheckConstraint(
            "length(trim(group_code)) > 0",
            name="ck_asset_risk_groups_group_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(group_name)) > 0",
            name="ck_asset_risk_groups_group_name_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["market_assets.id"],
            name="fk_asset_risk_groups_asset_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("asset_id", "group_code", name="uq_asset_risk_groups_asset_group"),
    )
    op.create_index("ix_asset_risk_groups_asset_id", "asset_risk_groups", ["asset_id"])
    op.create_index("idx_asset_risk_groups_group_code", "asset_risk_groups", ["group_code"])
    op.create_index(
        "uq_asset_risk_groups_primary_asset",
        "asset_risk_groups",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "risk_protection_state",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'normal'")),
        sa.Column("loss_streak", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_loss_amount", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column("weekly_loss_amount", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weekly_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_timezone", sa.Text(), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("peak_equity", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column("current_equity", sa.Numeric(38, 18), nullable=False, server_default=sa.text("0")),
        sa.Column("adaptive_multiplier", sa.Numeric(18, 8), nullable=False, server_default=sa.text("1")),
        sa.Column("reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('normal', 'reduced', 'virtual_only', 'blocked')",
            name="ck_risk_protection_state_state",
        ),
        sa.CheckConstraint(
            "loss_streak >= 0",
            name="ck_risk_protection_state_loss_streak_non_negative",
        ),
        sa.CheckConstraint(
            "daily_loss_amount >= 0",
            name="ck_risk_protection_state_daily_loss_non_negative",
        ),
        sa.CheckConstraint(
            "weekly_loss_amount >= 0",
            name="ck_risk_protection_state_weekly_loss_non_negative",
        ),
        sa.CheckConstraint(
            "peak_equity >= 0",
            name="ck_risk_protection_state_peak_equity_non_negative",
        ),
        sa.CheckConstraint(
            "current_equity >= 0",
            name="ck_risk_protection_state_current_equity_non_negative",
        ),
        sa.CheckConstraint(
            "adaptive_multiplier >= 0",
            name="ck_risk_protection_state_adaptive_multiplier_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_risk_protection_state_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_risk_protection_state"),
    )


def downgrade() -> None:
    op.drop_table("risk_protection_state")

    op.drop_index("uq_asset_risk_groups_primary_asset", table_name="asset_risk_groups")
    op.drop_index("idx_asset_risk_groups_group_code", table_name="asset_risk_groups")
    op.drop_index("ix_asset_risk_groups_asset_id", table_name="asset_risk_groups")
    op.drop_table("asset_risk_groups")

    op.drop_index("idx_exchange_instrument_rules_pair", table_name="exchange_instrument_rules")
    op.drop_index("ix_exchange_instrument_rules_pair_id", table_name="exchange_instrument_rules")
    op.drop_index("ix_exchange_instrument_rules_exchange_id", table_name="exchange_instrument_rules")
    op.drop_table("exchange_instrument_rules")

    op.drop_index(
        "ix_position_risk_snapshots_risk_decision_id",
        table_name="position_risk_snapshots",
    )
    op.drop_table("position_risk_snapshots")

    op.execute("DROP INDEX IF EXISTS idx_risk_decisions_position_time")
    op.execute("DROP INDEX IF EXISTS idx_risk_decisions_status_time")
    op.execute("DROP INDEX IF EXISTS idx_risk_decisions_signal_time")
    op.execute("DROP INDEX IF EXISTS idx_risk_decisions_user_time")
    op.drop_index("ix_risk_decisions_position_id", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_order_id", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_portfolio_id", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_signal_id", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_user_id", table_name="risk_decisions")
    op.drop_table("risk_decisions")
