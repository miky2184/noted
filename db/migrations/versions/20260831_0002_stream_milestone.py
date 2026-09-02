"""replace Task with Stream, make Milestone dates optional and nestable under a Stream

Revision ID: 20260831_0002
Revises: 20260831_0001
Create Date: 2026-08-31

Supersedes the "Task" concept introduced in 20260831_0001 with a richer model
based on real user feedback: a "Fase" (Milestone) can live directly on a
project or nested under a "Stream" (a work initiative, e.g. "Collection"),
and a Fase's dates are now optional — it can exist as a note container before
its schedule is known, and only renders as a timeline bar once both dates are
set.

Migration path (data-preserving): the 4 auto-created "Generale" Task rows
from the previous migration's backfill (each holding real historical notes
via note.task_id) become root Milestone rows (stream_id=None, no dates), and
note.task_id is migrated to note.milestone_id before task_id is dropped. The
`stream` table starts empty — no data maps to it, since no real Stream
existed before this feature.

Verified against the live database before writing this migration:
- note.milestone_id IS NOT NULL AND task_id IS NOT NULL → 0 rows (no conflicts)
- milestone.task_id IS NOT NULL → 0 rows (column never written by any code
  path, safe to drop without loss)
- a background project (is_background=1) already has a dateless-note root
  milestone in production — preserved untouched by this migration since it
  doesn't touch existing Milestone rows, only adds columns/backfills new ones

Idempotent: db.engine.init_db() runs `alembic upgrade head` on every app
startup, not just once at deploy time.
"""
import logging

from alembic import op
import sqlalchemy as sa

revision = '20260831_0002'
down_revision = '20260831_0001'
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.create_table(
        "stream",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("ganttproject.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stream_project_id", "stream", ["project_id"])

    # drop the old index before the batch recreate below, otherwise SQLite's
    # batch mode reflects it from the live table and tries to reissue it
    # against a column that's being dropped in the same operation
    op.drop_index("ix_milestone_task_id", table_name="milestone")

    with op.batch_alter_table("milestone") as batch_op:
        batch_op.alter_column("start_date", existing_type=sa.Date(), nullable=True)
        batch_op.alter_column("end_date", existing_type=sa.Date(), nullable=True)
        batch_op.add_column(sa.Column("stream_id", sa.Integer(), nullable=True))
        batch_op.drop_column("task_id")
    op.create_index("ix_milestone_stream_id", "milestone", ["stream_id"])

    # ── Backfill (outside batch_alter_table, after every column/table above
    # exists; guarded for idempotency across repeated app-startup runs) ─────
    bind = op.get_bind()

    bind.execute(sa.text("""
        INSERT INTO milestone (project_id, name, start_date, end_date, note_id, stream_id, created_at)
        SELECT t.project_id, t.name, NULL, NULL, NULL, NULL, t.created_at
        FROM task t
        WHERE NOT EXISTS (
            SELECT 1 FROM milestone m
            WHERE m.project_id = t.project_id AND m.name = t.name AND m.stream_id IS NULL
        )
    """))

    bind.execute(sa.text("""
        UPDATE note
        SET milestone_id = (
            SELECT m.id FROM milestone m
            JOIN task t ON t.project_id = m.project_id AND t.name = m.name AND m.stream_id IS NULL
            WHERE t.id = note.task_id
            LIMIT 1
        )
        WHERE task_id IS NOT NULL AND milestone_id IS NULL
    """))

    conflicts = bind.execute(sa.text("""
        SELECT COUNT(*) FROM note WHERE task_id IS NOT NULL AND milestone_id IS NOT NULL
    """)).scalar()
    if conflicts:
        logger.warning(
            "Gantt migration: %d note avevano sia task_id sia milestone_id gia' impostati — "
            "il vecchio task_id verra' comunque scartato, la nota resta collegata alla sua "
            "milestone esistente.", conflicts,
        )

    op.drop_index("ix_note_task_id", table_name="note")
    with op.batch_alter_table("note") as batch_op:
        batch_op.drop_column("task_id")

    # SQLite's batch mode DROPs and recreates the `note` table, which also
    # drops any triggers defined on it (per SQLite semantics) — the FTS5 sync
    # triggers from the baseline migration are casualties of that and must be
    # recreated, otherwise new/edited notes silently stop being indexed for
    # search. Mirrors db/migrations/versions/20260516_0001_baseline.py::_create_fts.
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
        logger.warning("SQLite FTS5 note_fts non presente/disponibile; salto il ripristino dei trigger.")

    op.drop_index("ix_task_project_id", table_name="task")
    op.drop_table("task")


def downgrade() -> None:
    bind = op.get_bind()
    dateless = bind.execute(sa.text(
        "SELECT COUNT(*) FROM milestone WHERE start_date IS NULL OR end_date IS NULL"
    )).scalar()
    if dateless:
        raise RuntimeError(
            f"Impossibile eseguire il downgrade: {dateless} Milestone senza data "
            "(start_date/end_date NULL) non possono tornare NOT NULL senza perdita di dati. "
            "Assegna delle date a tutte le Fasi prima di eseguire il downgrade."
        )

    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("ganttproject.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_task_project_id", "task", ["project_id"])

    with op.batch_alter_table("note") as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.Integer(), nullable=True))

    op.drop_index("ix_milestone_stream_id", table_name="milestone")
    with op.batch_alter_table("milestone") as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.Integer(), nullable=True))
        batch_op.drop_column("stream_id")
        batch_op.alter_column("start_date", existing_type=sa.Date(), nullable=False)
        batch_op.alter_column("end_date", existing_type=sa.Date(), nullable=False)

    op.drop_index("ix_stream_project_id", table_name="stream")
    op.drop_table("stream")
