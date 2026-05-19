from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import crud
from db.engine import get_session
from web.deps import get_ctx


router = APIRouter()


# ── Gantt ──────────────────────────────────────────────────────────────────────

class GanttProjectCreate(BaseModel):
    name: str
    color: str = "#818cf8"
    is_background: bool = False

class GanttProjectUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    is_background: Optional[bool] = None

class MilestoneCreate(BaseModel):
    project_id: int
    name: str
    start_date: str
    end_date: str

class MilestoneUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} non valida")


def _ensure_date_order(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(status_code=400, detail="La data fine non può precedere la data inizio")

@router.get("/api/gantt")
async def api_gantt(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        return crud.get_gantt_data(session, ctx=ctx)

@router.post("/api/gantt/projects", status_code=201)
async def api_add_gantt_project(request: Request, body: GanttProjectCreate):
    ctx = get_ctx(request)
    with get_session() as session:
        p = crud.add_gantt_project(session, name=body.name, color=body.color,
                                   ctx=ctx, is_background=body.is_background)
        return {"id": p.id, "name": p.name, "color": p.color, "is_background": p.is_background}

@router.patch("/api/gantt/projects/{project_id}")
async def api_edit_gantt_project(project_id: int, body: GanttProjectUpdate, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        project = session.get(crud.GanttProject, project_id)
        if not project or project.context != ctx:
            raise HTTPException(status_code=404, detail="Progetto non trovato")
        p = crud.edit_gantt_project(session, project_id, name=body.name, color=body.color,
                                    is_background=body.is_background)
    if not p: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": p.id, "name": p.name, "color": p.color, "is_background": p.is_background}

@router.delete("/api/gantt/projects/{project_id}", status_code=204)
async def api_delete_gantt_project(project_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        project = session.get(crud.GanttProject, project_id)
        if not project or project.context != ctx:
            raise HTTPException(status_code=404, detail="Progetto non trovato")
        ok = crud.delete_gantt_project(session, project_id)
    if not ok: raise HTTPException(status_code=404, detail="Progetto non trovato")

@router.post("/api/gantt/milestones", status_code=201)
async def api_add_milestone(body: MilestoneCreate, request: Request):
    from db.models import GanttProject
    ctx = get_ctx(request)
    start = _parse_date(body.start_date, "start_date")
    end = _parse_date(body.end_date, "end_date")
    _ensure_date_order(start, end)
    with get_session() as session:
        project = session.get(GanttProject, body.project_id)
        if not project or project.context != ctx:
            raise HTTPException(status_code=404, detail="Progetto non trovato")
        m = crud.add_milestone(session, project_id=body.project_id, name=body.name,
                               start_date=start, end_date=end)
        project_name = project.name if project else None
        if not (project and project.is_background):
            note = crud.add_note(session, content=body.name, tags="milestone", project=project_name,
                          status="todo", due_date=end, ctx=ctx)
            m.note_id = note.id
            session.add(m)
            session.commit()
        return {"id": m.id, "project_id": m.project_id, "name": m.name,
                "start_date": str(m.start_date), "end_date": str(m.end_date),
                "note_id": m.note_id}

@router.get("/api/gantt/milestones/for-project")
async def api_milestones_for_project(project: str, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        milestones = crud.get_milestones_by_project_name(session, project, ctx)
        return {"milestones": [
            {"id": m.id, "name": m.name, "end_date": str(m.end_date)}
            for m in milestones
        ]}

@router.patch("/api/gantt/milestones/{milestone_id}")
async def api_edit_milestone(milestone_id: int, body: MilestoneUpdate, request: Request):
    ctx = get_ctx(request)
    start = _parse_date(body.start_date, "start_date") if body.start_date else None
    end = _parse_date(body.end_date, "end_date") if body.end_date else None
    with get_session() as session:
        milestone = session.get(crud.Milestone, milestone_id)
        project = session.get(crud.GanttProject, milestone.project_id) if milestone else None
        if not milestone or not project or project.context != ctx:
            raise HTTPException(status_code=404, detail="Milestone non trovata")
        next_start = start or milestone.start_date
        next_end = end or milestone.end_date
        _ensure_date_order(next_start, next_end)
        m = crud.edit_milestone(session, milestone_id, name=body.name,
                                start_date=start, end_date=end)
    if not m: raise HTTPException(status_code=404, detail="Milestone non trovata")
    return {"id": m.id, "project_id": m.project_id, "name": m.name,
            "start_date": str(m.start_date), "end_date": str(m.end_date)}

@router.delete("/api/gantt/milestones/{milestone_id}", status_code=204)
async def api_delete_milestone(milestone_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        milestone = session.get(crud.Milestone, milestone_id)
        project = session.get(crud.GanttProject, milestone.project_id) if milestone else None
        if not milestone or not project or project.context != ctx:
            raise HTTPException(status_code=404, detail="Milestone non trovata")
        ok = crud.delete_milestone(session, milestone_id)
    if not ok: raise HTTPException(status_code=404, detail="Milestone non trovata")
