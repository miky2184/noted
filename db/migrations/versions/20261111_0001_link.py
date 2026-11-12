"""Tabella link: raccoglitore di link (OneDrive, Drive, SharePoint...) per
cliente/progetto. Migrazione solo additiva (nuova tabella): nessun dato esistente
viene toccato.

Revision ID: 20261111_0001
Revises: 20260920_0001
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = '20261111_0001'
down_revision = '20260920_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("cliente", sa.String(), nullable=True),
        sa.Column("project", sa.String(), nullable=True),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("note.id"), nullable=True),
        sa.Column("context", sa.String(), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_link_cliente", "link", ["cliente"])
    op.create_index("ix_link_context", "link", ["context"])
    op.create_index("ix_link_created_at", "link", ["created_at"])


def downgrade():
    op.drop_table("link")
