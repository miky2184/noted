"""add Client and Task, link GanttProject/Note/Milestone, backfill from existing data

Revision ID: 20260831_0001
Revises: 20260519_0001
Create Date: 2026-08-31

Adds the Cliente -> Progetto -> Task -> Nota hierarchy: a new `client` table
(1 client -> N GanttProject) and a new `task` table (1 GanttProject -> N Task
-> N Note), plus optional `task_id` on Milestone so a milestone can point at
the task it belongs to.

Backfill: for every existing (non-background) GanttProject, create a single
"Generale" Task and assign it (via note.task_id) to every Note whose free-text
`project` field matches the project's name — the exact same matching used at
runtime by db.crud.get_gantt_data today (case-insensitive, same context).
This is what gives historical data a real, non-zero progress % immediately
instead of starting from scratch. The backfill is idempotent (guarded by
`WHERE task_id IS NULL` / `NOT EXISTS`) because `db.engine.init_db()` runs
`alembic upgrade head` on every app startup, not just once at deploy time.

Downgrade is destructive: task assignments (note.task_id, milestone.task_id)
and the "Generale" tasks themselves are lost, not just hidden.
"""
import logging

from alembic import op
import sqlalchemy as sa

revision = '20260831_0001'
down_revision = '20260519_0001'
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.create_table(
        "client",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("context", sa.String(), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_client_context", "client", ["context"])

    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("ganttproject.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_task_project_id", "task", ["project_id"])

    with op.batch_alter_table("ganttproject") as batch_op:
        batch_op.add_column(sa.Column("client_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("note") as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("milestone") as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.Integer(), nullable=True))

    op.create_index("ix_ganttproject_client_id", "ganttproject", ["client_id"])
    op.create_index("ix_note_task_id", "note", ["task_id"])
    op.create_index("ix_milestone_task_id", "milestone", ["task_id"])

    # ── Backfill (must run after every column/table above exists, and
    # outside any batch_alter_table block) ─────────────────────────────────
    bind = op.get_bind()

    bind.execute(sa.text("""
        INSERT INTO task (project_id, name, created_at)
        SELECT p.id, 'Generale', CURRENT_TIMESTAMP
        FROM ganttproject p
        WHERE p.is_background = 0
          AND NOT EXISTS (
              SELECT 1 FROM task t WHERE t.project_id = p.id AND t.name = 'Generale'
          )
    """))

    bind.execute(sa.text("""
        UPDATE note
        SET task_id = (
            SELECT t.id FROM task t
            JOIN ganttproject p ON p.id = t.project_id
            WHERE t.name = 'Generale'
              AND LOWER(p.name) = LOWER(note.project)
              AND p.context = note.context
            LIMIT 1
        )
        WHERE task_id IS NULL
          AND project IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM ganttproject p2
              WHERE LOWER(p2.name) = LOWER(note.project)
                AND p2.context = note.context
                AND p2.is_background = 0
          )
    """))

    dupes = bind.execute(sa.text("""
        SELECT LOWER(name), context, COUNT(*) FROM ganttproject
        GROUP BY LOWER(name), context HAVING COUNT(*) > 1
    """)).fetchall()
    if dupes:
        logger.warning(
            "Gantt backfill: trovati progetti con nome duplicato (case-insensitive) "
            "nello stesso contesto — le note storiche potrebbero essere state assegnate "
            "al 'Generale' di uno solo dei duplicati: %s", dupes,
        )


def downgrade() -> None:
    op.drop_index("ix_milestone_task_id", table_name="milestone")
    op.drop_index("ix_note_task_id", table_name="note")
    op.drop_index("ix_ganttproject_client_id", table_name="ganttproject")

    with op.batch_alter_table("milestone") as batch_op:
        batch_op.drop_column("task_id")
    with op.batch_alter_table("note") as batch_op:
        batch_op.drop_column("task_id")
    with op.batch_alter_table("ganttproject") as batch_op:
        batch_op.drop_column("client_id")

    op.drop_index("ix_task_project_id", table_name="task")
    op.drop_table("task")
    op.drop_index("ix_client_context", table_name="client")
    op.drop_table("client")
