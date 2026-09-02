"""add Note.cliente and Note.start_date

Revision ID: 20260831_0004
Revises: 20260831_0003
Create Date: 2026-08-31

Notes become the source of truth for "who is this work for": a note can now
carry a free-text `cliente` (mirrors the existing `project` field — same
lightweight, no-FK style) and an optional `start_date` alongside the existing
`due_date`, so a single note can describe a scheduled range without needing
a separate Milestone/Fase.

Pure addition, no backfill: existing notes simply have cliente=NULL,
start_date=NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260831_0004'
down_revision = '20260831_0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("note") as batch_op:
        batch_op.add_column(sa.Column("cliente", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))
    op.create_index("ix_note_cliente", "note", ["cliente"])

    # SQLite's batch mode DROPs and recreates the `note` table (see the same
    # issue documented in 20260831_0002_stream_milestone.py), which also
    # drops the FTS5 sync triggers from the baseline migration — recreate
    # them or note search silently stops indexing new/edited notes.
    bind = op.get_bind()
    try:
        bind.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS note_ai AFTER INSERT ON note BEGIN
                INSERT INTO note_fts(rowid, content, tags, project, assignee, context)
                VALUES (new.id, new.content, new.tags, new.project, new.assignee, new.context);
            END
        """))
        bind.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS note_ad AFTER DELETE ON note BEGIN
                INSERT INTO note_fts(note_fts, rowid, content, tags, project, assignee, context)
                VALUES ('delete', old.id, old.content, old.tags, old.project, old.assignee, old.context);
            END
        """))
        bind.execute(sa.text("""
            CREATE TRIGGER IF NOT EXISTS note_au AFTER UPDATE ON note BEGIN
                INSERT INTO note_fts(note_fts, rowid, content, tags, project, assignee, context)
                VALUES ('delete', old.id, old.content, old.tags, old.project, old.assignee, old.context);
                INSERT INTO note_fts(rowid, content, tags, project, assignee, context)
                VALUES (new.id, new.content, new.tags, new.project, new.assignee, new.context);
            END
        """))
        bind.execute(sa.text("INSERT INTO note_fts(note_fts) VALUES ('rebuild')"))
    except Exception as exc:
        if "fts5" not in str(exc).lower() and "no such table" not in str(exc).lower():
            raise


def downgrade() -> None:
    op.drop_index("ix_note_cliente", table_name="note")
    with op.batch_alter_table("note") as batch_op:
        batch_op.drop_column("start_date")
        batch_op.drop_column("cliente")
