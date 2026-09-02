"""add Absence.color (manual color override, optional)

Revision ID: 20260831_0005
Revises: 20260831_0004
Create Date: 2026-08-31

Pure addition, nullable, no backfill: when NULL the frontend keeps deriving
the color deterministically from the person's name (personColor()); this
column lets the user override it per-absence for legibility/preference.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260831_0005'
down_revision = '20260831_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("absence", sa.Column("color", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("absence") as batch_op:
        batch_op.drop_column("color")
