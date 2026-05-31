"""create market derivative snapshots

Revision ID: 202605310002
Revises: 202605310001
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605310002"
down_revision = "202605310001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_derivative_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'linear'")),
        sa.Column("mark_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("funding_rate", sa.Numeric(18, 10), nullable=True),
        sa.Column("volume_24h", sa.Numeric(38, 18), nullable=True),
        sa.Column("turnover_24h", sa.Numeric(38, 18), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'bybit_v5_tickers'")),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("length(trim(symbol)) > 0", name="ck_market_derivative_snapshots_symbol_not_blank"),
        sa.CheckConstraint(
            "category IN ('linear', 'inverse', 'option')",
            name="ck_market_derivative_snapshots_category",
        ),
        sa.CheckConstraint(
            "mark_price IS NULL OR mark_price > 0",
            name="ck_market_derivative_snapshots_mark_price_positive",
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["market_exchanges.id"],
            name="fk_market_derivative_snapshots_exchange_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"],
            ["market_pairs.id"],
            name="fk_market_derivative_snapshots_pair_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "exchange_id",
            "symbol",
            "category",
            name="uq_market_derivative_snapshots_exchange_symbol_category",
        ),
    )
    op.create_index(
        "ix_market_derivative_snapshots_pair_id",
        "market_derivative_snapshots",
        ["pair_id"],
    )
    op.create_index(
        "ix_market_derivative_snapshots_fetched_at",
        "market_derivative_snapshots",
        ["fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_derivative_snapshots_fetched_at", table_name="market_derivative_snapshots")
    op.drop_index("ix_market_derivative_snapshots_pair_id", table_name="market_derivative_snapshots")
    op.drop_table("market_derivative_snapshots")
