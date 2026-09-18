"""Initial DomPuls schema.

Revision ID: 20260918_0001
Revises: None
"""
from app.db import Base
from app import models  # noqa: F401

revision = "20260918_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from alembic import op

    Base.metadata.drop_all(bind=op.get_bind())

