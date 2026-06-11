"""create strategy execution eligibility profiles

Revision ID: 202606110001
Revises: 202606060004
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606110001"
down_revision = "202606060004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_execution_eligibility_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("strategy_code", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("symbol_scope", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("market_regime", sa.Text(), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("score_bucket", sa.Text(), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sample_size", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expectancy_after_costs_r", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("entry_touch_rate", sa.Float(), nullable=True),
        sa.Column("no_entry_rate", sa.Float(), nullable=True),
        sa.Column("max_drawdown_r", sa.Float(), nullable=True),
        sa.Column(
            "run_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source IN ('historical_backtest', 'forward_virtual', 'mixed')",
            name="ck_strategy_execution_eligibility_profiles_source",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_strategy_execution_eligibility_profile_key",
        "strategy_execution_eligibility_profiles",
        [
            "strategy_code",
            "exchange",
            "symbol_scope",
            "timeframe",
            "market_regime",
            "score_bucket",
            "direction",
        ],
        unique=True,
    )
    op.create_index(
        "ix_strategy_execution_eligibility_profiles_lookup",
        "strategy_execution_eligibility_profiles",
        ["strategy_code", "exchange", "timeframe"],
    )
    op.create_index(
        "ix_strategy_execution_eligibility_profiles_eligible",
        "strategy_execution_eligibility_profiles",
        ["eligible"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_execution_eligibility_profiles_eligible",
        table_name="strategy_execution_eligibility_profiles",
    )
    op.drop_index(
        "ix_strategy_execution_eligibility_profiles_lookup",
        table_name="strategy_execution_eligibility_profiles",
    )
    op.drop_index(
        "ux_strategy_execution_eligibility_profile_key",
        table_name="strategy_execution_eligibility_profiles",
    )
    op.drop_table("strategy_execution_eligibility_profiles")
