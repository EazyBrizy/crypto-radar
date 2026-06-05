"""add soft delete to exchange connections

Revision ID: 202606050001
Revises: 202606040006
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "202606050001"
down_revision = "202606040006"
branch_labels = None
depends_on = None


VALID_STATUSES = "'active', 'disabled', 'revoked', 'deleted'"


def upgrade() -> None:
    op.add_column("user_exchange_connections", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_exchange_connections", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_exchange_connections", sa.Column("deletion_reason", sa.Text(), nullable=True))
    op.drop_constraint(
        "uq_user_exchange_connections_user_exchange_label",
        "user_exchange_connections",
        type_="unique",
    )
    op.execute(
        f"""
        UPDATE user_exchange_connections
        SET status = 'disabled'
        WHERE status NOT IN ({VALID_STATUSES})
        """
    )
    op.create_check_constraint(
        "ck_user_exchange_connections_status",
        "user_exchange_connections",
        f"status IN ({VALID_STATUSES})",
    )
    op.create_index(
        "uq_user_exchange_connections_active_label",
        "user_exchange_connections",
        ["user_id", "exchange_id", "label"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('deleted', 'revoked')"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_exchange_connections_active_label", table_name="user_exchange_connections")
    op.create_unique_constraint(
        "uq_user_exchange_connections_user_exchange_label",
        "user_exchange_connections",
        ["user_id", "exchange_id", "label"],
    )
    op.drop_constraint("ck_user_exchange_connections_status", "user_exchange_connections", type_="check")
    op.drop_column("user_exchange_connections", "deletion_reason")
    op.drop_column("user_exchange_connections", "deleted_at")
    op.drop_column("user_exchange_connections", "revoked_at")
