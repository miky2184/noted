"""baseline schema

Revision ID: 20260516_0001
Revises:
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
import logging


revision = "20260516_0001"
down_revision = None
branch_labels = None
depends_on = None
logger = logging.getLogger("alembic.runtime.migration")


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table_name: str) -> set[str]:
    if table_name not in _table_names(bind):
        return set()
    return {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def _add_column_if_missing(bind, table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(bind, table_name):
        op.add_column(table_name, column)


def _exec(sql: str) -> None:
    op.execute(sa.text(sql))


def _create_core_tables() -> None:
    _exec("""
        CREATE TABLE IF NOT EXISTS context (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            created_at DATETIME NOT NULL
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS note (
            id INTEGER PRIMARY KEY,
            content VARCHAR NOT NULL,
            tags VARCHAR NOT NULL DEFAULT '',
            project VARCHAR,
            priority VARCHAR NOT NULL DEFAULT 'medium',
            due_date DATE,
            status VARCHAR,
            assignee VARCHAR,
            context VARCHAR NOT NULL DEFAULT 'default',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS recap (
            id INTEGER PRIMARY KEY,
            recap_date DATE NOT NULL,
            summary VARCHAR NOT NULL,
            notes_count INTEGER NOT NULL DEFAULT 0,
            context VARCHAR NOT NULL DEFAULT 'default',
            created_at DATETIME NOT NULL
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS ganttproject (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            color VARCHAR NOT NULL DEFAULT '#818cf8',
            context VARCHAR NOT NULL DEFAULT 'default',
            is_background BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS milestone (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES ganttproject(id),
            name VARCHAR NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            created_at DATETIME NOT NULL
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS notedependency (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL REFERENCES note(id),
            blocker_id INTEGER NOT NULL REFERENCES note(id),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(note_id, blocker_id)
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER REFERENCES note(id) ON DELETE SET NULL,
            rel_path TEXT NOT NULL,
            orig_name TEXT NOT NULL,
            mime_type TEXT,
            size_bytes INTEGER,
            sha256 TEXT,
            analysis TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _upgrade_existing_tables() -> None:
    bind = op.get_bind()
    _add_column_if_missing(bind, "note", sa.Column("assignee", sa.String(), nullable=True))
    _add_column_if_missing(bind, "note", sa.Column("context", sa.String(), server_default="default", nullable=False))
    _add_column_if_missing(bind, "note", sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False))
    _add_column_if_missing(bind, "recap", sa.Column("context", sa.String(), server_default="default", nullable=False))
    _add_column_if_missing(bind, "ganttproject", sa.Column("context", sa.String(), server_default="default", nullable=False))
    _add_column_if_missing(bind, "ganttproject", sa.Column("is_background", sa.Boolean(), server_default="0", nullable=False))
    _add_column_if_missing(bind, "document", sa.Column("analysis", sa.Text(), nullable=True))
    _exec("DELETE FROM document WHERE note_id IS NOT NULL AND note_id NOT IN (SELECT id FROM note)")


def _create_fts() -> None:
    try:
        _exec("""
            CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
                content,
                tags,
                project,
                assignee,
                context UNINDEXED,
                content='note',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
        """)
        _exec("""
            CREATE TRIGGER IF NOT EXISTS note_ai AFTER INSERT ON note BEGIN
                INSERT INTO note_fts(rowid, content, tags, project, assignee, context)
                VALUES (new.id, new.content, new.tags, new.project, new.assignee, new.context);
            END
        """)
        _exec("""
            CREATE TRIGGER IF NOT EXISTS note_ad AFTER DELETE ON note BEGIN
                INSERT INTO note_fts(note_fts, rowid, content, tags, project, assignee, context)
                VALUES ('delete', old.id, old.content, old.tags, old.project, old.assignee, old.context);
            END
        """)
        _exec("""
            CREATE TRIGGER IF NOT EXISTS note_au AFTER UPDATE ON note BEGIN
                INSERT INTO note_fts(note_fts, rowid, content, tags, project, assignee, context)
                VALUES ('delete', old.id, old.content, old.tags, old.project, old.assignee, old.context);
                INSERT INTO note_fts(rowid, content, tags, project, assignee, context)
                VALUES (new.id, new.content, new.tags, new.project, new.assignee, new.context);
            END
        """)
        _exec("INSERT INTO note_fts(note_fts) VALUES ('rebuild')")
    except Exception as exc:
        if "fts5" not in str(exc).lower():
            raise
        # FTS5 is optional at runtime; search falls back to LIKE when this is unavailable.
        logger.warning("SQLite FTS5 setup failed; note search will use LIKE fallback", exc_info=True)


def upgrade() -> None:
    _create_core_tables()
    _upgrade_existing_tables()
    _create_fts()


def downgrade() -> None:
    _exec("DROP TRIGGER IF EXISTS note_au")
    _exec("DROP TRIGGER IF EXISTS note_ad")
    _exec("DROP TRIGGER IF EXISTS note_ai")
    _exec("DROP TABLE IF EXISTS note_fts")
