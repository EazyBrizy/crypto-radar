"""add lifecycle trace link to risk decisions

Revision ID: 202606040002
Revises: 202606040001
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606040002"
down_revision = "202606040001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "risk_decisions",
        sa.Column("pending_entry_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_risk_decisions_pending_entry_intent_id",
        "risk_decisions",
        "pending_entry_intents",
        ["pending_entry_intent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_risk_decisions_pending_entry_intent_id",
        "risk_decisions",
        ["pending_entry_intent_id"],
    )
    op.execute(
        "CREATE INDEX idx_risk_decisions_pending_entry_time "
        "ON risk_decisions (pending_entry_intent_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_risk_decisions_pending_entry_time")
    op.drop_index("ix_risk_decisions_pending_entry_intent_id", table_name="risk_decisions")
    op.drop_constraint(
        "fk_risk_decisions_pending_entry_intent_id",
        "risk_decisions",
        type_="foreignkey",
    )
    op.drop_column("risk_decisions", "pending_entry_intent_id")
