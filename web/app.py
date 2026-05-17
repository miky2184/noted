import sys
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import crud
from db.engine import get_session, init_db
from web.deps import get_ctx, templates
from web.routers import backup, contexts, docs, gantt, notes, recaps, settings, voice, ollama
from web.services.scheduler_service import lifespan


app = FastAPI(title="noted dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

init_db()

app.include_router(contexts.router)
app.include_router(notes.router)
app.include_router(settings.router)
app.include_router(docs.router)
app.include_router(gantt.router)
app.include_router(recaps.router)
app.include_router(backup.router)
app.include_router(voice.router)
app.include_router(ollama.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, tag: str = "", project: str = ""):
    ctx = get_ctx(request)
    with get_session() as session:
        contexts_ = crud.get_contexts(session)
        notes_ = crud.get_notes(session, day=date.today(), tag=tag or None,
                                project=project or None, ctx=ctx, limit=50)
        recap = crud.get_recap(session, day=date.today(), ctx=ctx)
        recent_recaps = crud.get_recent_recaps(session, ctx=ctx)

    return templates.TemplateResponse(request, "index.html", {
        "notes": notes_,
        "recap": recap,
        "recent_recaps": recent_recaps,
        "today": date.today(),
        "filter_tag": tag,
        "filter_project": project,
        "contexts": [{"id": c.id, "name": c.name} for c in contexts_],
        "active_ctx": ctx,
    })
