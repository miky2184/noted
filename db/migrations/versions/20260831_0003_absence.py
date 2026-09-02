"""add Absence table (persona + periodo, banda sulla timeline)

Revision ID: 20260831_0003
Revises: 20260831_0002
Create Date: 2026-08-31

Pure addition, no backfill: nothing in the existing schema maps to this new
concept (absences are a brand-new, deliberately lightweight idea — no note
links, no progress, just a person + a date range rendered as a colored band
on the Gantt timeline, separate from client/project work).
"""
from alembic import op
import sqlalchemy as sa

revision = '20260831_0003'
down_revision = '20260831_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "absence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person", sa.String(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("context", sa.String(), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_absence_context", "absence", ["context"])


def downgrade() -> None:
    op.drop_index("ix_absence_context", table_name="absence")
    op.drop_table("absence")
