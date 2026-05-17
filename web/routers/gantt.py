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
async def api_edit_gantt_project(project_id: int, body: GanttProjectUpdate):
    with get_session() as session:
        p = crud.edit_gantt_project(session, project_id, name=body.name, color=body.color,
                                    is_background=body.is_background)
    if not p: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": p.id, "name": p.name, "color": p.color, "is_background": p.is_background}

@router.delete("/api/gantt/projects/{project_id}", status_code=204)
async def api_delete_gantt_project(project_id: int):
    with get_session() as session:
        ok = crud.delete_gantt_project(session, project_id)
    if not ok: raise HTTPException(status_code=404, detail="Progetto non trovato")

@router.post("/api/gantt/milestones", status_code=201)
async def api_add_milestone(body: MilestoneCreate, request: Request):
    from db.models import GanttProject
    ctx = get_ctx(request)
    start = date.fromisoformat(body.start_date)
    end = date.fromisoformat(body.end_date)
    with get_session() as session:
        m = crud.add_milestone(session, project_id=body.project_id, name=body.name,
                               start_date=start, end_date=end)
        project = session.get(GanttProject, body.project_id)
        project_name = project.name if project else None
        if not (project and project.is_background):
            crud.add_note(session, content=body.name, tags="milestone", project=project_name,
                          status="todo", due_date=end, ctx=ctx)
        return {"id": m.id, "project_id": m.project_id, "name": m.name,
                "start_date": str(m.start_date), "end_date": str(m.end_date)}

@router.patch("/api/gantt/milestones/{milestone_id}")
async def api_edit_milestone(milestone_id: int, body: MilestoneUpdate):
    start = date.fromisoformat(body.start_date) if body.start_date else None
    end = date.fromisoformat(body.end_date) if body.end_date else None
    with get_session() as session:
        m = crud.edit_milestone(session, milestone_id, name=body.name,
                                start_date=start, end_date=end)
    if not m: raise HTTPException(status_code=404, detail="Milestone non trovata")
    return {"id": m.id, "project_id": m.project_id, "name": m.name,
            "start_date": str(m.start_date), "end_date": str(m.end_date)}

@router.delete("/api/gantt/milestones/{milestone_id}", status_code=204)
async def api_delete_milestone(milestone_id: int):
    with get_session() as session:
        ok = crud.delete_milestone(session, milestone_id)
    if not ok: raise HTTPException(status_code=404, detail="Milestone non trovata")
