"""create user auth identities

Revision ID: 202606040003
Revises: 202606040002
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606040003"
down_revision = "202606040002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_auth_identities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
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
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_user_auth_identities_provider_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(provider_subject)) > 0",
            name="ck_user_auth_identities_provider_subject_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_user_auth_identities_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_user_auth_identities_provider_subject",
        ),
    )
    op.create_index("ix_user_auth_identities_user_id", "user_auth_identities", ["user_id"])
    op.create_index(
        "ix_user_auth_identities_provider_subject",
        "user_auth_identities",
        ["provider_subject"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_auth_identities_provider_subject", table_name="user_auth_identities")
    op.drop_index("ix_user_auth_identities_user_id", table_name="user_auth_identities")
    op.drop_table("user_auth_identities")
