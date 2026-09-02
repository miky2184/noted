import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_color(color: Optional[str]) -> Optional[str]:
    """Colore opzionale scelto dall'utente: se presente deve essere un hex #rrggbb
    valido, per evitare che finisca non sanificato in un attributo style inline."""
    if color is None or color == "":
        return None
    if not _HEX_COLOR_RE.match(color):
        raise HTTPException(status_code=400, detail="Colore non valido (usa il formato #rrggbb)")
    return color

from db import crud
from db.engine import get_session
from web.deps import get_ctx


router = APIRouter()


# ── Gantt ──────────────────────────────────────────────────────────────────────

class GanttProjectCreate(BaseModel):
    name: str
    color: str = "#818cf8"
    is_background: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class GanttProjectUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    is_background: Optional[bool] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class StreamCreate(BaseModel):
    project_id: int
    name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class StreamUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class ClientCreate(BaseModel):
    name: str

class ClientUpdate(BaseModel):
    name: Optional[str] = None

class ProjectClientAssign(BaseModel):
    client_id: Optional[int] = None

class AbsenceCreate(BaseModel):
    person: str
    start_date: str
    end_date: str
    color: Optional[str] = None

class AbsenceColorUpdate(BaseModel):
    color: Optional[str] = None


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} non valida")


def _ensure_date_order(start: Optional[date], end: Optional[date]) -> None:
    if start is not None and end is not None and end < start:
        raise HTTPException(status_code=400, detail="La data fine non può precedere la data inizio")


def _get_project_or_404(session, project_id: int, ctx: str):
    project = session.get(crud.GanttProject, project_id)
    if not project or project.context != ctx:
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    return project


def _get_client_or_404(session, client_id: int, ctx: str):
    client = session.get(crud.Client, client_id)
    if not client or client.context != ctx:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    return client


def _get_stream_or_404(session, stream_id: int, ctx: str):
    stream = session.get(crud.Stream, stream_id)
    project = session.get(crud.GanttProject, stream.project_id) if stream else None
    if not stream or not project or project.context != ctx:
        raise HTTPException(status_code=404, detail="Stream non trovato")
    return stream

@router.get("/api/gantt")
async def api_gantt(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        data = crud.get_gantt_data(session, ctx=ctx)
        archived = crud.get_archived_gantt_projects(session, ctx=ctx)
        data["archived_projects"] = [
            {"id": p.id, "name": p.name, "color": p.color}
            for p in archived
        ]
        return data

@router.patch("/api/gantt/projects/{project_id}/archive", status_code=200)
async def api_archive_gantt_project(project_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_project_or_404(session, project_id, ctx)
        crud.archive_gantt_project(session, project_id)
    return {"ok": True}

@router.patch("/api/gantt/projects/{project_id}/unarchive", status_code=200)
async def api_unarchive_gantt_project(project_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_project_or_404(session, project_id, ctx)
        crud.unarchive_gantt_project(session, project_id)
    return {"ok": True}

def _project_dict(p) -> dict:
    return {"id": p.id, "name": p.name, "color": p.color, "is_background": p.is_background,
            "start_date": str(p.start_date) if p.start_date else None,
            "end_date": str(p.end_date) if p.end_date else None}

@router.post("/api/gantt/projects", status_code=201)
async def api_add_gantt_project(request: Request, body: GanttProjectCreate):
    ctx = get_ctx(request)
    color = _validate_color(body.color) or "#818cf8"
    start = _parse_date(body.start_date, "start_date") if body.start_date else None
    end = _parse_date(body.end_date, "end_date") if body.end_date else None
    _ensure_date_order(start, end)
    with get_session() as session:
        p = crud.add_gantt_project(session, name=body.name, color=color, ctx=ctx,
                                   is_background=body.is_background, start_date=start, end_date=end)
        return _project_dict(p)

@router.patch("/api/gantt/projects/{project_id}")
async def api_edit_gantt_project(project_id: int, body: GanttProjectUpdate, request: Request):
    ctx = get_ctx(request)
    color = _validate_color(body.color) if body.color is not None else None
    start = _parse_date(body.start_date, "start_date") if body.start_date else None
    end = _parse_date(body.end_date, "end_date") if body.end_date else None
    with get_session() as session:
        project = _get_project_or_404(session, project_id, ctx)
        next_start = project.start_date if body.start_date is None else (start if body.start_date != "" else None)
        next_end = project.end_date if body.end_date is None else (end if body.end_date != "" else None)
        _ensure_date_order(next_start, next_end)
        p = crud.edit_gantt_project(session, project_id, name=body.name, color=color,
                                    is_background=body.is_background,
                                    start_date=start, clear_start=body.start_date == "",
                                    end_date=end, clear_end=body.end_date == "")
    if not p: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return _project_dict(p)

@router.delete("/api/gantt/projects/{project_id}", status_code=204)
async def api_delete_gantt_project(project_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_project_or_404(session, project_id, ctx)
        ok = crud.delete_gantt_project(session, project_id)
    if not ok: raise HTTPException(status_code=404, detail="Progetto non trovato")

def _stream_dict(s) -> dict:
    return {"id": s.id, "project_id": s.project_id, "name": s.name,
            "start_date": str(s.start_date) if s.start_date else None,
            "end_date": str(s.end_date) if s.end_date else None,
            "note_id": s.note_id}

@router.post("/api/gantt/streams", status_code=201)
async def api_add_stream(body: StreamCreate, request: Request):
    ctx = get_ctx(request)
    start = _parse_date(body.start_date, "start_date") if body.start_date else None
    end = _parse_date(body.end_date, "end_date") if body.end_date else None
    _ensure_date_order(start, end)
    with get_session() as session:
        project = _get_project_or_404(session, body.project_id, ctx)
        s = crud.add_stream(session, project_id=body.project_id, name=body.name,
                            start_date=start, end_date=end)
        # La nota di tracking auto-creata ha senso solo per uno stream con una
        # scadenza reale — uno stream creato senza date è pensato per raccogliere
        # note operative vere (via milestone_id), non per generarne una fittizia.
        if not project.is_background and end is not None:
            note = crud.add_note(session, content=body.name, tags="milestone", project=project.name,
                          status="todo", due_date=end, ctx=ctx)
            s.note_id = note.id
            session.add(s)
            session.commit()
        return _stream_dict(s)

@router.get("/api/gantt/streams/all")
async def api_all_streams(request: Request):
    """Tutti gli Stream del contesto attivo, con etichetta "Progetto > Stream" —
    usato per il campo di ricerca nel form nota."""
    ctx = get_ctx(request)
    with get_session() as session:
        projects = crud.get_gantt_projects(session, ctx=ctx)
        results = []
        for p in projects:
            for s in crud.get_streams(session, p.id):
                results.append({"id": s.id, "label": f"{p.name} > {s.name}"})
        return {"streams": results}

@router.patch("/api/gantt/streams/{stream_id}")
async def api_edit_stream(stream_id: int, body: StreamUpdate, request: Request):
    ctx = get_ctx(request)
    start = _parse_date(body.start_date, "start_date") if body.start_date else None
    end = _parse_date(body.end_date, "end_date") if body.end_date else None
    with get_session() as session:
        stream = _get_stream_or_404(session, stream_id, ctx)
        # what the value will be *after* this update — None means "not provided" (unchanged),
        # "" means "explicit clear" (becomes None), anything else is the new parsed date
        next_start = stream.start_date if body.start_date is None else (start if body.start_date != "" else None)
        next_end = stream.end_date if body.end_date is None else (end if body.end_date != "" else None)
        _ensure_date_order(next_start, next_end)
        s = crud.edit_stream(
            session, stream_id, name=body.name,
            start_date=start, clear_start=body.start_date == "",
            end_date=end, clear_end=body.end_date == "",
        )
    if not s: raise HTTPException(status_code=404, detail="Stream non trovato")
    return _stream_dict(s)

@router.delete("/api/gantt/streams/{stream_id}", status_code=204)
async def api_delete_stream(stream_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_stream_or_404(session, stream_id, ctx)
        ok = crud.delete_stream(session, stream_id)
    if not ok: raise HTTPException(status_code=404, detail="Stream non trovato")


# ── Clienti ──────────────────────────────────────────────────────────────────

@router.get("/api/gantt/clients")
async def api_get_clients(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        clients = crud.get_clients(session, ctx=ctx)
        return [{"id": c.id, "name": c.name} for c in clients]

@router.post("/api/gantt/clients", status_code=201)
async def api_add_client(body: ClientCreate, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        c = crud.add_client(session, name=body.name, ctx=ctx)
        return {"id": c.id, "name": c.name}

@router.patch("/api/gantt/clients/{client_id}")
async def api_edit_client(client_id: int, body: ClientUpdate, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_client_or_404(session, client_id, ctx)
        c = crud.edit_client(session, client_id, name=body.name)
    if not c: raise HTTPException(status_code=404, detail="Cliente non trovato")
    return {"id": c.id, "name": c.name}

@router.delete("/api/gantt/clients/{client_id}", status_code=204)
async def api_delete_client(client_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_client_or_404(session, client_id, ctx)
        ok = crud.delete_client(session, client_id)
    if not ok: raise HTTPException(status_code=404, detail="Cliente non trovato")

@router.patch("/api/gantt/projects/{project_id}/client")
async def api_assign_project_client(project_id: int, body: ProjectClientAssign, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        _get_project_or_404(session, project_id, ctx)
        if body.client_id is not None:
            _get_client_or_404(session, body.client_id, ctx)
        p = crud.assign_gantt_project_client(session, project_id, body.client_id)
    if not p: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": p.id, "client_id": p.client_id}


# ── Assenze ──────────────────────────────────────────────────────────────────

@router.get("/api/gantt/absences")
async def api_get_absences(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        absences = crud.get_absences(session, ctx=ctx)
        return [{"id": a.id, "person": a.person,
                 "start_date": str(a.start_date), "end_date": str(a.end_date), "color": a.color}
                for a in absences]

@router.post("/api/gantt/absences", status_code=201)
async def api_add_absence(body: AbsenceCreate, request: Request):
    ctx = get_ctx(request)
    start = _parse_date(body.start_date, "start_date")
    end = _parse_date(body.end_date, "end_date")
    _ensure_date_order(start, end)
    person = body.person.strip()
    if not person:
        raise HTTPException(status_code=400, detail="Nome persona obbligatorio")
    color = _validate_color(body.color)
    with get_session() as session:
        a = crud.add_absence(session, person=person, start_date=start, end_date=end, ctx=ctx, color=color)
        return {"id": a.id, "person": a.person, "start_date": str(a.start_date), "end_date": str(a.end_date), "color": a.color}

@router.patch("/api/gantt/absences/{absence_id}")
async def api_edit_absence_color(absence_id: int, body: AbsenceColorUpdate, request: Request):
    ctx = get_ctx(request)
    color = _validate_color(body.color)
    with get_session() as session:
        a = session.get(crud.Absence, absence_id)
        if not a or a.context != ctx:
            raise HTTPException(status_code=404, detail="Assenza non trovata")
        a = crud.edit_absence_color(session, absence_id, color)
        return {"id": a.id, "person": a.person, "start_date": str(a.start_date), "end_date": str(a.end_date), "color": a.color}

@router.delete("/api/gantt/absences/{absence_id}", status_code=204)
async def api_delete_absence(absence_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        a = session.get(crud.Absence, absence_id)
        if not a or a.context != ctx:
            raise HTTPException(status_code=404, detail="Assenza non trovata")
        ok = crud.delete_absence(session, absence_id)
    if not ok: raise HTTPException(status_code=404, detail="Assenza non trovata")
