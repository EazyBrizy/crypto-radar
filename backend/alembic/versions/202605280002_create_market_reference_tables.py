"""create market reference tables

Revision ID: 202605280002
Revises: 202605280001
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280002"
down_revision = "202605280001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_exchanges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("api_base_url", sa.Text(), nullable=True),
        sa.Column("ws_base_url", sa.Text(), nullable=True),
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
        sa.CheckConstraint("type IN ('cex', 'dex')", name="ck_market_exchanges_type"),
        sa.CheckConstraint("length(trim(code)) > 0", name="ck_market_exchanges_code_not_blank"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_market_exchanges_name_not_blank"),
        sa.UniqueConstraint("code", name="uq_market_exchanges_code"),
    )

    op.create_table(
        "market_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("asset_type", sa.Text(), nullable=False, server_default="crypto"),
        sa.Column("decimals", sa.Integer(), nullable=True),
        sa.Column("coingecko_id", sa.Text(), nullable=True),
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
        sa.CheckConstraint("length(trim(symbol)) > 0", name="ck_market_assets_symbol_not_blank"),
        sa.CheckConstraint("decimals IS NULL OR decimals >= 0", name="ck_market_assets_decimals_non_negative"),
        sa.UniqueConstraint("symbol", name="uq_market_assets_symbol"),
    )

    op.create_table(
        "market_pairs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("min_qty", sa.Numeric(38, 18), nullable=True),
        sa.Column("tick_size", sa.Numeric(38, 18), nullable=True),
        sa.Column("lot_size", sa.Numeric(38, 18), nullable=True),
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
        sa.CheckConstraint("length(trim(symbol)) > 0", name="ck_market_pairs_symbol_not_blank"),
        sa.CheckConstraint("base_asset_id <> quote_asset_id", name="ck_market_pairs_distinct_assets"),
        sa.CheckConstraint("min_qty IS NULL OR min_qty >= 0", name="ck_market_pairs_min_qty_non_negative"),
        sa.CheckConstraint("tick_size IS NULL OR tick_size > 0", name="ck_market_pairs_tick_size_positive"),
        sa.CheckConstraint("lot_size IS NULL OR lot_size > 0", name="ck_market_pairs_lot_size_positive"),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["market_exchanges.id"],
            name="fk_market_pairs_exchange_id",
        ),
        sa.ForeignKeyConstraint(
            ["base_asset_id"],
            ["market_assets.id"],
            name="fk_market_pairs_base_asset_id",
        ),
        sa.ForeignKeyConstraint(
            ["quote_asset_id"],
            ["market_assets.id"],
            name="fk_market_pairs_quote_asset_id",
        ),
        sa.UniqueConstraint("exchange_id", "symbol", name="uq_market_pairs_exchange_symbol"),
    )
    op.create_index("ix_market_pairs_base_asset_id", "market_pairs", ["base_asset_id"])
    op.create_index("ix_market_pairs_quote_asset_id", "market_pairs", ["quote_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_market_pairs_quote_asset_id", table_name="market_pairs")
    op.drop_index("ix_market_pairs_base_asset_id", table_name="market_pairs")
    op.drop_table("market_pairs")
    op.drop_table("market_assets")
    op.drop_table("market_exchanges")
