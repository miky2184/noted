"""add Note.email_subject/email_body (saved AI email draft)

Revision ID: 20260902_0001
Revises: 20260901_0001
Create Date: 2026-09-02

Pure additions, nullable, no backfill. Plain ADD COLUMN (no batch mode), so
this does not touch the `note` table's DDL beyond appending columns — the
FTS5 sync triggers are unaffected (unlike the batch_alter_table changes in
20260831_0002/0004, which had to recreate them).
"""
from alembic import op
import sqlalchemy as sa

revision = '20260902_0001'
down_revision = '20260901_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("note", sa.Column("email_subject", sa.String(), nullable=True))
    op.add_column("note", sa.Column("email_body", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("note", "email_body")
    op.drop_column("note", "email_subject")
