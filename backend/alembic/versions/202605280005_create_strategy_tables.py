"""create strategy tables

Revision ID: 202605280005
Revises: 202605280004
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280005"
down_revision = "202605280004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(code)) > 0", name="ck_strategy_templates_code_not_blank"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_strategy_templates_name_not_blank"),
        sa.CheckConstraint("length(trim(category)) > 0", name="ck_strategy_templates_category_not_blank"),
        sa.UniqueConstraint("code", name="uq_strategy_templates_code"),
    )

    op.create_table(
        "strategy_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("config_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("default_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(version)) > 0", name="ck_strategy_versions_version_not_blank"),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy_templates.id"],
            name="fk_strategy_versions_strategy_id",
        ),
        sa.UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_strategy_version"),
    )
    op.create_index("ix_strategy_versions_strategy_id", "strategy_versions", ["strategy_id"])
    op.create_index("ix_strategy_versions_status", "strategy_versions", ["status"])

    op.create_table(
        "user_strategy_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "exchange_scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "pair_scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("timeframes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "risk_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_user_strategy_configs_name_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_user_strategy_configs_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name="fk_user_strategy_configs_strategy_version_id",
        ),
    )
    op.create_index("ix_user_strategy_configs_user_id", "user_strategy_configs", ["user_id"])
    op.create_index(
        "ix_user_strategy_configs_strategy_version_id",
        "user_strategy_configs",
        ["strategy_version_id"],
    )
    op.create_index("ix_user_strategy_configs_is_enabled", "user_strategy_configs", ["is_enabled"])


def downgrade() -> None:
    op.drop_index("ix_user_strategy_configs_is_enabled", table_name="user_strategy_configs")
    op.drop_index("ix_user_strategy_configs_strategy_version_id", table_name="user_strategy_configs")
    op.drop_index("ix_user_strategy_configs_user_id", table_name="user_strategy_configs")
    op.drop_table("user_strategy_configs")
    op.drop_index("ix_strategy_versions_status", table_name="strategy_versions")
    op.drop_index("ix_strategy_versions_strategy_id", table_name="strategy_versions")
    op.drop_table("strategy_versions")
    op.drop_table("strategy_templates")
