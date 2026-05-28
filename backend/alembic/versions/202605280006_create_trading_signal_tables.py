"""create trading signal tables

Revision ID: 202605280006
Revises: 202605280005
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280006"
down_revision = "202605280005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trading_signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_key", sa.Text(), nullable=False),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("score", sa.Numeric(8, 4), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("stop_loss", sa.Numeric(38, 18), nullable=True),
        sa.Column(
            "take_profit",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("risk_reward", sa.Numeric(10, 4), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "features_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("explanation", sa.Text(), nullable=True),
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
        sa.CheckConstraint("length(trim(signal_key)) > 0", name="ck_trading_signals_signal_key_not_blank"),
        sa.CheckConstraint("length(trim(timeframe)) > 0", name="ck_trading_signals_timeframe_not_blank"),
        sa.CheckConstraint("direction IN ('long', 'short')", name="ck_trading_signals_direction"),
        sa.CheckConstraint(
            "status IN ('new', 'active', 'confirmed', 'expired', 'invalidated', 'closed')",
            name="ck_trading_signals_status",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name="fk_trading_signals_strategy_version_id",
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["market_exchanges.id"],
            name="fk_trading_signals_exchange_id",
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"],
            ["market_pairs.id"],
            name="fk_trading_signals_pair_id",
        ),
        sa.UniqueConstraint("signal_key", name="uq_trading_signals_signal_key"),
    )
    op.execute(
        "CREATE INDEX idx_trading_signals_active "
        "ON trading_signals (status, detected_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_trading_signals_pair_time "
        "ON trading_signals (pair_id, timeframe, detected_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_trading_signals_strategy "
        "ON trading_signals (strategy_version_id, detected_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_trading_signals_features_gin "
        "ON trading_signals USING GIN (features_snapshot)"
    )

    op.create_table(
        "trading_signal_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("old_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=True),
        sa.Column(
            "payload",
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
        sa.CheckConstraint("length(trim(event_type)) > 0", name="ck_trading_signal_events_event_type_not_blank"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["trading_signals.id"],
            name="fk_trading_signal_events_signal_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "created_at", name="pk_trading_signal_events"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.execute("CREATE TABLE trading_signal_events_default PARTITION OF trading_signal_events DEFAULT")
    op.execute(
        "CREATE INDEX idx_trading_signal_events_signal_time "
        "ON trading_signal_events (signal_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_trading_signal_events_event_type_time "
        "ON trading_signal_events (event_type, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_trading_signal_events_event_type_time")
    op.execute("DROP INDEX IF EXISTS idx_trading_signal_events_signal_time")
    op.drop_table("trading_signal_events_default")
    op.drop_table("trading_signal_events")
    op.execute("DROP INDEX IF EXISTS idx_trading_signals_features_gin")
    op.execute("DROP INDEX IF EXISTS idx_trading_signals_strategy")
    op.execute("DROP INDEX IF EXISTS idx_trading_signals_pair_time")
    op.execute("DROP INDEX IF EXISTS idx_trading_signals_active")
    op.drop_table("trading_signals")
