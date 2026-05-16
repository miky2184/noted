from datetime import date, datetime, timedelta
from typing import Optional
from sqlmodel import Session, select
from sqlalchemy import or_, delete as sa_delete
from db.models import Note, Recap, GanttProject, Milestone, Context, NoteDependency


# ── Context ────────────────────────────────────────────────────────────────────

def get_contexts(session: Session) -> list[Context]:
    return session.exec(select(Context).order_by(Context.created_at.asc())).all()

def add_context(session: Session, name: str) -> Context:
    ctx = Context(name=name.strip().lower())
    session.add(ctx)
    session.commit()
    session.refresh(ctx)
    return ctx

def rename_context(session: Session, ctx_id: int, new_name: str) -> Optional[Context]:
    ctx = session.get(Context, ctx_id)
    if not ctx:
        return None
    old_name = ctx.name
    ctx.name = new_name
    session.add(ctx)
    # cascade rename on all related rows
    for model, col in [("note", "context"), ("recap", "context"), ("ganttproject", "context")]:
        from sqlalchemy import text
        session.execute(
            text(f"UPDATE {model} SET {col} = :new WHERE {col} = :old"),
            {"new": new_name, "old": old_name},
        )
    session.commit()
    session.refresh(ctx)
    return ctx

def delete_context(session: Session, ctx_id: int) -> bool:
    ctx = session.get(Context, ctx_id)
    if not ctx or ctx.name == "default":
        return False
    ctx_name = ctx.name
    # Cascade: delete milestones → gantt projects → recaps → notes
    project_ids = session.exec(
        select(GanttProject.id).where(GanttProject.context == ctx_name)
    ).all()
    if project_ids:
        session.exec(sa_delete(Milestone).where(Milestone.project_id.in_(project_ids)))
    session.exec(sa_delete(GanttProject).where(GanttProject.context == ctx_name))
    session.exec(sa_delete(Recap).where(Recap.context == ctx_name))
    session.exec(sa_delete(Note).where(Note.context == ctx_name))
    session.delete(ctx)
    session.commit()
    return True


# ── Notes ──────────────────────────────────────────────────────────────────────

def add_note(
    session: Session,
    content: str,
    tags: str = "",
    project: Optional[str] = None,
    priority: str = "medium",
    due_date: Optional[date] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    ctx: str = "default",
) -> Note:
    note = Note(content=content, tags=tags, project=project, priority=priority,
                due_date=due_date, status=status, assignee=assignee, context=ctx)
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
    assignee: Optional[str] = None,
    status: Optional[str] = None,
    ctx: str = "default",
    limit: int = 50,
) -> list[Note]:
    stmt = select(Note).where(Note.context == ctx)

    if day:
        start = datetime.combine(day, datetime.min.time())
        end = datetime.combine(day, datetime.max.time())
        stmt = stmt.where(Note.created_at >= start, Note.created_at <= end)

    if tag:
        stmt = stmt.where(or_(
            Note.tags == tag,
            Note.tags.ilike(f"{tag},%"),
            Note.tags.ilike(f"%,{tag}"),
            Note.tags.ilike(f"%,{tag},%"),
        ))
    if project:
        stmt = stmt.where(Note.project.ilike(project))
    if priority:
        stmt = stmt.where(Note.priority == priority)
    if assignee:
        stmt = stmt.where(Note.assignee.ilike(f"%{assignee}%"))
    if status:
        stmt = stmt.where(Note.status == status)

    stmt = stmt.order_by(Note.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


def get_notes_for_recap(session: Session, day: Optional[date] = None, ctx: str = "default") -> list[Note]:
    return get_notes(session, day=day or date.today(), ctx=ctx, limit=200)


def edit_note(
    session: Session,
    note_id: int,
    content: Optional[str] = None,
    tags: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[date] = None,
    clear_due: bool = False,
    status: Optional[str] = None,
    clear_status: bool = False,
    assignee: Optional[str] = None,
    clear_assignee: bool = False,
) -> Optional[Note]:
    note = session.get(Note, note_id)
    if not note:
        return None
    if content is not None:
        note.content = content
    if tags is not None:
        note.tags = tags
    if project is not None:
        note.project = project or None
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
    if clear_assignee:
        note.assignee = None
    elif assignee is not None:
        note.assignee = assignee if assignee else None
    note.updated_at = datetime.now()
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def get_board_notes(
    session: Session,
    project: Optional[str] = None,
    assignee: Optional[str] = None,
    ctx: str = "default",
) -> list[Note]:
    stmt = select(Note).where(Note.status.isnot(None), Note.context == ctx)
    if project:
        stmt = stmt.where(Note.project.ilike(f"%{project}%"))
    if assignee:
        stmt = stmt.where(Note.assignee.ilike(f"%{assignee}%"))
    stmt = stmt.order_by(Note.sort_order.asc(), Note.created_at.desc()).limit(500)
    return session.exec(stmt).all()


def get_inbox_notes(
    session: Session,
    days: int = 7,
    project: Optional[str] = None,
    assignee: Optional[str] = None,
    ctx: str = "default",
    limit: int = 50,
) -> list[Note]:
    since = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    stmt = (
        select(Note)
        .where(Note.status.is_(None), Note.context == ctx)
        .where(Note.created_at >= since)
    )
    if project:
        stmt = stmt.where(Note.project.ilike(f"%{project}%"))
    if assignee:
        stmt = stmt.where(Note.assignee.ilike(f"%{assignee}%"))
    stmt = stmt.order_by(Note.sort_order.asc(), Note.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


def get_notes_last_n_days(session: Session, days: int = 7, ctx: str = "default") -> list[Note]:
    since = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    stmt = (
        select(Note)
        .where(Note.created_at >= since, Note.context == ctx)
        .order_by(Note.created_at.asc())
        .limit(1000)
    )
    return session.exec(stmt).all()


def delete_note(session: Session, note_id: int) -> bool:
    note = session.get(Note, note_id)
    if not note:
        return False
    session.delete(note)
    session.commit()
    return True


def get_due_notes(session: Session, ctx: str = "default") -> list[Note]:
    from sqlalchemy import or_
    stmt = (
        select(Note)
        .where(Note.due_date.isnot(None), Note.context == ctx)
        .where(or_(Note.status.is_(None), Note.status != 'done'))
        .order_by(Note.due_date.asc())
    )
    return session.exec(stmt).all()


def search_notes(session: Session, query: str, ctx: str = "default", limit: int = 30) -> list[Note]:
    stmt = (
        select(Note)
        .where(Note.content.ilike(f"%{query}%"), Note.context == ctx)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    return session.exec(stmt).all()


# ── Recaps ─────────────────────────────────────────────────────────────────────

def save_recap(session: Session, summary: str, notes_count: int,
               recap_date: Optional[date] = None, ctx: str = "default") -> Recap:
    recap = Recap(recap_date=recap_date or date.today(), summary=summary,
                  notes_count=notes_count, context=ctx)
    session.add(recap)
    session.commit()
    session.refresh(recap)
    return recap


def get_recap(session: Session, day: Optional[date] = None, ctx: str = "default") -> Optional[Recap]:
    target = day or date.today()
    stmt = (select(Recap)
            .where(Recap.recap_date == target, Recap.context == ctx)
            .order_by(Recap.created_at.desc()))
    return session.exec(stmt).first()


def delete_recap(session: Session, recap_id: int) -> bool:
    recap = session.get(Recap, recap_id)
    if not recap:
        return False
    session.delete(recap)
    session.commit()
    return True


def get_recent_recaps(session: Session, days: int = 90, ctx: str = "default") -> list[Recap]:
    since = date.today() - timedelta(days=days)
    stmt = (select(Recap)
            .where(Recap.recap_date >= since, Recap.context == ctx)
            .order_by(Recap.recap_date.desc(), Recap.created_at.desc())
            .limit(50))
    return session.exec(stmt).all()


# ── Gantt ──────────────────────────────────────────────────────────────────────

def get_gantt_projects(session: Session, ctx: str = "default") -> list[GanttProject]:
    return session.exec(
        select(GanttProject).where(GanttProject.context == ctx).order_by(GanttProject.created_at.asc())
    ).all()

def get_milestones(session: Session, project_id: int) -> list[Milestone]:
    return session.exec(
        select(Milestone).where(Milestone.project_id == project_id).order_by(Milestone.start_date.asc())
    ).all()

def add_gantt_project(session: Session, name: str, color: str = "#818cf8", ctx: str = "default", is_background: bool = False) -> GanttProject:
    p = GanttProject(name=name, color=color, context=ctx, is_background=is_background)
    session.add(p); session.commit(); session.refresh(p)
    return p

def edit_gantt_project(session: Session, project_id: int, name: Optional[str] = None, color: Optional[str] = None, is_background: Optional[bool] = None) -> Optional[GanttProject]:
    p = session.get(GanttProject, project_id)
    if not p: return None
    if name is not None: p.name = name
    if color is not None: p.color = color
    if is_background is not None: p.is_background = is_background
    session.add(p); session.commit(); session.refresh(p)
    return p

def delete_gantt_project(session: Session, project_id: int) -> bool:
    p = session.get(GanttProject, project_id)
    if not p: return False
    for m in session.exec(select(Milestone).where(Milestone.project_id == project_id)).all():
        session.delete(m)
    session.delete(p); session.commit()
    return True

def add_milestone(session: Session, project_id: int, name: str, start_date: date, end_date: date) -> Milestone:
    m = Milestone(project_id=project_id, name=name, start_date=start_date, end_date=end_date)
    session.add(m); session.commit(); session.refresh(m)
    return m

def edit_milestone(session: Session, milestone_id: int, name: Optional[str] = None, start_date: Optional[date] = None, end_date: Optional[date] = None) -> Optional[Milestone]:
    m = session.get(Milestone, milestone_id)
    if not m: return None
    if name is not None: m.name = name
    if start_date is not None: m.start_date = start_date
    if end_date is not None: m.end_date = end_date
    session.add(m); session.commit(); session.refresh(m)
    return m

def delete_milestone(session: Session, milestone_id: int) -> bool:
    m = session.get(Milestone, milestone_id)
    if not m: return False
    session.delete(m); session.commit()
    return True

# ── Note Dependencies ──────────────────────────────────────────────────────────

def add_dependency(session: Session, note_id: int, blocker_id: int) -> Optional[NoteDependency]:
    if note_id == blocker_id:
        return None
    if not session.get(Note, note_id) or not session.get(Note, blocker_id):
        return None
    existing = session.exec(
        select(NoteDependency).where(NoteDependency.note_id == note_id, NoteDependency.blocker_id == blocker_id)
    ).first()
    if existing:
        return existing
    dep = NoteDependency(note_id=note_id, blocker_id=blocker_id)
    session.add(dep)
    session.commit()
    session.refresh(dep)
    return dep

def remove_dependency(session: Session, note_id: int, blocker_id: int) -> bool:
    dep = session.exec(
        select(NoteDependency).where(NoteDependency.note_id == note_id, NoteDependency.blocker_id == blocker_id)
    ).first()
    if not dep:
        return False
    session.delete(dep)
    session.commit()
    return True

def get_blockers(session: Session, note_id: int) -> list[Note]:
    """Note che bloccano note_id."""
    ids = session.exec(select(NoteDependency.blocker_id).where(NoteDependency.note_id == note_id)).all()
    if not ids:
        return []
    return session.exec(select(Note).where(Note.id.in_(ids))).all()

def get_blocking(session: Session, note_id: int) -> list[Note]:
    """Note bloccate da note_id."""
    ids = session.exec(select(NoteDependency.note_id).where(NoteDependency.blocker_id == note_id)).all()
    if not ids:
        return []
    return session.exec(select(Note).where(Note.id.in_(ids))).all()

def get_deps_bulk(session: Session, note_ids: list[int]) -> dict:
    """Ritorna {note_id: {blockers: [...], blocking: [...]}} per una lista di note."""
    if not note_ids:
        return {}
    all_deps = session.exec(
        select(NoteDependency).where(
            or_(NoteDependency.note_id.in_(note_ids), NoteDependency.blocker_id.in_(note_ids))
        )
    ).all()
    result = {nid: {"blockers": [], "blocking": []} for nid in note_ids}
    blocker_ids = set()
    blocking_ids = set()
    for d in all_deps:
        if d.note_id in result:
            result[d.note_id]["blockers"].append(d.blocker_id)
            blocker_ids.add(d.blocker_id)
        if d.blocker_id in result:
            result[d.blocker_id]["blocking"].append(d.note_id)
            blocking_ids.add(d.note_id)
    # Fetch note summaries for tooltip
    all_ref_ids = blocker_ids | blocking_ids
    if all_ref_ids:
        ref_notes = {n.id: n for n in session.exec(select(Note).where(Note.id.in_(all_ref_ids))).all()}
        for nid, data in result.items():
            data["blocker_notes"] = [
                {"id": rid, "content": ref_notes[rid].content[:60], "status": ref_notes[rid].status}
                for rid in data["blockers"] if rid in ref_notes
            ]
            data["blocking_notes"] = [
                {"id": rid, "content": ref_notes[rid].content[:60], "status": ref_notes[rid].status}
                for rid in data["blocking"] if rid in ref_notes
            ]
    return result


# ── Gantt ──────────────────────────────────────────────────────────────────────

def get_gantt_data(session: Session, ctx: str = "default") -> dict:
    from sqlalchemy import text as sa_text
    projects = get_gantt_projects(session, ctx=ctx)

    # IDs of notes that are actual blockers of something (appear as blocker_id in NoteDependency)
    blocker_ids_in_use: set[int] = set(
        session.exec(select(NoteDependency.blocker_id)).all()
    )

    result = []
    for p in projects:
        milestones = get_milestones(session, p.id)
        notes_with_due = session.exec(
            select(Note)
            .where(Note.due_date.isnot(None), Note.context == ctx)
            .where(Note.project.ilike(p.name))
            .where(~(Note.tags == "milestone"))
            .where(~Note.tags.ilike("milestone,%"))
            .where(~Note.tags.ilike("%,milestone"))
            .where(~Note.tags.ilike("%,milestone,%"))
        ).all()

        # All notes of this project (to check risk)
        all_proj_notes = session.exec(
            select(Note).where(Note.context == ctx, Note.project.ilike(p.name))
        ).all()

        # A project has a risk blocker if any of its notes is:
        # - in a blocking status AND is itself a blocker of another note (has dependents)
        has_risk_blocker = any(
            n.status in ("blocked", "waiting", "backlog") and n.id in blocker_ids_in_use
            for n in all_proj_notes
        )

        result.append({
            "id": p.id,
            "name": p.name,
            "color": p.color,
            "is_background": p.is_background,
            "has_risk_blocker": has_risk_blocker,
            "milestones": [
                {"id": m.id, "name": m.name, "start_date": str(m.start_date), "end_date": str(m.end_date)}
                for m in milestones
            ],
            "notes": [
                {"id": n.id, "content": n.content, "due_date": str(n.due_date), "status": n.status,
                 "assignee": n.assignee, "created_at": n.created_at.date().isoformat()}
                for n in notes_with_due
            ]
        })
    return {"projects": result}
