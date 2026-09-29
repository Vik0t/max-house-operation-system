"""Remember the representative's manual route choice on Action.

Revision ID: 20260928_0002
Revises: 20260918_0001
"""
import sqlalchemy as sa
from alembic import op

revision = "20260928_0002"
down_revision = "20260918_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("actions")}
    if "manual_destination" not in columns:
        op.add_column("actions", sa.Column("manual_destination", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("actions", "manual_destination")
