"""remove old Stream grouping entity, rename Milestone -> Stream, add GanttProject dates

Revision ID: 20260901_0001
Revises: 20260831_0005
Create Date: 2026-09-01

User feedback: the old "Stream" table (a work-initiative grouping container
nested inside a project, holding N "Fasi"/Milestone) added a confusing extra
nesting level nobody could place mentally. The simplified model is flat:

    Cliente -> 1..N Progetto -> 1..N Stream -> 1..N Nota

...where "Stream" is exactly the old "Fase"/Milestone concept (name + optional
start/end dates, renders as a timeline bar once both are set, groups notes),
just renamed and no longer nestable under anything else. The project itself
gains its own optional start_date/end_date (e.g. "settembre - gennaio").

Migration path (data-preserving):
- `milestone.stream_id` (link to the OLD Stream) is nulled out and dropped —
  every existing Fase becomes a direct child of its project, which is exactly
  where it already conceptually lived (root Fasi were already stream_id=NULL;
  the handful nested under a Stream just lose that grouping, nothing else
  changes about them: same name, dates, linked notes, note_id).
- The old `stream` table is dropped once nothing references it.
- `milestone` is renamed to `stream` — SQLite (>= 3.25.2) automatically
  rewrites the stored foreign key text of dependent tables (note.milestone_id)
  to point at the new table name, so `note` itself is never touched by this
  migration and its FTS5 sync triggers are unaffected (unlike the batch-mode
  column changes in 20260831_0002/0004, which had to recreate them).
- `ganttproject.start_date`/`end_date` are pure additions, nullable, no
  backfill needed.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260901_0001'
down_revision = '20260831_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Drop the old Stream grouping entity: unlink every Fase from it first
    # (harmless — the Fase itself, its dates and its notes are untouched),
    # then drop the now-orphan column/index, then the table.
    bind.execute(sa.text("UPDATE milestone SET stream_id = NULL"))
    op.drop_index("ix_milestone_stream_id", table_name="milestone")
    with op.batch_alter_table("milestone") as batch_op:
        batch_op.drop_column("stream_id")
    op.drop_index("ix_stream_project_id", table_name="stream")
    op.drop_table("stream")

    # "Fase" (Milestone) becomes "Stream" — a plain rename, no column changes,
    # so `note` (and its FTS triggers) are never touched by this step.
    op.rename_table("milestone", "stream")

    # Il progetto ora può avere un proprio periodo (es. "settembre - gennaio"),
    # indipendente dalle date dei singoli Stream al suo interno.
    op.add_column("ganttproject", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("ganttproject", sa.Column("end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("ganttproject", "end_date")
    op.drop_column("ganttproject", "start_date")

    op.rename_table("stream", "milestone")

    op.create_table(
        "stream",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("ganttproject.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stream_project_id", "stream", ["project_id"])

    with op.batch_alter_table("milestone") as batch_op:
        batch_op.add_column(sa.Column("stream_id", sa.Integer(), nullable=True))
    op.create_index("ix_milestone_stream_id", "milestone", ["stream_id"])
