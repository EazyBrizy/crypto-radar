"""add exchange connection execution safety fields

Revision ID: 202606050002
Revises: 202606050001
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "202606050002"
down_revision = "202606050001"
branch_labels = None
depends_on = None


TRUTHY = "'true', '1', 'yes', 'on', 'enabled', 'testnet'"


def upgrade() -> None:
    op.add_column(
        "user_exchange_connections",
        sa.Column("environment", sa.Text(), nullable=True, server_default="testnet"),
    )
    op.add_column(
        "user_exchange_connections",
        sa.Column("order_placement_mode", sa.Text(), nullable=False, server_default="dry_run"),
    )
    op.add_column(
        "user_exchange_connections",
        sa.Column("mainnet_explicitly_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "user_exchange_connections",
        sa.Column("last_account_snapshot_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_exchange_connections",
        sa.Column("account_snapshot_status", sa.Text(), nullable=False, server_default="missing"),
    )

    op.execute(
        f"""
        UPDATE user_exchange_connections
        SET environment = CASE
            WHEN lower(coalesce(metadata ->> 'testnet', '')) IN ({TRUTHY})
              OR lower(coalesce(metadata ->> 'environment', '')) = 'testnet'
              OR lower(coalesce(metadata ->> 'network', '')) = 'testnet'
            THEN 'testnet'
            ELSE 'mainnet'
        END
        """
    )
    op.execute(
        """
        UPDATE user_exchange_connections
        SET order_placement_mode = lower(metadata ->> 'order_placement_mode')
        WHERE lower(coalesce(metadata ->> 'order_placement_mode', '')) IN ('disabled', 'dry_run', 'live')
        """
    )
    op.execute(
        f"""
        UPDATE user_exchange_connections
        SET mainnet_explicitly_enabled = true
        WHERE lower(coalesce(metadata ->> 'mainnet_explicitly_enabled', '')) IN ({TRUTHY})
           OR lower(coalesce(metadata ->> 'explicit_mainnet_enabled', '')) IN ({TRUTHY})
           OR lower(coalesce(metadata ->> 'mainnet_enabled', '')) IN ({TRUTHY})
           OR lower(coalesce(metadata ->> 'enable_live_mainnet', '')) IN ({TRUTHY})
           OR lower(coalesce(metadata ->> 'enable_mainnet_order_placement', '')) IN ({TRUTHY})
           OR lower(coalesce(metadata ->> 'mainnet_order_placement_enabled', '')) IN ({TRUTHY})
           OR lower(coalesce(metadata ->> 'allow_mainnet_order_placement', '')) IN ({TRUTHY})
        """
    )

    op.alter_column("user_exchange_connections", "environment", nullable=False)
    op.create_check_constraint(
        "ck_user_exchange_connections_environment",
        "user_exchange_connections",
        "environment IN ('testnet', 'mainnet')",
    )
    op.create_check_constraint(
        "ck_user_exchange_connections_order_placement_mode",
        "user_exchange_connections",
        "order_placement_mode IN ('disabled', 'dry_run', 'live')",
    )
    op.create_check_constraint(
        "ck_user_exchange_connections_account_snapshot_status",
        "user_exchange_connections",
        "account_snapshot_status IN ('fresh', 'stale', 'missing')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_exchange_connections_account_snapshot_status",
        "user_exchange_connections",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_exchange_connections_order_placement_mode",
        "user_exchange_connections",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_exchange_connections_environment",
        "user_exchange_connections",
        type_="check",
    )
    op.drop_column("user_exchange_connections", "account_snapshot_status")
    op.drop_column("user_exchange_connections", "last_account_snapshot_at")
    op.drop_column("user_exchange_connections", "mainnet_explicitly_enabled")
    op.drop_column("user_exchange_connections", "order_placement_mode")
    op.drop_column("user_exchange_connections", "environment")
