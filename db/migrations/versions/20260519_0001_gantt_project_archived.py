"""add archived to ganttproject

Revision ID: 20260519_0001
Revises: 20260518_0001
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = '20260519_0001'
down_revision = '20260518_0001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("ganttproject") as batch_op:
        batch_op.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"))

def downgrade() -> None:
    with op.batch_alter_table("ganttproject") as batch_op:
        batch_op.drop_column("archived")
