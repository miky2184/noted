from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import date
from pathlib import Path
from typing import Optional, List
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.engine import init_db, get_session, engine
from db import crud

app = FastAPI(title="noted dashboard")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

init_db()


def _note_dict(n):
    return {
        "id": n.id,
        "content": n.content,
        "tags": n.tags_list(),
        "project": n.project,
        "priority": n.priority,
        "due_date": str(n.due_date) if n.due_date else None,
        "status": n.status,
        "assignee": n.assignee,
        "created_at": n.created_at.isoformat(),
    }

def _get_ctx(request: Request) -> str:
    return request.query_params.get("ctx", "default")


# ── Context ────────────────────────────────────────────────────────────────────

@app.get("/api/contexts")
async def api_get_contexts():
    with get_session() as session:
        return [{"id": c.id, "name": c.name} for c in crud.get_contexts(session)]

class ContextCreate(BaseModel):
    name: str

@app.post("/api/contexts", status_code=201)
async def api_add_context(body: ContextCreate):
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nome non valido")
    with get_session() as session:
        c = crud.add_context(session, name)
    return {"id": c.id, "name": c.name}

class ContextUpdate(BaseModel):
    name: str

@app.patch("/api/contexts/{ctx_id}")
async def api_rename_context(ctx_id: int, body: ContextUpdate):
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nome non valido")
    with get_session() as session:
        c = crud.rename_context(session, ctx_id, name)
    if not c:
        raise HTTPException(status_code=404, detail="Contesto non trovato")
    return {"id": c.id, "name": c.name}

@app.delete("/api/contexts/{ctx_id}", status_code=204)
async def api_delete_context(ctx_id: int):
    with get_session() as session:
        ok = crud.delete_context(session, ctx_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Contesto non eliminabile")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, tag: str = "", project: str = ""):
    ctx = _get_ctx(request)
    with get_session() as session:
        contexts = crud.get_contexts(session)
        notes = crud.get_notes(session, day=date.today(), tag=tag or None,
                               project=project or None, ctx=ctx, limit=50)
        recap = crud.get_recap(session, day=date.today(), ctx=ctx)
        recent_recaps = crud.get_recent_recaps(session, ctx=ctx)

    return templates.TemplateResponse(request, "index.html", {
        "notes": notes,
        "recap": recap,
        "recent_recaps": recent_recaps,
        "today": date.today(),
        "filter_tag": tag,
        "filter_project": project,
        "contexts": [{"id": c.id, "name": c.name} for c in contexts],
        "active_ctx": ctx,
    })


# ── Notes API ─────────────────────────────────────────────────────────────────

@app.get("/api/notes")
async def api_notes(
    request: Request,
    day: str = Query(None),
    tag: str = Query(None),
    project: str = Query(None),
    assignee: str = Query(None),
    status: str = Query(None),
):
    ctx = _get_ctx(request)
    target = date.fromisoformat(day) if day else None
    with get_session() as session:
        notes = crud.get_notes(session, day=target, tag=tag, project=project,
                               assignee=assignee, status=status, ctx=ctx)
    return [_note_dict(n) for n in notes]


class NoteCreate(BaseModel):
    content: str
    tags: Optional[str] = ""
    project: Optional[str] = None
    priority: Optional[str] = "medium"
    due_date: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None


@app.post("/api/notes", status_code=201)
async def api_add_note(request: Request, body: NoteCreate):
    ctx = _get_ctx(request)
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.add_note(
            session, content=body.content, tags=body.tags or "",
            project=body.project, priority=body.priority or "medium", due_date=due,
            status=body.status or None, assignee=body.assignee or None, ctx=ctx,
        )
    return _note_dict(note)


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    tags: Optional[str] = None
    project: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None


@app.patch("/api/notes/{note_id}")
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
    return _note_dict(note)


@app.get("/api/notes/due")
async def api_due_notes(request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        notes = crud.get_due_notes(session, ctx=ctx)
    return [_note_dict(n) for n in notes]


@app.delete("/api/notes/{note_id}", status_code=204)
async def api_delete_note(note_id: int):
    with get_session() as session:
        ok = crud.delete_note(session, note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Nota non trovata")


@app.get("/api/board")
async def api_board(
    request: Request,
    project: str = Query(None),
    assignee: str = Query(None),
):
    ctx = _get_ctx(request)
    with get_session() as session:
        notes = crud.get_board_notes(session, project=project or None,
                                     assignee=assignee or None, ctx=ctx)
        inbox = crud.get_inbox_notes(session, days=7, project=project or None,
                                     assignee=assignee or None, ctx=ctx)
    result = {"inbox": [], "backlog": [], "todo": [], "wip": [], "waiting": [], "blocked": [], "done": []}
    for n in inbox:
        result["inbox"].append(_note_dict(n))
    for n in notes:
        key = n.status if n.status in result else None
        if key:
            result[key].append(_note_dict(n))
    return result


# ── Gantt ──────────────────────────────────────────────────────────────────────

class GanttProjectCreate(BaseModel):
    name: str
    color: str = "#818cf8"

class GanttProjectUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class MilestoneCreate(BaseModel):
    project_id: int
    name: str
    start_date: str
    end_date: str

class MilestoneUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

@app.get("/api/gantt")
async def api_gantt(request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        return crud.get_gantt_data(session, ctx=ctx)

@app.post("/api/gantt/projects", status_code=201)
async def api_add_gantt_project(request: Request, body: GanttProjectCreate):
    ctx = _get_ctx(request)
    with get_session() as session:
        p = crud.add_gantt_project(session, name=body.name, color=body.color, ctx=ctx)
        return {"id": p.id, "name": p.name, "color": p.color}

@app.patch("/api/gantt/projects/{project_id}")
async def api_edit_gantt_project(project_id: int, body: GanttProjectUpdate):
    with get_session() as session:
        p = crud.edit_gantt_project(session, project_id, name=body.name, color=body.color)
    if not p: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": p.id, "name": p.name, "color": p.color}

@app.delete("/api/gantt/projects/{project_id}", status_code=204)
async def api_delete_gantt_project(project_id: int):
    with get_session() as session:
        ok = crud.delete_gantt_project(session, project_id)
    if not ok: raise HTTPException(status_code=404, detail="Progetto non trovato")

@app.post("/api/gantt/milestones", status_code=201)
async def api_add_milestone(body: MilestoneCreate):
    start = date.fromisoformat(body.start_date)
    end = date.fromisoformat(body.end_date)
    with get_session() as session:
        m = crud.add_milestone(session, project_id=body.project_id, name=body.name,
                               start_date=start, end_date=end)
        return {"id": m.id, "project_id": m.project_id, "name": m.name,
                "start_date": str(m.start_date), "end_date": str(m.end_date)}

@app.patch("/api/gantt/milestones/{milestone_id}")
async def api_edit_milestone(milestone_id: int, body: MilestoneUpdate):
    start = date.fromisoformat(body.start_date) if body.start_date else None
    end = date.fromisoformat(body.end_date) if body.end_date else None
    with get_session() as session:
        m = crud.edit_milestone(session, milestone_id, name=body.name,
                                start_date=start, end_date=end)
    if not m: raise HTTPException(status_code=404, detail="Milestone non trovata")
    return {"id": m.id, "project_id": m.project_id, "name": m.name,
            "start_date": str(m.start_date), "end_date": str(m.end_date)}

@app.delete("/api/gantt/milestones/{milestone_id}", status_code=204)
async def api_delete_milestone(milestone_id: int):
    with get_session() as session:
        ok = crud.delete_milestone(session, milestone_id)
    if not ok: raise HTTPException(status_code=404, detail="Milestone non trovata")


# ── Recap ──────────────────────────────────────────────────────────────────────

@app.post("/api/recap")
async def api_generate_recap(request: Request):
    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY non impostata")

    ctx = _get_ctx(request)
    with get_session() as session:
        notes = crud.get_notes_for_recap(session, day=date.today(), ctx=ctx)
        gantt = crud.get_gantt_data(session, ctx=ctx)

    if not notes:
        raise HTTPException(status_code=404, detail="Nessuna nota per oggi")

    from ai.recap import stream_recap

    chunks: list[str] = []

    def generate():
        for chunk in stream_recap(notes, date.today(), gantt=gantt):
            chunks.append(chunk)
            yield chunk
        with get_session() as session:
            crud.save_recap(session, summary="".join(chunks),
                            notes_count=len(notes), recap_date=date.today(), ctx=ctx)

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/api/recap/weekly")
async def api_generate_weekly_recap(request: Request):
    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY non impostata")

    ctx = _get_ctx(request)
    with get_session() as session:
        notes = crud.get_notes_last_n_days(session, days=7, ctx=ctx)
        gantt = crud.get_gantt_data(session, ctx=ctx)

    if not notes:
        raise HTTPException(status_code=404, detail="Nessuna nota negli ultimi 7 giorni")

    from ai.recap import stream_weekly_from_notes

    chunks: list[str] = []

    def generate():
        for chunk in stream_weekly_from_notes(notes, gantt=gantt):
            chunks.append(chunk)
            yield chunk
        with get_session() as session:
            crud.save_recap(session, summary="".join(chunks),
                            notes_count=len(notes), recap_date=date.today(), ctx=ctx)

    return StreamingResponse(generate(), media_type="text/plain")


@app.get("/api/recaps/recent")
async def api_recent_recaps(request: Request, days: int = 7):
    ctx = _get_ctx(request)
    with get_session() as session:
        recaps = crud.get_recent_recaps(session, days=days, ctx=ctx)
    return [
        {"id": r.id, "recap_date": r.recap_date.isoformat(),
         "created_at": r.created_at.isoformat(),
         "notes_count": r.notes_count, "summary": r.summary}
        for r in recaps
    ]

@app.get("/api/recaps/{recap_id}")
async def api_get_recap(recap_id: int):
    from db.models import Recap
    with get_session() as session:
        r = session.get(Recap, recap_id)
    if not r:
        raise HTTPException(status_code=404, detail="Recap non trovato")
    return {"id": r.id, "recap_date": r.recap_date.isoformat(),
            "created_at": r.created_at.isoformat(),
            "notes_count": r.notes_count, "summary": r.summary}

@app.delete("/api/recaps/{recap_id}", status_code=204)
async def api_delete_recap(recap_id: int):
    with get_session() as session:
        ok = crud.delete_recap(session, recap_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Recap non trovato")


# ── Backup ────────────────────────────────────────────────────────────────────

@app.get("/api/backup/db")
async def api_backup_db():
    import base64
    from db.paths import db_path as get_db_path
    path = get_db_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Database non trovato: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "filename": f"noted_backup_{date.today().isoformat()}.db",
        "encoding": "base64",
        "data": encoded,
    }

@app.post("/api/restore/db")
async def api_restore_db(request: Request):
    from db.paths import db_path as get_db_path
    body = await request.body()
    if not body.startswith(b"SQLite format 3"):
        raise HTTPException(status_code=400, detail="File non valido: non è un database SQLite")
    path = get_db_path()
    engine.dispose()
    path.write_bytes(body)
    init_db()
    return {"ok": True}


@app.post("/api/restore/json")
async def api_restore_json(request: Request):
    from db.models import Note, Recap, GanttProject, Milestone, Context
    from sqlmodel import delete as sql_delete
    from datetime import datetime

    body = await request.json()
    if "notes" not in body:
        raise HTTPException(status_code=400, detail="JSON non valido")

    with get_session() as session:
        session.exec(sql_delete(Milestone))
        session.exec(sql_delete(GanttProject))
        session.exec(sql_delete(Recap))
        session.exec(sql_delete(Note))
        session.exec(sql_delete(Context))

        for c in body.get("contexts", []):
            session.add(Context(id=c["id"], name=c["name"]))

        for n in body.get("notes", []):
            session.add(Note(
                id=n["id"], content=n["content"], tags=n.get("tags", ""),
                project=n.get("project"), priority=n.get("priority", "medium"),
                due_date=date.fromisoformat(n["due_date"]) if n.get("due_date") else None,
                status=n.get("status"), assignee=n.get("assignee"),
                context=n.get("context", "default"),
                created_at=datetime.fromisoformat(n["created_at"]),
                updated_at=datetime.fromisoformat(n.get("updated_at", n["created_at"])),
            ))

        for r in body.get("recaps", []):
            session.add(Recap(
                id=r["id"], recap_date=date.fromisoformat(r["recap_date"]),
                summary=r["summary"], notes_count=r.get("notes_count", 0),
                context=r.get("context", "default"),
                created_at=datetime.fromisoformat(r["created_at"]),
            ))

        for p in body.get("gantt_projects", []):
            session.add(GanttProject(
                id=p["id"], name=p["name"], color=p.get("color", "#818cf8"),
                context=p.get("context", "default"),
                created_at=datetime.fromisoformat(p["created_at"]),
            ))

        for m in body.get("milestones", []):
            session.add(Milestone(
                id=m["id"], project_id=m["project_id"], name=m["name"],
                start_date=date.fromisoformat(m["start_date"]),
                end_date=date.fromisoformat(m["end_date"]),
            ))

        session.commit()

    return {"ok": True}


@app.get("/api/backup/json")
async def api_backup_json():
    from fastapi.responses import JSONResponse
    from db.models import Note, Recap, GanttProject, Milestone, Context
    from sqlmodel import select
    import json

    with get_session() as session:
        contexts  = session.exec(select(Context)).all()
        notes     = session.exec(select(Note)).all()
        recaps    = session.exec(select(Recap)).all()
        projects  = session.exec(select(GanttProject)).all()
        milestones = session.exec(select(Milestone)).all()

    data = {
        "exported_at": date.today().isoformat(),
        "version": 1,
        "contexts": [{"id": c.id, "name": c.name} for c in contexts],
        "notes": [
            {"id": n.id, "content": n.content, "tags": n.tags,
             "project": n.project, "priority": n.priority,
             "due_date": str(n.due_date) if n.due_date else None,
             "status": n.status, "assignee": n.assignee,
             "context": n.context, "created_at": n.created_at.isoformat(),
             "updated_at": n.updated_at.isoformat()}
            for n in notes
        ],
        "recaps": [
            {"id": r.id, "recap_date": str(r.recap_date), "summary": r.summary,
             "notes_count": r.notes_count, "context": r.context,
             "created_at": r.created_at.isoformat()}
            for r in recaps
        ],
        "gantt_projects": [
            {"id": p.id, "name": p.name, "color": p.color,
             "context": p.context, "created_at": p.created_at.isoformat()}
            for p in projects
        ],
        "milestones": [
            {"id": m.id, "project_id": m.project_id, "name": m.name,
             "start_date": str(m.start_date), "end_date": str(m.end_date)}
            for m in milestones
        ],
    }

    filename = f"noted_backup_{date.today().isoformat()}.json"
    return JSONResponse(content=data, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'
    })


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config/model")
async def api_get_model():
    from db.config import get_model, MODELS
    current = get_model()
    return {"model": current, "label": next((k for k, v in MODELS.items() if v == current), current)}

@app.post("/api/config/model")
async def api_set_model(body: dict):
    from db.config import MODELS, set_model
    model_id = body.get("model", "")
    if model_id not in MODELS.values():
        raise HTTPException(status_code=400, detail="Modello non valido")
    set_model(model_id)
    return {"model": model_id}
