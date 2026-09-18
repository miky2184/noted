"""Aggiunge la Fase (Phase) come livello tra Stream e Nota: uno Stream può avere
N Fasi, ciascuna con le proprie date; le note si agganciano alla Fase (non più
allo Stream). Migra i dati esistenti: ogni Stream con date/nota di tracking/note
collegate diventa una singola Fase con lo stesso nome, poi lo Stream perde i
campi data/nota (diventa un puro contenitore).

Revision ID: 20260918_0001
Revises: 20260902_0001
Create Date: 2026-09-18
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = '20260918_0001'
down_revision = '20260902_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'phase',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stream_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('note_id', sa.Integer(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_phase_stream_id', 'phase', ['stream_id'])

    conn = op.get_bind()
    meta = sa.MetaData()
    stream = sa.Table('stream', meta, autoload_with=conn)
    phase = sa.Table('phase', meta, autoload_with=conn)
    note = sa.Table('note', meta, autoload_with=conn)

    now = datetime.now()
    streams = conn.execute(
        sa.select(stream.c.id, stream.c.name, stream.c.start_date, stream.c.end_date, stream.c.note_id)
    ).fetchall()
    for s in streams:
        linked_count = conn.execute(
            sa.select(sa.func.count()).select_from(note).where(note.c.milestone_id == s.id)
        ).scalar()
        if not (s.start_date or s.end_date or s.note_id or linked_count):
            continue  # stream vuoto, senza date/nota/note collegate: niente da preservare
        result = conn.execute(
            phase.insert().values(
                stream_id=s.id, name=s.name, start_date=s.start_date, end_date=s.end_date,
                note_id=s.note_id, sort_order=0, created_at=now,
            )
        )
        new_phase_id = result.inserted_primary_key[0]
        conn.execute(
            note.update().where(note.c.milestone_id == s.id).values(milestone_id=new_phase_id)
        )

    with op.batch_alter_table('stream') as batch_op:
        batch_op.drop_column('start_date')
        batch_op.drop_column('end_date')
        batch_op.drop_column('note_id')


def downgrade():
    with op.batch_alter_table('stream') as batch_op:
        batch_op.add_column(sa.Column('start_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('end_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('note_id', sa.Integer(), nullable=True))

    conn = op.get_bind()
    meta = sa.MetaData()
    stream = sa.Table('stream', meta, autoload_with=conn)
    phase = sa.Table('phase', meta, autoload_with=conn)
    note = sa.Table('note', meta, autoload_with=conn)

    # Downgrade con perdita di dati se uno stream ha più di una fase: vince
    # l'ultima incontrata. Accettabile per un rollback di emergenza.
    phases = conn.execute(
        sa.select(phase.c.id, phase.c.stream_id, phase.c.start_date, phase.c.end_date, phase.c.note_id)
    ).fetchall()
    for ph in phases:
        conn.execute(
            stream.update().where(stream.c.id == ph.stream_id).values(
                start_date=ph.start_date, end_date=ph.end_date, note_id=ph.note_id,
            )
        )
        conn.execute(
            note.update().where(note.c.milestone_id == ph.id).values(milestone_id=ph.stream_id)
        )

    op.drop_index('ix_phase_stream_id', table_name='phase')
    op.drop_table('phase')
