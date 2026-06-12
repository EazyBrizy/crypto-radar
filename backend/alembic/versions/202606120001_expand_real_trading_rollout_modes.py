"""Expand real trading rollout order modes.

Revision ID: 202606120001
Revises: 202606110001
Create Date: 2026-06-12 16:16:00.000000
"""

from alembic import op


revision = "202606120001"
down_revision = "202606110001"
branch_labels = None
depends_on = None


NEW_ORDER_PLACEMENT_MODES = (
    "order_placement_mode IN ("
    "'disabled', "
    "'dry_run', "
    "'dry_run_orders', "
    "'testnet_real_orders', "
    "'mainnet_small_size', "
    "'mainnet_scaled', "
    "'live'"
    ")"
)
OLD_ORDER_PLACEMENT_MODES = "order_placement_mode IN ('disabled', 'dry_run', 'live')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_user_exchange_connections_order_placement_mode",
        "user_exchange_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_exchange_connections_order_placement_mode",
        "user_exchange_connections",
        NEW_ORDER_PLACEMENT_MODES,
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_exchange_connections
        SET order_placement_mode = CASE
            WHEN order_placement_mode = 'disabled' THEN 'disabled'
            WHEN order_placement_mode IN ('dry_run', 'dry_run_orders') THEN 'dry_run'
            ELSE 'live'
        END
        """
    )
    op.drop_constraint(
        "ck_user_exchange_connections_order_placement_mode",
        "user_exchange_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_exchange_connections_order_placement_mode",
        "user_exchange_connections",
        OLD_ORDER_PLACEMENT_MODES,
    )
