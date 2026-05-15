from datetime import date, datetime, timedelta
from typing import Optional
from sqlmodel import Session, select
from db.models import Note, Recap


# ── Notes ──────────────────────────────────────────────────────────────────────

def add_note(
    session: Session,
    content: str,
    tags: str = "",
    project: Optional[str] = None,
    priority: str = "medium",
    due_date: Optional[date] = None,
    status: Optional[str] = None,
) -> Note:
    note = Note(content=content, tags=tags, project=project, priority=priority, due_date=due_date, status=status)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def get_notes(
    session: Session,
    day: Optional[date] = None,
    tag: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
) -> list[Note]:
    stmt = select(Note)

    if day:
        start = datetime.combine(day, datetime.min.time())
        end = datetime.combine(day, datetime.max.time())
        stmt = stmt.where(Note.created_at >= start, Note.created_at <= end)

    if tag:
        stmt = stmt.where(Note.tags.ilike(f"%{tag}%"))

    if project:
        stmt = stmt.where(Note.project.ilike(project))

    if priority:
        stmt = stmt.where(Note.priority == priority)

    stmt = stmt.order_by(Note.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


def get_notes_for_recap(session: Session, day: Optional[date] = None) -> list[Note]:
    return get_notes(session, day=day or date.today(), limit=200)


def edit_note(
    session: Session,
    note_id: int,
    content: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[date] = None,
    clear_due: bool = False,
    status: Optional[str] = None,
    clear_status: bool = False,
) -> Optional[Note]:
    note = session.get(Note, note_id)
    if not note:
        return None
    if content is not None:
        note.content = content
    if priority is not None:
        note.priority = priority
    if clear_due:
        note.due_date = None
    elif due_date is not None:
        note.due_date = due_date
    if clear_status:
        note.status = None
    elif status is not None:
        note.status = status
    note.updated_at = datetime.now()
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def delete_note(session: Session, note_id: int) -> bool:
    note = session.get(Note, note_id)
    if not note:
        return False
    session.delete(note)
    session.commit()
    return True


def get_due_notes(session: Session) -> list[Note]:
    """Note con scadenza impostata e status != done, ordinate per due_date ASC."""
    from sqlalchemy import or_, null
    stmt = (
        select(Note)
        .where(Note.due_date.isnot(None))
        .where(or_(Note.status.is_(None), Note.status != 'done'))
        .order_by(Note.due_date.asc())
    )
    return session.exec(stmt).all()


def search_notes(session: Session, query: str, limit: int = 30) -> list[Note]:
    stmt = (
        select(Note)
        .where(Note.content.ilike(f"%{query}%"))
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    return session.exec(stmt).all()


# ── Recaps ─────────────────────────────────────────────────────────────────────

def save_recap(session: Session, summary: str, notes_count: int, recap_date: Optional[date] = None) -> Recap:
    recap = Recap(recap_date=recap_date or date.today(), summary=summary, notes_count=notes_count)
    session.add(recap)
    session.commit()
    session.refresh(recap)
    return recap


def get_recap(session: Session, day: Optional[date] = None) -> Optional[Recap]:
    target = day or date.today()
    stmt = select(Recap).where(Recap.recap_date == target).order_by(Recap.created_at.desc())
    return session.exec(stmt).first()


def delete_recap(session: Session, recap_id: int) -> bool:
    recap = session.get(Recap, recap_id)
    if not recap:
        return False
    session.delete(recap)
    session.commit()
    return True


def get_recent_recaps(session: Session, days: int = 7) -> list[Recap]:
    since = date.today() - timedelta(days=days)
    stmt = select(Recap).where(Recap.recap_date >= since).order_by(Recap.recap_date.desc())
    return session.exec(stmt).all()
