"""add market universe fields to market pairs

Revision ID: 202606040006
Revises: 202606040005
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa


revision = "202606040006"
down_revision = "202606040005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_pairs", sa.Column("market_type", sa.Text(), nullable=True))
    op.add_column("market_pairs", sa.Column("category", sa.Text(), nullable=True))
    op.add_column("market_pairs", sa.Column("quote_volume_24h", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("base_volume_24h", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("turnover_24h", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("last_price", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("mark_price", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("bid_price", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("ask_price", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_pairs", sa.Column("spread_bps", sa.Numeric(18, 8), nullable=True))
    op.add_column("market_pairs", sa.Column("funding_rate", sa.Numeric(18, 10), nullable=True))
    op.add_column("market_pairs", sa.Column("liquidity_rank", sa.Integer(), nullable=True))
    op.add_column("market_pairs", sa.Column("liquidity_tier", sa.Text(), nullable=True))
    op.add_column("market_pairs", sa.Column("exchange_status", sa.Text(), nullable=True))
    op.add_column("market_pairs", sa.Column("universe_source", sa.Text(), nullable=True))
    op.add_column("market_pairs", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))

    op.create_check_constraint(
        "ck_market_pairs_quote_volume_24h_non_negative",
        "market_pairs",
        "quote_volume_24h IS NULL OR quote_volume_24h >= 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_base_volume_24h_non_negative",
        "market_pairs",
        "base_volume_24h IS NULL OR base_volume_24h >= 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_turnover_24h_non_negative",
        "market_pairs",
        "turnover_24h IS NULL OR turnover_24h >= 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_last_price_positive",
        "market_pairs",
        "last_price IS NULL OR last_price > 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_mark_price_positive",
        "market_pairs",
        "mark_price IS NULL OR mark_price > 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_bid_price_positive",
        "market_pairs",
        "bid_price IS NULL OR bid_price > 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_ask_price_positive",
        "market_pairs",
        "ask_price IS NULL OR ask_price > 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_spread_bps_non_negative",
        "market_pairs",
        "spread_bps IS NULL OR spread_bps >= 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_liquidity_rank_positive",
        "market_pairs",
        "liquidity_rank IS NULL OR liquidity_rank > 0",
    )
    op.create_check_constraint(
        "ck_market_pairs_liquidity_tier",
        "market_pairs",
        "liquidity_tier IS NULL OR liquidity_tier IN ('high', 'medium', 'low', 'unknown')",
    )

    op.create_index(
        "idx_market_pairs_exchange_category_rank",
        "market_pairs",
        ["exchange_id", "category", "liquidity_rank"],
    )
    op.create_index(
        "idx_market_pairs_exchange_quote_rank",
        "market_pairs",
        ["exchange_id", "quote_asset_id", "liquidity_rank"],
    )
    op.create_index(
        "idx_market_pairs_exchange_turnover",
        "market_pairs",
        ["exchange_id", "turnover_24h"],
    )


def downgrade() -> None:
    op.drop_index("idx_market_pairs_exchange_turnover", table_name="market_pairs")
    op.drop_index("idx_market_pairs_exchange_quote_rank", table_name="market_pairs")
    op.drop_index("idx_market_pairs_exchange_category_rank", table_name="market_pairs")

    op.drop_constraint("ck_market_pairs_liquidity_tier", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_liquidity_rank_positive", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_spread_bps_non_negative", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_ask_price_positive", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_bid_price_positive", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_mark_price_positive", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_last_price_positive", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_turnover_24h_non_negative", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_base_volume_24h_non_negative", "market_pairs", type_="check")
    op.drop_constraint("ck_market_pairs_quote_volume_24h_non_negative", "market_pairs", type_="check")

    op.drop_column("market_pairs", "synced_at")
    op.drop_column("market_pairs", "universe_source")
    op.drop_column("market_pairs", "exchange_status")
    op.drop_column("market_pairs", "liquidity_tier")
    op.drop_column("market_pairs", "liquidity_rank")
    op.drop_column("market_pairs", "funding_rate")
    op.drop_column("market_pairs", "spread_bps")
    op.drop_column("market_pairs", "ask_price")
    op.drop_column("market_pairs", "bid_price")
    op.drop_column("market_pairs", "mark_price")
    op.drop_column("market_pairs", "last_price")
    op.drop_column("market_pairs", "turnover_24h")
    op.drop_column("market_pairs", "base_volume_24h")
    op.drop_column("market_pairs", "quote_volume_24h")
    op.drop_column("market_pairs", "category")
    op.drop_column("market_pairs", "market_type")
