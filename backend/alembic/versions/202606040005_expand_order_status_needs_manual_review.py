"""expand order statuses for exchange reconciliation

Revision ID: 202606040005
Revises: 202606040004
Create Date: 2026-06-04
"""

from alembic import op


revision = "202606040005"
down_revision = "202606040004"
branch_labels = None
depends_on = None


_OLD_STATUSES = "'created', 'submitted', 'partially_filled', 'filled', 'cancelled', 'rejected'"
_NEW_STATUSES = _OLD_STATUSES + ", 'needs_manual_review'"


def upgrade() -> None:
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_status",
        "orders",
        f"status IN ({_NEW_STATUSES})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_status",
        "orders",
        f"status IN ({_OLD_STATUSES})",
    )
