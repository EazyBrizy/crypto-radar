"""create signal ai explanations

Revision ID: 202605280010
Revises: 202605280009
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280010"
down_revision = "202605280009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_ai_explanations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_provider", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("explanation_md", sa.Text(), nullable=False),
        sa.Column("risk_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(trim(model_provider)) > 0",
            name="ck_signal_ai_explanations_model_provider_not_blank",
        ),
        sa.CheckConstraint("length(trim(model_name)) > 0", name="ck_signal_ai_explanations_model_name_not_blank"),
        sa.CheckConstraint("length(trim(prompt_hash)) > 0", name="ck_signal_ai_explanations_prompt_hash_not_blank"),
        sa.CheckConstraint(
            "length(trim(explanation_md)) > 0",
            name="ck_signal_ai_explanations_explanation_md_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["trading_signals.id"],
            name="fk_signal_ai_explanations_signal_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_signal_ai_explanations_signal_id", "signal_ai_explanations", ["signal_id"])
    op.create_index("ix_signal_ai_explanations_created_at", "signal_ai_explanations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_signal_ai_explanations_created_at", table_name="signal_ai_explanations")
    op.drop_index("ix_signal_ai_explanations_signal_id", table_name="signal_ai_explanations")
    op.drop_table("signal_ai_explanations")
