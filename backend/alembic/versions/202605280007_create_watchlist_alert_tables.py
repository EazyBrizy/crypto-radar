"""create watchlist alert tables

Revision ID: 202605280007
Revises: 202605280006
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280007"
down_revision = "202605280006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_watchlists",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_user_watchlists_name_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_user_watchlists_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_user_watchlists_user_id", "user_watchlists", ["user_id"])

    op.create_table(
        "user_watchlist_pairs",
        sa.Column("watchlist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["user_watchlists.id"],
            name="fk_user_watchlist_pairs_watchlist_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"],
            ["market_pairs.id"],
            name="fk_user_watchlist_pairs_pair_id",
        ),
        sa.PrimaryKeyConstraint("watchlist_id", "pair_id", name="pk_user_watchlist_pairs"),
    )
    op.create_index("ix_user_watchlist_pairs_pair_id", "user_watchlist_pairs", ["pair_id"])

    op.create_table(
        "user_alert_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("condition_type", sa.Text(), nullable=False),
        sa.Column("condition_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "channels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['websocket']::text[]"),
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(condition_type)) > 0", name="ck_user_alert_rules_condition_type_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_user_alert_rules_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"],
            ["market_pairs.id"],
            name="fk_user_alert_rules_pair_id",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name="fk_user_alert_rules_strategy_version_id",
        ),
    )
    op.create_index("ix_user_alert_rules_user_id", "user_alert_rules", ["user_id"])
    op.create_index("ix_user_alert_rules_pair_id", "user_alert_rules", ["pair_id"])
    op.create_index("ix_user_alert_rules_strategy_version_id", "user_alert_rules", ["strategy_version_id"])
    op.create_index("ix_user_alert_rules_is_enabled", "user_alert_rules", ["is_enabled"])


def downgrade() -> None:
    op.drop_index("ix_user_alert_rules_is_enabled", table_name="user_alert_rules")
    op.drop_index("ix_user_alert_rules_strategy_version_id", table_name="user_alert_rules")
    op.drop_index("ix_user_alert_rules_pair_id", table_name="user_alert_rules")
    op.drop_index("ix_user_alert_rules_user_id", table_name="user_alert_rules")
    op.drop_table("user_alert_rules")
    op.drop_index("ix_user_watchlist_pairs_pair_id", table_name="user_watchlist_pairs")
    op.drop_table("user_watchlist_pairs")
    op.drop_index("ix_user_watchlists_user_id", table_name="user_watchlists")
    op.drop_table("user_watchlists")
