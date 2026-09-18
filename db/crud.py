from datetime import date, datetime, timedelta
from typing import Optional
from sqlmodel import Session, select
from sqlalchemy import or_, and_, delete as sa_delete, update as sa_update, text
from db.models import Note, Recap, GanttProject, Context, NoteDependency, Document, Client, Stream, Phase, Absence


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
    # Cascade: delete streams → gantt projects → recaps → notes
    project_ids = session.exec(
        select(GanttProject.id).where(GanttProject.context == ctx_name)
    ).all()
    if project_ids:
        session.exec(sa_delete(Stream).where(Stream.project_id.in_(project_ids)))
    session.exec(sa_delete(GanttProject).where(GanttProject.context == ctx_name))
    session.exec(sa_delete(Recap).where(Recap.context == ctx_name))
    session.exec(sa_delete(Note).where(Note.context == ctx_name))
    session.delete(ctx)
    session.commit()
    return True


# ── Notes ──────────────────────────────────────────────────────────────────────

_GANTT_COLORS = ["#818cf8", "#60a5fa", "#34d399", "#fbbf24", "#f87171",
                  "#a78bfa", "#fb923c", "#2dd4bf", "#f472b6", "#a3e635"]


def _color_for(name: str) -> str:
    return _GANTT_COLORS[sum(ord(c) for c in name) % len(_GANTT_COLORS)]


def _sync_project_client_from_note(session: Session, project: Optional[str], cliente: Optional[str], ctx: str) -> None:
    """La nota è la fonte di verità per "di chi è" un progetto: se porta sia
    `project` sia `cliente`, crea il GanttProject corrispondente se non esiste
    ancora e lo collega al Client (creandolo se serve) — niente più setup
    manuale nel Gantt, basta scrivere la nota."""
    if not project or not cliente:
        return
    proj = session.exec(
        select(GanttProject).where(GanttProject.context == ctx, GanttProject.name.ilike(project))
    ).first()
    if not proj:
        # Non creare un progetto "fantasma" per un gruppo di note ormai tutte
        # concluse (es. nota storica già "done" alla creazione, o richiamata
        # dalla riconciliazione su dati vecchi) — se il lavoro viene riaperto,
        # riportare una nota a uno stato non-done farà scattare la creazione
        # al giro successivo. Un progetto già esistente che finisce tutte le
        # sue note nel tempo resta invece da archiviare manualmente: non va
        # fatto sparire da solo senza che l'utente se ne accorga.
        statuses = session.exec(
            select(Note.status).where(
                Note.context == ctx,
                Note.project.ilike(project),
                Note.cliente.ilike(cliente),
            )
        ).all()
        if statuses and all(s == "done" for s in statuses):
            return
        proj = GanttProject(name=project, color=_color_for(project), context=ctx)
        session.add(proj)
        session.commit()
        session.refresh(proj)
    client = session.exec(
        select(Client).where(Client.context == ctx, Client.name.ilike(cliente))
    ).first()
    if not client:
        client = Client(name=cliente, context=ctx)
        session.add(client)
        session.commit()
        session.refresh(client)
    if proj.client_id != client.id:
        proj.client_id = client.id
        session.add(proj)
        session.commit()


def add_note(
    session: Session,
    content: str,
    tags: str = "",
    cliente: Optional[str] = None,
    project: Optional[str] = None,
    priority: str = "medium",
    start_date: Optional[date] = None,
    due_date: Optional[date] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    ctx: str = "default",
    milestone_id: Optional[int] = None,
    stream_id: Optional[int] = None,
) -> Note:
    # milestone_id (Fase) e stream_id (Stream diretto) sono mutuamente esclusivi:
    # una nota è "dentro" una Fase oppure fa lei stessa da fase per uno Stream.
    if stream_id is not None:
        milestone_id = None
    note = Note(content=content, tags=tags, cliente=cliente, project=project, priority=priority,
                start_date=start_date, due_date=due_date, status=status, assignee=assignee,
                context=ctx, milestone_id=milestone_id, stream_id=stream_id)
    session.add(note)
    session.commit()
    session.refresh(note)
    _sync_project_client_from_note(session, note.project, note.cliente, ctx)
    # _sync_project_client_from_note may have committed again (creating the
    # Client / updating the GanttProject), which expires `note`'s attributes
    # (expire_on_commit) — refresh once more so it's safe to read after the
    # caller's `with get_session()` block has already closed.
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

    # Le note di tracking auto-create per una Fase (v. add_phase) sono già
    # rappresentate dalla barra della Fase stessa nel Gantt — non devono
    # comparire nella lista note "vere" (a meno che non le si cerchi
    # esplicitamente per tag, es. per debug).
    if tag != "milestone":
        stmt = _exclude_milestone_tag(stmt)

    stmt = stmt.order_by(Note.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


def get_notes_for_recap(session: Session, day: Optional[date] = None, ctx: str = "default") -> list[Note]:
    return get_notes(session, day=day or date.today(), ctx=ctx, limit=200)


def edit_note(
    session: Session,
    note_id: int,
    content: Optional[str] = None,
    tags: Optional[str] = None,
    cliente: Optional[str] = None,
    clear_cliente: bool = False,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    start_date: Optional[date] = None,
    clear_start: bool = False,
    due_date: Optional[date] = None,
    clear_due: bool = False,
    status: Optional[str] = None,
    clear_status: bool = False,
    assignee: Optional[str] = None,
    clear_assignee: bool = False,
    milestone_id: Optional[int] = None,
    clear_milestone: bool = False,
    stream_id: Optional[int] = None,
    clear_stream_id: bool = False,
    ctx: Optional[str] = None,
) -> Optional[Note]:
    note = session.get(Note, note_id)
    if not note:
        return None
    if ctx is not None and note.context != ctx:
        return None
    if content is not None:
        note.content = content
    if tags is not None:
        note.tags = tags
    if clear_cliente:
        note.cliente = None
    elif cliente is not None:
        note.cliente = cliente or None
    if project is not None:
        note.project = project or None
    if priority is not None:
        note.priority = priority
    if clear_start:
        note.start_date = None
    elif start_date is not None:
        note.start_date = start_date
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
    # milestone_id (Fase) e stream_id (Stream diretto) sono mutuamente esclusivi:
    # collegarne uno scollega l'altro, così una nota ha sempre una sola
    # collocazione nel Gantt.
    if clear_milestone:
        note.milestone_id = None
    elif milestone_id is not None:
        note.milestone_id = milestone_id
        note.stream_id = None
    if clear_stream_id:
        note.stream_id = None
    elif stream_id is not None:
        note.stream_id = stream_id
        note.milestone_id = None
    note.updated_at = datetime.now()
    session.add(note)
    session.commit()
    session.refresh(note)
    _sync_project_client_from_note(session, note.project, note.cliente, note.context)
    session.refresh(note)  # vedi commento in add_note: il sync può aver committato di nuovo
    return note


def _exclude_milestone_tag(stmt):
    """Le note taggate "milestone" sono la nota di tracking auto-creata per uno
    Stream (v. add_stream) — sono già rappresentate dalla barra dello Stream
    stesso nel Gantt e non devono comparire come note "vere" altrove (Board,
    Attività, lista note-con-scadenza di un progetto)."""
    return stmt.where(
        ~(Note.tags == "milestone"),
        ~Note.tags.ilike("milestone,%"),
        ~Note.tags.ilike("%,milestone"),
        ~Note.tags.ilike("%,milestone,%"),
    )


def get_board_notes(
    session: Session,
    project: Optional[str] = None,
    cliente: Optional[str] = None,
    assignee: Optional[str] = None,
    tag: Optional[str] = None,
    priority: Optional[str] = None,
    query: Optional[str] = None,
    created_today: bool = False,
    due_filter: Optional[str] = None,
    no_project: bool = False,
    no_cliente: bool = False,
    no_tag: bool = False,
    milestone_id: Optional[int] = None,
    stream_id: Optional[int] = None,
    ctx: str = "default",
) -> list[Note]:
    stmt = select(Note).where(Note.status.isnot(None), Note.context == ctx)
    stmt = _exclude_milestone_tag(stmt)
    stmt = _apply_board_filters(stmt, project, cliente, assignee, tag, priority, query, created_today, due_filter, no_project, no_cliente, no_tag, milestone_id, stream_id)
    stmt = stmt.order_by(Note.sort_order.asc(), Note.created_at.desc()).limit(500)
    return session.exec(stmt).all()


def get_inbox_notes(
    session: Session,
    days: int = 7,
    project: Optional[str] = None,
    cliente: Optional[str] = None,
    assignee: Optional[str] = None,
    tag: Optional[str] = None,
    priority: Optional[str] = None,
    query: Optional[str] = None,
    created_today: bool = False,
    due_filter: Optional[str] = None,
    no_project: bool = False,
    no_cliente: bool = False,
    no_tag: bool = False,
    milestone_id: Optional[int] = None,
    stream_id: Optional[int] = None,
    ctx: str = "default",
    limit: int = 50,
) -> list[Note]:
    since = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    stmt = (
        select(Note)
        .where(Note.status.is_(None), Note.context == ctx)
        .where(Note.created_at >= since)
    )
    stmt = _exclude_milestone_tag(stmt)
    stmt = _apply_board_filters(stmt, project, cliente, assignee, tag, priority, query, created_today, due_filter, no_project, no_cliente, no_tag, milestone_id, stream_id)
    stmt = stmt.order_by(Note.sort_order.asc(), Note.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


def _apply_board_filters(
    stmt,
    project: Optional[str] = None,
    cliente: Optional[str] = None,
    assignee: Optional[str] = None,
    tag: Optional[str] = None,
    priority: Optional[str] = None,
    query: Optional[str] = None,
    created_today: bool = False,
    due_filter: Optional[str] = None,
    no_project: bool = False,
    no_cliente: bool = False,
    no_tag: bool = False,
    milestone_id: Optional[int] = None,
    stream_id: Optional[int] = None,
):
    if milestone_id is not None:
        stmt = stmt.where(Note.milestone_id == milestone_id)
    if stream_id is not None:
        stmt = stmt.where(Note.stream_id == stream_id)
    if no_project:
        stmt = stmt.where(or_(Note.project.is_(None), Note.project == ""))
    elif project:
        stmt = stmt.where(Note.project.ilike(f"%{project}%"))
    if no_cliente:
        stmt = stmt.where(or_(Note.cliente.is_(None), Note.cliente == ""))
    elif cliente:
        stmt = stmt.where(Note.cliente.ilike(f"%{cliente}%"))
    if assignee:
        stmt = stmt.where(Note.assignee.ilike(f"%{assignee.lstrip('@')}%"))
    if no_tag:
        stmt = stmt.where(or_(Note.tags.is_(None), Note.tags == ""))
    elif tag:
        tag = tag.lstrip("#")
        stmt = stmt.where(or_(
            Note.tags == tag,
            Note.tags.ilike(f"{tag},%"),
            Note.tags.ilike(f"%,{tag}"),
            Note.tags.ilike(f"%,{tag},%"),
        ))
    if priority:
        stmt = stmt.where(Note.priority == priority)
    if query:
        q = f"%{query}%"
        stmt = stmt.where(or_(
            Note.content.ilike(q),
            Note.tags.ilike(q),
            Note.project.ilike(q),
            Note.assignee.ilike(q),
        ))
    if created_today:
        start = datetime.combine(date.today(), datetime.min.time())
        end = datetime.combine(date.today(), datetime.max.time())
        stmt = stmt.where(Note.created_at >= start, Note.created_at <= end)
    if due_filter == "has":
        stmt = stmt.where(Note.due_date.isnot(None))
    elif due_filter == "none":
        stmt = stmt.where(Note.due_date.is_(None))
    elif due_filter == "overdue":
        stmt = stmt.where(Note.due_date.isnot(None), Note.due_date < date.today())
    elif due_filter == "today":
        stmt = stmt.where(Note.due_date == date.today())
    elif due_filter == "week":
        stmt = stmt.where(Note.due_date.isnot(None), Note.due_date >= date.today(), Note.due_date <= date.today() + timedelta(days=7))
    elif due_filter == "fiscal_year":
        from db.config import get_current_fiscal_year_bounds
        fy_start, fy_end = get_current_fiscal_year_bounds()
        stmt = stmt.where(Note.due_date.isnot(None), Note.due_date >= fy_start, Note.due_date <= fy_end)
    return stmt


def get_notes_last_n_days(session: Session, days: int = 7, ctx: str = "default") -> list[Note]:
    since = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    stmt = (
        select(Note)
        .where(Note.created_at >= since, Note.context == ctx)
        .order_by(Note.created_at.asc())
        .limit(1000)
    )
    return session.exec(stmt).all()


def delete_note(session: Session, note_id: int, ctx: Optional[str] = None) -> bool:
    note = session.get(Note, note_id)
    if not note:
        return False
    if ctx is not None and note.context != ctx:
        return False
    session.exec(sa_delete(Document).where(Document.note_id == note_id))
    session.exec(sa_delete(NoteDependency).where(
        or_(NoteDependency.note_id == note_id, NoteDependency.blocker_id == note_id)
    ))
    session.delete(note)
    session.commit()
    return True


def get_note_for_ctx(session: Session, note_id: int, ctx: Optional[str] = None) -> Optional[Note]:
    note = session.get(Note, note_id)
    if not note:
        return None
    if ctx is not None and note.context != ctx:
        return None
    return note


def save_email_draft(session: Session, note_id: int, subject: str, body: str) -> Optional[Note]:
    note = session.get(Note, note_id)
    if not note:
        return None
    note.email_subject = subject
    note.email_body = body
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def get_due_notes(session: Session, ctx: str = "default") -> list[Note]:
    from sqlalchemy import or_
    stmt = (
        select(Note)
        .where(Note.due_date.isnot(None), Note.context == ctx)
        .where(or_(Note.status.is_(None), Note.status != 'done'))
        .order_by(Note.due_date.asc())
    )
    return session.exec(stmt).all()


def get_today_activity(session: Session, ctx: str = "default", include_done: bool = False) -> dict[str, list[Note]]:
    """Attività trasversali del giorno: scadute, in scadenza a breve (oggi o
    nei prossimi 2 giorni — stessa soglia "soon" già usata per il badge
    scadenza nelle note), che iniziano oggi, o senza nessuna data —
    indipendentemente da cliente/progetto/stream, per avere un colpo d'occhio
    su cosa affrontare senza girare per il Gantt. Ogni nota finisce in un solo
    bucket anche se soddisfa più criteri (priorità: overdue > due_soon >
    starting_today > no_date)."""
    today = date.today()
    soon_cutoff = today + timedelta(days=2)
    stmt = select(Note).where(
        Note.context == ctx,
        or_(
            and_(Note.due_date.isnot(None), Note.due_date < today),
            and_(Note.due_date.isnot(None), Note.due_date <= soon_cutoff),
            Note.start_date == today,
            and_(Note.start_date.is_(None), Note.due_date.is_(None)),
        ),
    )
    if not include_done:
        stmt = stmt.where(or_(Note.status.is_(None), Note.status != "done"))
    stmt = _exclude_milestone_tag(stmt)
    notes = session.exec(stmt).all()

    overdue, due_soon, starting_today, no_date = [], [], [], []
    for n in notes:
        if n.due_date and n.due_date < today:
            overdue.append(n)
        elif n.due_date and n.due_date <= soon_cutoff:
            due_soon.append(n)
        elif n.start_date == today:
            starting_today.append(n)
        else:
            no_date.append(n)
    overdue.sort(key=lambda n: n.due_date)
    due_soon.sort(key=lambda n: n.due_date)
    starting_today.sort(key=lambda n: n.created_at)
    no_date.sort(key=lambda n: n.created_at)
    return {"overdue": overdue, "due_soon": due_soon, "starting_today": starting_today, "no_date": no_date}


def _fts_query(query: str) -> str:
    import re

    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    return " ".join(f"{term}*" for term in terms)


def _search_notes_like(session: Session, query: str, ctx: str = "default", limit: int = 30) -> list[Note]:
    import re

    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not terms:
        return []

    stmt = select(Note).where(Note.context == ctx)
    for term in terms:
        stmt = stmt.where(
            or_(
                Note.content.ilike(f"%{term}%"),
                Note.tags.ilike(f"%{term}%"),
                Note.project.ilike(f"%{term}%"),
                Note.assignee.ilike(f"%{term}%"),
            )
        )
    stmt = stmt.order_by(Note.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


def search_notes(session: Session, query: str, ctx: str = "default", limit: int = 30) -> list[Note]:
    fts = _fts_query(query)
    if not fts:
        return []

    try:
        rows = session.execute(
            text("""
                SELECT note.id
                FROM note_fts
                JOIN note ON note.id = note_fts.rowid
                WHERE note_fts MATCH :query
                  AND note.context = :ctx
                ORDER BY bm25(note_fts), note.created_at DESC
                LIMIT :limit
            """),
            {"query": fts, "ctx": ctx, "limit": limit},
        ).all()
    except Exception:
        return _search_notes_like(session, query=query, ctx=ctx, limit=limit)

    ids = [row[0] for row in rows]
    if not ids:
        return []
    notes = session.exec(select(Note).where(Note.id.in_(ids))).all()
    by_id = {n.id: n for n in notes}
    return [by_id[nid] for nid in ids if nid in by_id]


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

# ── Clients ────────────────────────────────────────────────────────────────────

def get_clients(session: Session, ctx: str = "default") -> list[Client]:
    return session.exec(
        select(Client).where(Client.context == ctx).order_by(Client.created_at.asc())
    ).all()

def add_client(session: Session, name: str, ctx: str = "default") -> Client:
    c = Client(name=name, context=ctx)
    session.add(c); session.commit(); session.refresh(c)
    return c

def edit_client(session: Session, client_id: int, name: Optional[str] = None) -> Optional[Client]:
    c = session.get(Client, client_id)
    if not c: return None
    if name is not None: c.name = name
    session.add(c); session.commit(); session.refresh(c)
    return c

def delete_client(session: Session, client_id: int) -> bool:
    """Elimina il cliente. I progetti collegati restano (client_id -> NULL), non vengono cancellati."""
    c = session.get(Client, client_id)
    if not c: return False
    session.exec(sa_update(GanttProject).where(GanttProject.client_id == client_id).values(client_id=None))
    session.delete(c)
    session.commit()
    return True

def assign_gantt_project_client(session: Session, project_id: int, client_id: Optional[int]) -> Optional[GanttProject]:
    p = session.get(GanttProject, project_id)
    if not p: return None
    p.client_id = client_id
    session.add(p); session.commit(); session.refresh(p)
    return p


# ── Absences ─────────────────────────────────────────────────────────────────

def get_absences(session: Session, ctx: str = "default") -> list[Absence]:
    return session.exec(
        select(Absence).where(Absence.context == ctx).order_by(Absence.start_date.asc())
    ).all()

def add_absence(session: Session, person: str, start_date: date, end_date: date, ctx: str = "default", color: Optional[str] = None) -> Absence:
    a = Absence(person=person, start_date=start_date, end_date=end_date, context=ctx, color=color)
    session.add(a); session.commit(); session.refresh(a)
    return a

def edit_absence_color(session: Session, absence_id: int, color: Optional[str]) -> Optional[Absence]:
    a = session.get(Absence, absence_id)
    if not a: return None
    a.color = color
    session.add(a); session.commit(); session.refresh(a)
    return a

def delete_absence(session: Session, absence_id: int) -> bool:
    a = session.get(Absence, absence_id)
    if not a: return False
    session.delete(a)
    session.commit()
    return True


# ── Streams ──────────────────────────────────────────────────────────────────

def get_streams(session: Session, project_id: int) -> list[Stream]:
    return session.exec(
        select(Stream).where(Stream.project_id == project_id).order_by(Stream.created_at.asc())
    ).all()

def add_stream(
    session: Session,
    project_id: int,
    name: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Stream:
    s = Stream(project_id=project_id, name=name, start_date=start_date, end_date=end_date)
    session.add(s); session.commit(); session.refresh(s)
    return s

def edit_stream(
    session: Session,
    stream_id: int,
    name: Optional[str] = None,
    start_date: Optional[date] = None,
    clear_start: bool = False,
    end_date: Optional[date] = None,
    clear_end: bool = False,
) -> Optional[Stream]:
    s = session.get(Stream, stream_id)
    if not s: return None
    if name is not None: s.name = name
    if clear_start:
        s.start_date = None
    elif start_date is not None:
        s.start_date = start_date
    if clear_end:
        s.end_date = None
    elif end_date is not None:
        s.end_date = end_date
    session.add(s); session.commit(); session.refresh(s)
    return s

def delete_stream(session: Session, stream_id: int) -> bool:
    """Elimina lo stream e le sue Fasi. Le note collegate (alle fasi via
    milestone_id, o direttamente allo stream via stream_id) restano, solo
    scollegate."""
    s = session.get(Stream, stream_id)
    if not s: return False
    phase_ids = session.exec(select(Phase.id).where(Phase.stream_id == stream_id)).all()
    if phase_ids:
        session.exec(sa_update(Note).where(Note.milestone_id.in_(phase_ids)).values(milestone_id=None))
        session.exec(sa_delete(Phase).where(Phase.stream_id == stream_id))
    session.exec(sa_update(Note).where(Note.stream_id == stream_id).values(stream_id=None))
    session.delete(s); session.commit()
    return True


# ── Fasi ─────────────────────────────────────────────────────────────────────

STANDARD_PHASE_NAMES = ("Analisi e Requisiti", "Implementazione", "UAT", "Rilascio in PROD")

def get_phases(session: Session, stream_id: int) -> list[Phase]:
    """Ordinate per data inizio (le fasi datate riflettono l'ordine cronologico
    reale del lavoro, non l'ordine in cui sono state create/rinominate); le fasi
    senza data restano in coda, ordinate come prima (sort_order, creazione)."""
    phases = session.exec(select(Phase).where(Phase.stream_id == stream_id)).all()
    phases.sort(key=lambda ph: (ph.start_date is None, ph.start_date or date.max, ph.sort_order, ph.created_at))
    return phases

def add_phase(
    session: Session,
    stream_id: int,
    name: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sort_order: int = 0,
) -> Phase:
    ph = Phase(stream_id=stream_id, name=name, start_date=start_date, end_date=end_date, sort_order=sort_order)
    session.add(ph); session.commit(); session.refresh(ph)
    return ph

def add_standard_phases(session: Session, stream_id: int) -> list[Phase]:
    """Crea in un solo click le fasi tipiche (Analisi e Requisiti / Implementazione /
    UAT / Rilascio in PROD), senza date — l'utente le compila dopo. Non tocca eventuali
    fasi già presenti."""
    return [add_phase(session, stream_id, name, sort_order=i) for i, name in enumerate(STANDARD_PHASE_NAMES)]

def edit_phase(
    session: Session,
    phase_id: int,
    name: Optional[str] = None,
    start_date: Optional[date] = None,
    clear_start: bool = False,
    end_date: Optional[date] = None,
    clear_end: bool = False,
) -> Optional[Phase]:
    ph = session.get(Phase, phase_id)
    if not ph: return None
    if name is not None: ph.name = name
    if clear_start:
        ph.start_date = None
    elif start_date is not None:
        ph.start_date = start_date
    if clear_end:
        ph.end_date = None
    elif end_date is not None:
        ph.end_date = end_date
    if ph.note_id:
        note = session.get(Note, ph.note_id)
        if note:
            if name is not None:
                note.content = name
            if clear_end:
                note.due_date = None
            elif end_date is not None:
                note.due_date = end_date
            note.updated_at = datetime.now()
            session.add(note)
    session.add(ph); session.commit(); session.refresh(ph)
    return ph

def delete_phase(session: Session, phase_id: int) -> bool:
    """Elimina la fase. La nota auto-creata collegata (note.milestone_id) resta, solo scollegata."""
    ph = session.get(Phase, phase_id)
    if not ph: return False
    session.exec(sa_update(Note).where(Note.milestone_id == phase_id).values(milestone_id=None))
    session.delete(ph); session.commit()
    return True


def get_gantt_projects(session: Session, ctx: str = "default") -> list[GanttProject]:
    return session.exec(
        select(GanttProject)
        .where(GanttProject.context == ctx, GanttProject.archived == False)
        .order_by(GanttProject.created_at.asc())
    ).all()

def get_archived_gantt_projects(session: Session, ctx: str = "default") -> list[GanttProject]:
    return session.exec(
        select(GanttProject)
        .where(GanttProject.context == ctx, GanttProject.archived == True)
        .order_by(GanttProject.created_at.asc())
    ).all()

def archive_gantt_project(session: Session, project_id: int) -> bool:
    p = session.get(GanttProject, project_id)
    if not p:
        return False
    p.archived = True
    session.add(p)
    session.commit()
    return True

def unarchive_gantt_project(session: Session, project_id: int) -> bool:
    p = session.get(GanttProject, project_id)
    if not p:
        return False
    p.archived = False
    session.add(p)
    session.commit()
    return True

def add_gantt_project(
    session: Session,
    name: str,
    color: str = "#818cf8",
    ctx: str = "default",
    is_background: bool = False,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> GanttProject:
    p = GanttProject(name=name, color=color, context=ctx, is_background=is_background,
                      start_date=start_date, end_date=end_date)
    session.add(p); session.commit(); session.refresh(p)
    return p

def edit_gantt_project(
    session: Session,
    project_id: int,
    name: Optional[str] = None,
    color: Optional[str] = None,
    is_background: Optional[bool] = None,
    start_date: Optional[date] = None,
    clear_start: bool = False,
    end_date: Optional[date] = None,
    clear_end: bool = False,
) -> Optional[GanttProject]:
    p = session.get(GanttProject, project_id)
    if not p: return None
    if name is not None: p.name = name
    if color is not None: p.color = color
    if is_background is not None: p.is_background = is_background
    if clear_start:
        p.start_date = None
    elif start_date is not None:
        p.start_date = start_date
    if clear_end:
        p.end_date = None
    elif end_date is not None:
        p.end_date = end_date
    session.add(p); session.commit(); session.refresh(p)
    return p

def delete_gantt_project(session: Session, project_id: int) -> bool:
    """Elimina il progetto e i suoi Stream/Fasi. Note collegate alle fasi restano,
    solo scollegate (milestone_id -> NULL) — niente viene cancellato oltre a
    progetto, Stream e Fasi."""
    p = session.get(GanttProject, project_id)
    if not p: return False
    stream_ids = session.exec(
        select(Stream.id).where(Stream.project_id == project_id)
    ).all()
    if stream_ids:
        phase_ids = session.exec(select(Phase.id).where(Phase.stream_id.in_(stream_ids))).all()
        if phase_ids:
            session.exec(sa_update(Note).where(Note.milestone_id.in_(phase_ids)).values(milestone_id=None))
            session.exec(sa_delete(Phase).where(Phase.stream_id.in_(stream_ids)))
        session.exec(sa_update(Note).where(Note.stream_id.in_(stream_ids)).values(stream_id=None))
        session.exec(sa_delete(Stream).where(Stream.project_id == project_id))
    session.delete(p); session.commit()
    return True

# ── Note Dependencies ──────────────────────────────────────────────────────────

def add_dependency(session: Session, note_id: int, blocker_id: int, ctx: Optional[str] = None) -> Optional[NoteDependency]:
    if note_id == blocker_id:
        return None
    note = session.get(Note, note_id)
    blocker = session.get(Note, blocker_id)
    if not note or not blocker:
        return None
    if note.context != blocker.context:
        return None
    if ctx is not None and (note.context != ctx or blocker.context != ctx):
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

def get_blockers(session: Session, note_id: int, ctx: Optional[str] = None) -> list[Note]:
    """Note che bloccano note_id."""
    ids = session.exec(select(NoteDependency.blocker_id).where(NoteDependency.note_id == note_id)).all()
    if not ids:
        return []
    stmt = select(Note).where(Note.id.in_(ids))
    if ctx is not None:
        stmt = stmt.where(Note.context == ctx)
    return session.exec(stmt).all()

def get_blocking(session: Session, note_id: int, ctx: Optional[str] = None) -> list[Note]:
    """Note bloccate da note_id."""
    ids = session.exec(select(NoteDependency.note_id).where(NoteDependency.blocker_id == note_id)).all()
    if not ids:
        return []
    stmt = select(Note).where(Note.id.in_(ids))
    if ctx is not None:
        stmt = stmt.where(Note.context == ctx)
    return session.exec(stmt).all()

def get_deps_bulk(session: Session, note_ids: list[int], ctx: Optional[str] = None) -> dict:
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
        stmt = select(Note).where(Note.id.in_(all_ref_ids))
        if ctx is not None:
            stmt = stmt.where(Note.context == ctx)
        ref_notes = {n.id: n for n in session.exec(stmt).all()}
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


# ── Documents ─────────────────────────────────────────────────────────────────

def add_document(session: Session, note_id: Optional[int], rel_path: str, orig_name: str,
                 mime_type: Optional[str] = None, size_bytes: Optional[int] = None,
                 sha256: Optional[str] = None) -> Document:
    doc = Document(note_id=note_id, rel_path=rel_path, orig_name=orig_name,
                   mime_type=mime_type, size_bytes=size_bytes, sha256=sha256)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def get_docs_for_note(session: Session, note_id: int) -> list[Document]:
    return session.exec(select(Document).where(Document.note_id == note_id)).all()


def get_docs_bulk(session: Session, note_ids: list[int]) -> dict[int, list]:
    if not note_ids:
        return {}
    docs = session.exec(select(Document).where(Document.note_id.in_(note_ids))).all()
    result: dict[int, list] = {nid: [] for nid in note_ids}
    for d in docs:
        if d.note_id in result:
            result[d.note_id].append(d)
    return result


def delete_document(session: Session, doc_id: int) -> Optional[Document]:
    doc = session.get(Document, doc_id)
    if not doc:
        return None
    session.delete(doc)
    session.commit()
    return doc


def update_doc_analysis(session: Session, doc_id: int, analysis: str) -> Optional[Document]:
    doc = session.get(Document, doc_id)
    if not doc:
        return None
    doc.analysis = analysis
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def get_all_documents(session: Session, ctx: str = "default", limit: int = 200) -> list[Document]:
    """Tutti i documenti del contesto, joinando con note esistenti."""
    stmt = (
        select(Document)
        .join(Note, Document.note_id == Note.id)
        .where(Note.context == ctx)
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    return session.exec(stmt).all()


# ── Gantt ──────────────────────────────────────────────────────────────────────

def _reconcile_projects_from_notes(session: Session, ctx: str) -> None:
    """Rete di sicurezza: se per qualche motivo una nota con cliente+progetto
    non ha (ancora) fatto scattare _sync_project_client_from_note al momento
    della creazione/modifica, questa riconciliazione (eseguita ad ogni lettura
    del Gantt) recupera i progetti/clienti mancanti — la nota non deve restare
    invisibile nel Gantt solo perché non ha ancora delle date."""
    pairs = session.exec(
        select(Note.cliente, Note.project)
        .where(Note.context == ctx, Note.cliente.isnot(None), Note.project.isnot(None))
        .distinct()
    ).all()
    for cliente, project in pairs:
        _sync_project_client_from_note(session, project, cliente, ctx)


def get_gantt_data(session: Session, ctx: str = "default") -> dict:
    _reconcile_projects_from_notes(session, ctx=ctx)
    projects = get_gantt_projects(session, ctx=ctx)

    # IDs of notes that are actual blockers of something (appear as blocker_id in NoteDependency)
    blocker_ids_in_use: set[int] = set(
        session.exec(select(NoteDependency.blocker_id)).all()
    )

    clients = get_clients(session, ctx=ctx)
    client_name_map = {c.id: c.name for c in clients}

    # All phase-linked notes for the whole context, grouped by milestone_id
    # (legacy column name, v. Note.milestone_id — ora punta a Phase.id) in Python,
    # per evitare una query per fase (N+1) across every project.
    def _note_period_key(n: Note):
        # Ordine "di periodo": start_date se c'è, altrimenti due_date, altrimenti
        # data di creazione — non l'id/ordine di inserimento della nota.
        return n.start_date or n.due_date or n.created_at.date()

    all_phase_notes = session.exec(
        select(Note).where(Note.context == ctx, Note.milestone_id.isnot(None))
    ).all()
    notes_by_phase: dict[int, list[Note]] = {}
    for n in all_phase_notes:
        notes_by_phase.setdefault(n.milestone_id, []).append(n)
    for notes in notes_by_phase.values():
        notes.sort(key=_note_period_key)

    # Note agganciate direttamente a uno Stream (senza una Fase intermedia) —
    # lavoro semplice dove la nota stessa fa da "fase" nel Gantt.
    direct_stream_notes = session.exec(
        select(Note).where(Note.context == ctx, Note.stream_id.isnot(None))
    ).all()
    notes_by_stream_direct: dict[int, list[Note]] = {}
    for n in direct_stream_notes:
        notes_by_stream_direct.setdefault(n.stream_id, []).append(n)

    def _phase_data(ph: Phase, project_name: str) -> tuple[dict, int, int]:
        linked = notes_by_phase.get(ph.id, [])
        progress_notes = linked[:]
        phase_note = None
        if ph.note_id and not any(n.id == ph.note_id for n in progress_notes):
            phase_note = session.get(Note, ph.note_id)
            if phase_note and phase_note.context == ctx:
                progress_notes.append(phase_note)
        if not ph.note_id:
            phase_note = session.exec(
                select(Note)
                .where(Note.context == ctx, Note.project.ilike(project_name))
                .where(Note.content == ph.name, Note.due_date == ph.end_date)
                .where(or_(
                    Note.tags == "milestone",
                    Note.tags.ilike("milestone,%"),
                    Note.tags.ilike("%,milestone"),
                    Note.tags.ilike("%,milestone,%"),
                ))
            ).first()
            if phase_note and not any(n.id == phase_note.id for n in progress_notes):
                progress_notes.append(phase_note)
        progress_total = len(progress_notes)
        progress_done = sum(1 for n in progress_notes if n.status == "done")
        progress = round(progress_done / progress_total * 100) if progress_total else 0
        return {
            "id": ph.id,
            "name": ph.name,
            "start_date": str(ph.start_date) if ph.start_date else None,
            "end_date": str(ph.end_date) if ph.end_date else None,
            "note_id": ph.note_id,
            "progress": progress,
            "progress_done": progress_done,
            "progress_total": progress_total,
            "linked_notes": [
                {"id": n.id, "content": n.content, "status": n.status,
                 "start_date": str(n.start_date) if n.start_date else None,
                 "due_date": str(n.due_date) if n.due_date else None,
                 "created_at": n.created_at.date().isoformat()}
                for n in linked
            ]
        }, progress_done, progress_total

    def _note_as_phase(n: Note) -> dict:
        """Una nota agganciata direttamente a uno Stream si presenta nel Gantt
        esattamente come una Fase (stessa forma dati) — il suo status ne è
        anche il progress (1 nota, fatta o no), la nota stessa è il contenuto,
        niente sotto-note proprie."""
        return {
            "id": f"note-{n.id}",
            "name": n.content,
            "start_date": str(n.start_date) if n.start_date else None,
            "end_date": str(n.due_date) if n.due_date else None,
            "note_id": n.id,
            "is_note": True,
            "status": n.status,
            "created_at": n.created_at.date().isoformat(),
            "progress": 100 if n.status == "done" else 0,
            "progress_done": 1 if n.status == "done" else 0,
            "progress_total": 1,
            "linked_notes": [],
        }

    def _stream_data(s: Stream, project_name: str) -> tuple[dict, int, int]:
        phases_data = []
        stream_done_total = 0
        stream_notes_total = 0
        for ph in get_phases(session, s.id):
            data, done, total = _phase_data(ph, project_name)
            phases_data.append(data)
            stream_done_total += done
            stream_notes_total += total
        for n in notes_by_stream_direct.get(s.id, []):
            phases_data.append(_note_as_phase(n))
            stream_notes_total += 1
            if n.status == "done":
                stream_done_total += 1
        # Fasi reali e note-come-fase mescolate e riordinate insieme per periodo
        # (senza data in coda), non nell'ordine "prima le Fasi, poi le note".
        phases_data.sort(key=lambda ph: (ph["start_date"] is None, ph["start_date"] or ""))
        progress = round(stream_done_total / stream_notes_total * 100) if stream_notes_total else 0
        # Date effettive dello Stream: se ha almeno una Fase (o nota-come-fase),
        # è il min/max delle loro date a contare, non quelle proprie dello
        # Stream (che restano "di riserva" per quando non ne ha nessuna).
        if phases_data:
            starts = [ph["start_date"] for ph in phases_data if ph["start_date"]]
            ends = [ph["end_date"] for ph in phases_data if ph["end_date"]]
            eff_start = min(starts) if starts else None
            eff_end = max(ends) if ends else None
        else:
            eff_start = str(s.start_date) if s.start_date else None
            eff_end = str(s.end_date) if s.end_date else None
        return {
            "id": s.id,
            "name": s.name,
            "start_date": eff_start,
            "end_date": eff_end,
            "progress": progress,
            "progress_done": stream_done_total,
            "progress_total": stream_notes_total,
            "phases": phases_data,
        }, stream_done_total, stream_notes_total

    result = []
    for p in projects:
        streams = [] if p.is_background else get_streams(session, p.id)
        notes_with_due_stmt = (
            select(Note)
            .where(Note.due_date.isnot(None), Note.context == ctx)
            .where(Note.project.ilike(p.name))
            .where(Note.milestone_id.is_(None))
            .where(Note.stream_id.is_(None))
        )
        notes_with_due = session.exec(_exclude_milestone_tag(notes_with_due_stmt)).all()
        notes_with_due.sort(key=_note_period_key)

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

        proj_done_total = 0
        proj_notes_total = 0

        streams_data = []
        for s in streams:
            data, done, total = _stream_data(s, p.name)
            streams_data.append(data)
            proj_done_total += done
            proj_notes_total += total

        project_progress = round(proj_done_total / proj_notes_total * 100) if proj_notes_total else 0

        result.append({
            "id": p.id,
            "name": p.name,
            "color": p.color,
            "is_background": p.is_background,
            "has_risk_blocker": has_risk_blocker,
            "client_id": p.client_id,
            "client_name": client_name_map.get(p.client_id),
            "start_date": str(p.start_date) if p.start_date else None,
            "end_date": str(p.end_date) if p.end_date else None,
            "streams": streams_data,
            "progress": project_progress,
            "notes": [
                {"id": n.id, "content": n.content, "due_date": str(n.due_date), "status": n.status,
                 "start_date": str(n.start_date) if n.start_date else None,
                 "assignee": n.assignee, "created_at": n.created_at.date().isoformat()}
                for n in notes_with_due
            ]
        })
    absences = get_absences(session, ctx=ctx)
    return {
        "projects": result,
        "clients": [{"id": c.id, "name": c.name} for c in clients],
        "absences": [
            {"id": a.id, "person": a.person, "start_date": str(a.start_date), "end_date": str(a.end_date), "color": a.color}
            for a in absences
        ],
    }
