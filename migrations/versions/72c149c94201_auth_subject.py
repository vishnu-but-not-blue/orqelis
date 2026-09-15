"""Bind hosted identity to immutable provider subject."""

import sqlalchemy as sa
from alembic import op

revision = "72c149c94201"
down_revision = "49fbf1a00102"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("auth_subject", sa.String(160), nullable=True))
        batch.create_unique_constraint("uq_users_auth_subject", ["auth_subject"])


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_auth_subject", type_="unique")
        batch.drop_column("auth_subject")
