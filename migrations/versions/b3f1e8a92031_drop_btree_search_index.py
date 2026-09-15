"""drop btree index on search_text in postgresql

Revision ID: b3f1e8a92031
Revises: 72c149c94201
Create Date: 2026-09-15 11:32:00.000000

"""
from alembic import op

revision = "b3f1e8a92031"
down_revision = "72c149c94201"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX IF EXISTS ix_notice_search")


def downgrade():
    op.create_index("ix_notice_search", "source_notices", ["search_text"], unique=False)
