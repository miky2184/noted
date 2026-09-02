from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from datetime import date
from typing import Literal, Optional, List

from db.engine import get_session
from db import crud
from db.models import PRIORITIES, STATUSES
from web.deps import note_dict, doc_dict, get_ctx

Priority = Literal[*PRIORITIES]
# "" is a valid wire value for NoteUpdate: it means "clear the field" (see
# clear_status below) and must stay accepted there even though it's not a
# real status.
Status = Literal[*STATUSES]
StatusOrClear = Literal[*STATUSES, ""]


router = APIRouter()


# ── Notes API ─────────────────────────────────────────────────────────────────

@router.get("/api/notes")
async def api_notes(
    request: Request,
    day: str = Query(None),
    tag: str = Query(None),
    project: str = Query(None),
    assignee: str = Query(None),
    status: str = Query(None),
):
    ctx = get_ctx(request)
    target = date.fromisoformat(day) if day else None
    with get_session() as session:
        notes = crud.get_notes(session, day=target, tag=tag, project=project,
                               assignee=assignee, status=status, ctx=ctx)
        note_ids = [n.id for n in notes]
        deps = crud.get_deps_bulk(session, note_ids, ctx=ctx)
        docs_map = crud.get_docs_bulk(session, note_ids)
    result = []
    for n in notes:
        d = note_dict(n)
        nd = deps.get(n.id, {})
        d["blockers"] = nd.get("blocker_notes", [])
        d["blocking"] = nd.get("blocking_notes", [])
        d["docs"] = [doc_dict(doc) for doc in docs_map.get(n.id, [])]
        result.append(d)
    return result


class NoteCreate(BaseModel):
    content: str
    tags: Optional[str] = ""
    cliente: Optional[str] = None
    project: Optional[str] = None
    priority: Optional[Priority] = "medium"
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[Status] = None
    assignee: Optional[str] = None
    milestone_id: Optional[int] = None


@router.post("/api/notes", status_code=201)
async def api_add_note(request: Request, body: NoteCreate):
    ctx = get_ctx(request)
    start = date.fromisoformat(body.start_date) if body.start_date else None
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.add_note(
            session, content=body.content, tags=body.tags or "",
            cliente=body.cliente or None,
            project=body.project, priority=body.priority or "medium",
            start_date=start, due_date=due,
            status=body.status or None, assignee=body.assignee or None, ctx=ctx,
            milestone_id=body.milestone_id,
        )
    return note_dict(note)


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    tags: Optional[str] = None
    cliente: Optional[str] = None
    project: Optional[str] = None
    priority: Optional[Priority] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[StatusOrClear] = None
    assignee: Optional[str] = None
    milestone_id: Optional[int] = None
    clear_milestone: bool = False


@router.patch("/api/notes/{note_id}")
async def api_update_note(note_id: int, body: NoteUpdate, request: Request):
    ctx = get_ctx(request)
    start = date.fromisoformat(body.start_date) if body.start_date else None
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.edit_note(
            session, note_id,
            content=body.content,
            tags=body.tags,
            cliente=body.cliente,
            clear_cliente=body.cliente == "",
            project=body.project,
            priority=body.priority,
            start_date=start,
            clear_start=body.start_date == "",
            due_date=due,
            clear_due=body.due_date == "",
            status=body.status,
            clear_status=body.status == "",
            assignee=body.assignee,
            clear_assignee=body.assignee == "",
            milestone_id=body.milestone_id,
            clear_milestone=body.clear_milestone,
            ctx=ctx,
        )
    if not note:
        raise HTTPException(status_code=404, detail="Nota non trovata")
    return note_dict(note)


@router.get("/api/search")
async def api_search(request: Request, q: str = Query(""), limit: int = Query(20)):
    ctx = get_ctx(request)
    if not q.strip():
        return []
    with get_session() as session:
        notes = crud.search_notes(session, query=q.strip(), ctx=ctx, limit=limit)
    return [note_dict(n) for n in notes]


@router.get("/api/notes/due")
async def api_due_notes(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        notes = crud.get_due_notes(session, ctx=ctx)
    return [note_dict(n) for n in notes]


class EmailDraftRequest(BaseModel):
    instruction: Optional[str] = None


@router.post("/api/notes/{note_id}/email-draft")
async def api_email_draft(note_id: int, body: EmailDraftRequest, request: Request):
    ctx = get_ctx(request)
    instruction = (body.instruction or "").strip()
    with get_session() as session:
        note = crud.get_note_for_ctx(session, note_id, ctx=ctx)
        if not note:
            raise HTTPException(status_code=404, detail="Nota non trovata")

        has_draft = bool(note.email_subject or note.email_body)
        # Bozza già salvata e nessuna richiesta di modifica: la restituiamo
        # senza richiamare l'AI (v. commento nel modello Note).
        if has_draft and not instruction:
            return {"subject": note.email_subject or "", "body": note.email_body or ""}

        if not has_draft and not note.content.strip():
            raise HTTPException(status_code=400, detail="Nota vuota")

        from web.services.recap_service import ensure_api_key, MissingApiKeyError
        try:
            ensure_api_key()
        except MissingApiKeyError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        from ai.email_draft import generate_email_draft, refine_email_draft
        try:
            if has_draft:
                draft = refine_email_draft(note.content, note.email_subject or "", note.email_body or "", instruction)
            else:
                draft = generate_email_draft(note.content)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Errore generazione email: {exc}") from exc

        crud.save_email_draft(session, note_id, draft["subject"], draft["body"])
        return draft


@router.get("/api/notes/today-activity")
async def api_today_activity(request: Request, include_done: bool = Query(False)):
    ctx = get_ctx(request)
    with get_session() as session:
        buckets = crud.get_today_activity(session, ctx=ctx, include_done=include_done)
        all_notes = [n for notes in buckets.values() for n in notes]
        note_ids = [n.id for n in all_notes]
        deps = crud.get_deps_bulk(session, note_ids, ctx=ctx)
        docs_map = crud.get_docs_bulk(session, note_ids)

        def _enrich(n):
            d = note_dict(n)
            nd = deps.get(n.id, {})
            d["blockers"] = nd.get("blocker_notes", [])
            d["blocking"] = nd.get("blocking_notes", [])
            d["docs"] = [doc_dict(doc) for doc in docs_map.get(n.id, [])]
            return d

        return {key: [_enrich(n) for n in notes] for key, notes in buckets.items()}


@router.delete("/api/notes/{note_id}", status_code=204)
async def api_delete_note(note_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        ok = crud.delete_note(session, note_id, ctx=ctx)
    if not ok:
        raise HTTPException(status_code=404, detail="Nota non trovata")


class MoveNote(BaseModel):
    status: Optional[str] = None
    column_ids: List[int] = []

@router.patch("/api/notes/{note_id}/move", status_code=204)
async def api_move_note(note_id: int, body: MoveNote, request: Request):
    from db.models import Note as NoteModel
    ctx = get_ctx(request)
    with get_session() as session:
        note = session.get(NoteModel, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        if body.status is not None:
            note.status = body.status if body.status != "inbox" else None
        for i, nid in enumerate(body.column_ids):
            n = session.get(NoteModel, nid)
            if n and n.context == ctx:
                n.sort_order = i
                session.add(n)
        session.add(note)
        session.commit()


@router.get("/api/notes/{note_id}/deps")
async def api_get_deps(note_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        blockers = crud.get_blockers(session, note_id, ctx=ctx)
        blocking = crud.get_blocking(session, note_id, ctx=ctx)
        return {
            "blockers": [{"id": n.id, "content": n.content[:80], "status": n.status} for n in blockers],
            "blocking": [{"id": n.id, "content": n.content[:80], "status": n.status} for n in blocking],
        }

class DepBody(BaseModel):
    blocker_id: int

@router.post("/api/notes/{note_id}/deps", status_code=201)
async def api_add_dep(note_id: int, body: DepBody, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        blocker = session.get(crud.Note, body.blocker_id)
        if not blocker or blocker.context != ctx:
            raise HTTPException(status_code=404, detail="Nota blocker non trovata")
        dep = crud.add_dependency(session, note_id, body.blocker_id, ctx=ctx)
        if not dep:
            raise HTTPException(status_code=400, detail="Dipendenza non valida o già esistente")
        return {"id": dep.id, "note_id": dep.note_id, "blocker_id": dep.blocker_id}

@router.delete("/api/notes/{note_id}/deps/{blocker_id}", status_code=204)
async def api_remove_dep(note_id: int, blocker_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        blocker = session.get(crud.Note, blocker_id)
        if not blocker or blocker.context != ctx:
            raise HTTPException(status_code=404, detail="Nota blocker non trovata")
        crud.remove_dependency(session, note_id, blocker_id)

@router.get("/api/board")
async def api_board(
    request: Request,
    q: str = Query(None),
    tag: str = Query(None),
    project: str = Query(None),
    cliente: str = Query(None),
    assignee: str = Query(None),
    priority: str = Query(None),
    due: str = Query(None),
    created: str = Query(None),
    no_project: bool = Query(False),
    no_cliente: bool = Query(False),
    no_tag: bool = Query(False),
):
    ctx = get_ctx(request)
    created_today = created == "today"
    with get_session() as session:
        notes = crud.get_board_notes(session, project=project or None, cliente=cliente or None,
                                     assignee=assignee or None, tag=tag or None,
                                     priority=priority or None, query=q or None,
                                     created_today=created_today, due_filter=due or None,
                                     no_project=no_project, no_cliente=no_cliente, no_tag=no_tag,
                                     ctx=ctx)
        inbox = crud.get_inbox_notes(session, days=7, project=project or None, cliente=cliente or None,
                                     assignee=assignee or None, tag=tag or None,
                                     priority=priority or None, query=q or None,
                                     created_today=created_today, due_filter=due or None,
                                     no_project=no_project, no_cliente=no_cliente, no_tag=no_tag,
                                     ctx=ctx)
    result = {"inbox": [], "backlog": [], "todo": [], "discuss": [], "wip": [], "waiting": [], "blocked": [], "done": []}
    for n in inbox:
        result["inbox"].append(note_dict(n))
    for n in notes:
        key = n.status if n.status in result else None
        if key:
            result[key].append(note_dict(n))
    return result
