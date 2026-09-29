"""MAX identity and selected house.

Revision ID: 20260929_0003
Revises: 20260928_0002
"""
import sqlalchemy as sa
from alembic import op

revision = "20260929_0003"
down_revision = "20260928_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    uri_type = next(item["type"] for item in inspector.get_columns("evidence") if item["name"] == "uri")
    if uri_type.__class__.__name__.lower() != "text":
        op.alter_column("evidence", "uri", existing_type=sa.String(500), type_=sa.Text(), existing_nullable=False)
    tables = set(inspector.get_table_names())
    if "max_profiles" not in tables:
        op.create_table(
        "max_profiles",
        sa.Column("user_id", sa.String(100), primary_key=True),
        sa.Column("selected_house_id", sa.String(64), sa.ForeignKey("houses.id"), nullable=True),
        sa.Column("residency_status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "issue_comments" not in tables:
        op.create_table(
        "issue_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issue_id", sa.String(36), sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.String(100), nullable=False),
        sa.Column("author_role", sa.String(40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_issue_comments_issue_id", "issue_comments", ["issue_id"])


def downgrade() -> None:
    op.alter_column("evidence", "uri", existing_type=sa.Text(), type_=sa.String(500), existing_nullable=False)
    op.drop_index("ix_issue_comments_issue_id", table_name="issue_comments")
    op.drop_table("issue_comments")
    op.drop_table("max_profiles")
