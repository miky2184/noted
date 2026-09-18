"""Aggiunge Note.stream_id: aggancio diretto di una nota a uno Stream, senza
passare da una Fase — per lavoro semplice dove la nota stessa fa da "fase"
nel Gantt (es. "attività extra" con solo una copertura a supporto datata).

Revision ID: 20260919_0001
Revises: 20260918_0001
Create Date: 2026-09-19
"""
import sqlalchemy as sa
from alembic import op

revision = '20260919_0001'
down_revision = '20260918_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("note", sa.Column("stream_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("note", "stream_id")
