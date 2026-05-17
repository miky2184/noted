from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from datetime import date
from typing import Optional, List

from db.engine import get_session
from db import crud
from web.deps import note_dict, doc_dict, get_ctx


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
    project: Optional[str] = None
    priority: Optional[str] = "medium"
    due_date: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None


@router.post("/api/notes", status_code=201)
async def api_add_note(request: Request, body: NoteCreate):
    ctx = get_ctx(request)
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.add_note(
            session, content=body.content, tags=body.tags or "",
            project=body.project, priority=body.priority or "medium", due_date=due,
            status=body.status or None, assignee=body.assignee or None, ctx=ctx,
        )
    return note_dict(note)


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    tags: Optional[str] = None
    project: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None


@router.patch("/api/notes/{note_id}")
async def api_update_note(note_id: int, body: NoteUpdate):
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.edit_note(
            session, note_id,
            content=body.content,
            tags=body.tags,
            project=body.project,
            priority=body.priority,
            due_date=due,
            clear_due=body.due_date == "",
            status=body.status,
            clear_status=body.status == "",
            assignee=body.assignee,
            clear_assignee=body.assignee == "",
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


@router.delete("/api/notes/{note_id}", status_code=204)
async def api_delete_note(note_id: int):
    with get_session() as session:
        ok = crud.delete_note(session, note_id)
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
    project: str = Query(None),
    assignee: str = Query(None),
):
    ctx = get_ctx(request)
    with get_session() as session:
        notes = crud.get_board_notes(session, project=project or None,
                                     assignee=assignee or None, ctx=ctx)
        inbox = crud.get_inbox_notes(session, days=7, project=project or None,
                                     assignee=assignee or None, ctx=ctx)
    result = {"inbox": [], "backlog": [], "todo": [], "wip": [], "waiting": [], "blocked": [], "done": []}
    for n in inbox:
        result["inbox"].append(note_dict(n))
    for n in notes:
        key = n.status if n.status in result else None
        if key:
            result[key].append(note_dict(n))
    return result
