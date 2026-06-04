"""expand virtual position lifecycle statuses

Revision ID: 202606040004
Revises: 202606040003
Create Date: 2026-06-04
"""

from alembic import op


revision = "202606040004"
down_revision = "202606040003"
branch_labels = None
depends_on = None


NEW_STATUS_CHECK = (
    "status IN ('open', 'partially_closed', 'closed', 'stopped', "
    "'invalidated', 'expired', 'cancelled', 'liquidated')"
)
OLD_STATUS_CHECK = "status IN ('open', 'closed', 'liquidated')"


def upgrade() -> None:
    op.drop_constraint("ck_positions_status", "positions", type_="check")
    op.create_check_constraint("ck_positions_status", "positions", NEW_STATUS_CHECK)


def downgrade() -> None:
    op.execute(
        "UPDATE positions SET status = CASE "
        "WHEN status = 'partially_closed' THEN 'open' "
        "WHEN status IN ('stopped', 'invalidated', 'expired', 'cancelled') THEN 'closed' "
        "ELSE status END"
    )
    op.drop_constraint("ck_positions_status", "positions", type_="check")
    op.create_check_constraint("ck_positions_status", "positions", OLD_STATUS_CHECK)
