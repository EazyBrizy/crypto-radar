"""enable postgres extensions

Revision ID: 202605280001
Revises:
Create Date: 2026-05-28
"""

from alembic import op


revision = "202605280001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")


def downgrade() -> None:
    # Extensions may be shared by other objects, so downgrades leave them in place.
    pass
