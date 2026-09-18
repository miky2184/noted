"""Riaggiunge Stream.start_date/end_date: uno Stream senza Fasi può avere una
propria data inizio/fine (se ha Fasi, nel Gantt vince l'aggregato min/max tra
le loro date — v. crud._stream_data).

Revision ID: 20260920_0001
Revises: 20260919_0001
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = '20260920_0001'
down_revision = '20260919_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stream", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("stream", sa.Column("end_date", sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table("stream") as batch_op:
        batch_op.drop_column("start_date")
        batch_op.drop_column("end_date")
