from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import date
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.engine import init_db, get_session
from db import crud

app = FastAPI(title="noted dashboard")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

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
        "created_at": n.created_at.isoformat(),
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, tag: str = "", project: str = ""):
    with get_session() as session:
        notes = crud.get_notes(session, day=date.today(), tag=tag or None, project=project or None, limit=50)
        recap = crud.get_recap(session, day=date.today())
        recent_recaps = crud.get_recent_recaps(session, days=7)

    return templates.TemplateResponse(request, "index.html", {
        "notes": notes,
        "recap": recap,
        "recent_recaps": recent_recaps,
        "today": date.today(),
        "filter_tag": tag,
        "filter_project": project,
    })


@app.get("/api/notes")
async def api_notes(
    day: str = Query(None),
    tag: str = Query(None),
    project: str = Query(None),
):
    target = date.fromisoformat(day) if day else None
    with get_session() as session:
        notes = crud.get_notes(session, day=target, tag=tag, project=project)
    return [_note_dict(n) for n in notes]


class NoteCreate(BaseModel):
    content: str
    tags: Optional[str] = ""
    project: Optional[str] = None
    priority: Optional[str] = "medium"
    due_date: Optional[str] = None
    status: Optional[str] = None


@app.post("/api/notes", status_code=201)
async def api_add_note(body: NoteCreate):
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.add_note(
            session, content=body.content, tags=body.tags or "",
            project=body.project, priority=body.priority or "medium", due_date=due,
            status=body.status or None,
        )
    return _note_dict(note)


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None


@app.patch("/api/notes/{note_id}")
async def api_update_note(note_id: int, body: NoteUpdate):
    due = date.fromisoformat(body.due_date) if body.due_date else None
    with get_session() as session:
        note = crud.edit_note(
            session, note_id,
            content=body.content,
            priority=body.priority,
            due_date=due,
            clear_due=body.due_date == "",
            status=body.status,
            clear_status=body.status == "",
        )
    if not note:
        raise HTTPException(status_code=404, detail="Nota non trovata")
    return _note_dict(note)


@app.get("/api/notes/due")
async def api_due_notes():
    with get_session() as session:
        notes = crud.get_due_notes(session)
    return [_note_dict(n) for n in notes]


@app.delete("/api/notes/{note_id}", status_code=204)
async def api_delete_note(note_id: int):
    with get_session() as session:
        ok = crud.delete_note(session, note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Nota non trovata")


@app.post("/api/recap")
async def api_generate_recap(save: bool = Query(False)):
    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY non impostata")

    with get_session() as session:
        notes = crud.get_notes_for_recap(session, day=date.today())

    if not notes:
        raise HTTPException(status_code=404, detail="Nessuna nota per oggi")

    from ai.recap import stream_recap

    chunks = []

    def generate():
        for chunk in stream_recap(notes, date.today()):
            chunks.append(chunk)
            yield chunk

    if save:
        # genera tutto, salva, poi invia
        summary = "".join(stream_recap(notes, date.today()))
        with get_session() as session:
            crud.save_recap(session, summary=summary, notes_count=len(notes), recap_date=date.today())
        return {"summary": summary, "notes_count": len(notes), "saved": True}

    return StreamingResponse(generate(), media_type="text/plain")


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


@app.delete("/api/recaps/{recap_id}", status_code=204)
async def api_delete_recap(recap_id: int):
    with get_session() as session:
        ok = crud.delete_recap(session, recap_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Recap non trovato")
