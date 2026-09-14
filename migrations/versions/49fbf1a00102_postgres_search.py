"""PostgreSQL full-text index; local SQLite uses bounded lexical search."""

from alembic import op

revision = "49fbf1a00102"
down_revision = "8588dede27de"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_notice_fts ON source_notices USING GIN (to_tsvector('simple', search_text))"
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_notice_fts")
