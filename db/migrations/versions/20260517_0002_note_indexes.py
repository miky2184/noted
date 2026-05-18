"""note: indici su context, status, created_at

Revision ID: 20260517_0002
Revises: 20260516_0001
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = "20260517_0002"
down_revision = "20260516_0001"
branch_labels = None
depends_on = None


def _index_names(bind) -> set[str]:
    insp = sa.inspect(bind)
    names: set[str] = set()
    for idx in insp.get_indexes("note"):
        names.add(idx["name"])
    return names


def upgrade() -> None:
    bind = op.get_bind()
    existing = _index_names(bind)

    if "ix_note_context" not in existing:
        op.create_index("ix_note_context", "note", ["context"])

    if "ix_note_status" not in existing:
        op.create_index("ix_note_status", "note", ["status"])

    if "ix_note_created_at" not in existing:
        op.create_index("ix_note_created_at", "note", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_note_created_at", table_name="note")
    op.drop_index("ix_note_status", table_name="note")
    op.drop_index("ix_note_context", table_name="note")
