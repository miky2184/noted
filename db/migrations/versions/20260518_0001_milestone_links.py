"""add milestone_id to note and note_id to milestone

Revision ID: 20260518_0001
Revises: 20260517_0002
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = '20260518_0001'
down_revision = '20260517_0002'
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("milestone") as batch_op:
        batch_op.add_column(sa.Column("note_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("note") as batch_op:
        batch_op.add_column(sa.Column("milestone_id", sa.Integer(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table("milestone") as batch_op:
        batch_op.drop_column("note_id")
    with op.batch_alter_table("note") as batch_op:
        batch_op.drop_column("milestone_id")
