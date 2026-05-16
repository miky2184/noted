from fastapi import FastAPI, Request, Query, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List
import asyncio
import logging
import sys

logging.basicConfig(
    filename=Path("~/.noted/scheduler.log").expanduser(),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger("noted.scheduler")

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.engine import init_db, get_session, engine
from db import crud
from db.models import Document


def _do_scheduled_recap():
    """Generate today's recap for every context that has notes and no recap yet."""
    from db.config import get_schedule, set_scheduler_status
    schedule = get_schedule()
    recap_type = schedule.get("type", "daily") if schedule else "daily"
    _log.info("Scheduler avviato (type=%s)", recap_type)

    with get_session() as session:
        contexts = crud.get_contexts(session)

    for ctx_obj in contexts:
        ctx = ctx_obj.name
        try:
            with get_session() as session:
                if crud.get_recap(session, day=date.today(), ctx=ctx):
                    _log.info("ctx=%s: recap già presente, skip", ctx)
                    continue
                gantt = crud.get_gantt_data(session, ctx=ctx)
                if recap_type == "weekly":
                    notes = crud.get_notes_last_n_days(session, days=7, ctx=ctx)
                else:
                    notes = crud.get_notes_for_recap(session, day=date.today(), ctx=ctx)
                if not notes:
                    _log.info("ctx=%s: nessuna nota, skip", ctx)
                    continue
            if recap_type == "weekly":
                from ai.recap import generate_weekly_from_notes_sync
                summary = generate_weekly_from_notes_sync(notes, gantt=gantt)
            else:
                from ai.recap import generate_recap
                summary = generate_recap(notes, date.today(), gantt=gantt)
            with get_session() as session:
                crud.save_recap(session, summary=summary, notes_count=len(notes),
                                recap_date=date.today(), ctx=ctx)
            _log.info("ctx=%s: recap salvato (%d note)", ctx, len(notes))
        except Exception as exc:
            _log.error("ctx=%s: errore — %s", ctx, exc)
            set_scheduler_status(ok=False, error=str(exc))
            return

    set_scheduler_status(ok=True)


async def _scheduler_loop():
    from db.config import get_schedule
    # Startup check: run immediately if scheduled time has passed today and no recap yet
    schedule = get_schedule()
    if schedule:
        now = datetime.now()
        h, m = map(int, schedule["time"].split(":"))
        if now.weekday() in schedule["days"] and (now.hour > h or (now.hour == h and now.minute >= m)):
            await asyncio.get_event_loop().run_in_executor(None, _do_scheduled_recap)

    while True:
        # Sleep until next minute boundary
        await asyncio.sleep(60 - datetime.now().second)
        schedule = get_schedule()
        if not schedule:
            continue
        now = datetime.now()
        h, m = map(int, schedule["time"].split(":"))
        if now.weekday() in schedule["days"] and now.hour == h and now.minute == m:
            await asyncio.get_event_loop().run_in_executor(None, _do_scheduled_recap)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="noted dashboard", lifespan=lifespan)
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

def _doc_dict(d):
    return {
        "id": d.id,
        "note_id": d.note_id,
        "rel_path": d.rel_path,
        "orig_name": d.orig_name,
        "mime_type": d.mime_type,
        "size_bytes": d.size_bytes,
        "analysis": d.analysis,
        "created_at": d.created_at.isoformat(),
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
        note_ids = [n.id for n in notes]
        deps = crud.get_deps_bulk(session, note_ids)
        docs_map = crud.get_docs_bulk(session, note_ids)
    result = []
    for n in notes:
        d = _note_dict(n)
        nd = deps.get(n.id, {})
        d["blockers"] = nd.get("blocker_notes", [])
        d["blocking"] = nd.get("blocking_notes", [])
        d["docs"] = [_doc_dict(doc) for doc in docs_map.get(n.id, [])]
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


@app.get("/api/search")
async def api_search(request: Request, q: str = Query(""), limit: int = Query(20)):
    ctx = _get_ctx(request)
    if not q.strip():
        return []
    with get_session() as session:
        notes = crud.search_notes(session, query=q.strip(), ctx=ctx, limit=limit)
    return [_note_dict(n) for n in notes]


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


class MoveNote(BaseModel):
    status: Optional[str] = None
    column_ids: List[int] = []

@app.patch("/api/notes/{note_id}/move", status_code=204)
async def api_move_note(note_id: int, body: MoveNote, request: Request):
    from db.models import Note as NoteModel
    ctx = _get_ctx(request)
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


@app.get("/api/notes/{note_id}/deps")
async def api_get_deps(note_id: int, request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        blockers = crud.get_blockers(session, note_id)
        blocking = crud.get_blocking(session, note_id)
        return {
            "blockers": [{"id": n.id, "content": n.content[:80], "status": n.status} for n in blockers],
            "blocking": [{"id": n.id, "content": n.content[:80], "status": n.status} for n in blocking],
        }

class DepBody(BaseModel):
    blocker_id: int

@app.post("/api/notes/{note_id}/deps", status_code=201)
async def api_add_dep(note_id: int, body: DepBody, request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        blocker = session.get(crud.Note, body.blocker_id)
        if not blocker:
            raise HTTPException(status_code=404, detail="Nota blocker non trovata")
        dep = crud.add_dependency(session, note_id, body.blocker_id)
        if not dep:
            raise HTTPException(status_code=400, detail="Dipendenza non valida o già esistente")
        return {"id": dep.id, "note_id": dep.note_id, "blocker_id": dep.blocker_id}

@app.delete("/api/notes/{note_id}/deps/{blocker_id}", status_code=204)
async def api_remove_dep(note_id: int, blocker_id: int, request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note or note.context != ctx:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        crud.remove_dependency(session, note_id, blocker_id)


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    from db.config import get_doc_root
    return {"doc_root": get_doc_root()}


class SettingsUpdate(BaseModel):
    doc_root: Optional[str] = None


@app.patch("/api/settings", status_code=200)
async def api_update_settings(body: SettingsUpdate):
    from db.config import set_doc_root
    if body.doc_root is not None:
        set_doc_root(body.doc_root.strip())
    return {"ok": True}


# ── Documents ─────────────────────────────────────────────────────────────────

@app.post("/api/notes/{note_id}/docs", status_code=201)
async def api_upload_doc(note_id: int, file: UploadFile = File(...)):
    import hashlib, mimetypes, re
    from db.config import get_doc_root

    with get_session() as session:
        note = session.get(crud.Note, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        project = note.project
        ctx = note.context or "default"

    doc_root = Path(get_doc_root()).expanduser()

    ctx_slug  = re.sub(r'[^a-z0-9\-]', '_', ctx.lower()).strip('_') or 'default'
    proj_slug = re.sub(r'[^a-z0-9\-]', '_', (project or '').lower()).strip('_') or '_inbox'

    today_str = date.today().strftime('%Y%m%d')
    safe_name = re.sub(r'[^\w.\- ]', '_', file.filename or 'file')

    dest_dir = doc_root / ctx_slug / proj_slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    sha256 = hashlib.sha256(content).hexdigest()

    dest_name = f"{today_str}_{safe_name}"
    dest_path = dest_dir / dest_name
    if dest_path.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        dest_name = f"{today_str}_{stem}_{sha256[:6]}{suffix}"
        dest_path = dest_dir / dest_name

    dest_path.write_bytes(content)

    rel_path = f"{ctx_slug}/{proj_slug}/{dest_name}"
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0]

    with get_session() as session:
        doc = crud.add_document(session, note_id=note_id, rel_path=rel_path,
                                orig_name=file.filename or safe_name,
                                mime_type=mime, size_bytes=len(content), sha256=sha256)
    return _doc_dict(doc)


@app.get("/api/notes/{note_id}/docs")
async def api_get_docs(note_id: int):
    with get_session() as session:
        docs = crud.get_docs_for_note(session, note_id)
    return [_doc_dict(d) for d in docs]


@app.delete("/api/docs/{doc_id}", status_code=204)
async def api_delete_doc(doc_id: int, remove_file: bool = False):
    from db.config import get_doc_root
    with get_session() as session:
        doc = crud.delete_document(session, doc_id)
    if not doc:
        raise HTTPException(status_code=404)
    if remove_file:
        fp = Path(get_doc_root()).expanduser() / doc.rel_path
        if fp.is_file():
            fp.unlink()


@app.post("/api/docs/{doc_id}/open")
async def api_open_doc(doc_id: int):
    import subprocess
    from db.config import get_doc_root
    with get_session() as session:
        doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404)
    fp = Path(get_doc_root()).expanduser() / doc.rel_path
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="File non trovato sul disco")
    _open_path(fp)
    return {"ok": True}


@app.post("/api/docs/{doc_id}/open-folder")
async def api_open_doc_folder(doc_id: int):
    from db.config import get_doc_root
    with get_session() as session:
        doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404)
    folder = (Path(get_doc_root()).expanduser() / doc.rel_path).parent
    folder.mkdir(parents=True, exist_ok=True)
    _open_path(folder)
    return {"ok": True}


@app.post("/api/docs/open-folder-root")
async def api_open_doc_root():
    from db.config import get_doc_root
    folder = Path(get_doc_root()).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    _open_path(folder)
    return {"ok": True}


@app.get("/api/docs/{doc_id}/file")
async def api_serve_doc(doc_id: int):
    from fastapi.responses import FileResponse
    from db.config import get_doc_root
    with get_session() as session:
        doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404)
    doc_root = Path(get_doc_root()).expanduser()
    fp = doc_root / doc.rel_path
    try:
        fp.relative_to(doc_root)  # path traversal check
    except ValueError:
        raise HTTPException(status_code=403)
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="File non trovato")
    return FileResponse(str(fp), filename=doc.orig_name,
                        media_type=doc.mime_type or "application/octet-stream")


def _open_path(path: Path) -> None:
    import subprocess
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "linux":
        subprocess.Popen(["xdg-open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])


# ── Document listing ───────────────────────────────────────────────────────────

@app.get("/api/docs")
async def api_list_docs(request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        docs = crud.get_all_documents(session, ctx=ctx)
    return [_doc_dict(d) for d in docs]


# ── Document analysis ──────────────────────────────────────────────────────────

_MAX_DOCS        = 5
_MAX_IMAGE_BYTES = 1_048_576  # 1 MB per immagine

_DEPTH_LIMITS = {
    "low":    {"chars_per_doc": 2_000,  "total_chars": 6_000,  "max_tokens": 512},
    "medium": {"chars_per_doc": 6_000,  "total_chars": 24_000, "max_tokens": 1024},
    "high":   {"chars_per_doc": 15_000, "total_chars": 50_000, "max_tokens": 2048},
}


def _smart_truncate(text: str, limit: int) -> str:
    """Prendi inizio e fine del testo per non perdere le conclusioni."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n[…]\n\n" + text[-half:]


def _extract_text(fp: Path, mime: str | None, chars_limit: int = 6_000) -> tuple[str, str]:
    """Return (text, mode) where mode is 'text' or 'image'."""
    mime = mime or ""
    suffix = fp.suffix.lower()

    if mime.startswith("image/") or suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return ("", "image")

    if mime == "application/pdf" or suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(fp))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
            return (_smart_truncate(text, chars_limit), "text")
        except Exception as e:
            return (f"[Errore lettura PDF: {e}]", "text")

    if suffix in (".docx",) or "wordprocessingml" in mime:
        try:
            from docx import Document as DocxDoc
            doc = DocxDoc(str(fp))
            text = "\n".join(p.text for p in doc.paragraphs)
            return (_smart_truncate(text, chars_limit), "text")
        except Exception as e:
            return (f"[Errore lettura DOCX: {e}]", "text")

    # Fallback: plain text
    try:
        return (_smart_truncate(fp.read_text(errors="replace"), chars_limit), "text")
    except Exception:
        return ("[Formato non supportato]", "text")


_ANALYSIS_SYSTEM = """Sei un assistente che analizza documenti di lavoro e li trasforma in elementi strutturati per un'app di project management.
Rispondi SEMPRE e SOLO con JSON valido, senza testo prima o dopo."""

_ANALYSIS_USER = """Analizza questi documenti e fornisci un'analisi strutturata.

{docs_block}

Rispondi con questo JSON (tutti i campi obbligatori):
{{
  "summary": "riepilogo conciso in 3-5 frasi",
  "insights": ["insight 1", "insight 2", ...],
  "items": [
    {{
      "type": "note",
      "content": "testo della nota/todo",
      "project": "NOME_PROGETTO oppure null",
      "tags": "tag1,tag2 oppure null",
      "priority": "low|medium|high",
      "status": "todo|backlog|wip|null"
    }},
    {{
      "type": "milestone",
      "name": "nome della milestone",
      "project": "NOME_PROGETTO (obbligatorio)",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD"
    }}
  ]
}}

Suggerisci solo elementi concreti e azionabili. Le date delle milestone devono essere realistiche a partire da oggi ({today})."""


class AnalyzeDocsRequest(BaseModel):
    doc_ids: list[int]
    extra_instructions: Optional[str] = None
    depth: str = "medium"  # low | medium | high


@app.post("/api/analyze-docs")
async def api_analyze_docs(request: Request, body: AnalyzeDocsRequest):
    import base64, json as _json
    from db.config import get_doc_root, get_model
    from anthropic import Anthropic

    if not body.doc_ids:
        raise HTTPException(status_code=400, detail="Nessun documento selezionato")
    if len(body.doc_ids) > _MAX_DOCS:
        raise HTTPException(status_code=400,
            detail=f"Massimo {_MAX_DOCS} documenti per analisi (selezionati: {len(body.doc_ids)})")

    limits = _DEPTH_LIMITS.get(body.depth, _DEPTH_LIMITS["medium"])
    max_chars_per_doc = limits["chars_per_doc"]
    max_total_chars   = limits["total_chars"]
    max_tokens        = limits["max_tokens"]

    doc_root = Path(get_doc_root()).expanduser()
    client = Anthropic()
    model = get_model()

    with get_session() as session:
        docs = [session.get(Document, did) for did in body.doc_ids]
    docs = [d for d in docs if d]
    if not docs:
        raise HTTPException(status_code=404, detail="Documenti non trovati")

    # Build message content — mix text blocks and image blocks
    content_parts: list = []
    docs_block_lines: list[str] = []
    total_chars = 0

    for doc in docs:
        fp = doc_root / doc.rel_path
        if not fp.is_file():
            continue
        text, mode = _extract_text(fp, doc.mime_type, chars_limit=max_chars_per_doc)
        if mode == "image":
            img_bytes = fp.read_bytes()
            if len(img_bytes) > _MAX_IMAGE_BYTES:
                docs_block_lines.append(
                    f"--- Documento: {doc.orig_name} ---\n[immagine troppo grande, saltata]"
                )
                continue
            img_data = base64.standard_b64encode(img_bytes).decode()
            media_type = doc.mime_type or "image/png"
            if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                media_type = "image/png"
            content_parts.append({
                "type": "text",
                "text": f"--- Documento: {doc.orig_name} (immagine) ---"
            })
            content_parts.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": img_data}
            })
        else:
            remaining = max_total_chars - total_chars
            if remaining <= 0:
                docs_block_lines.append(
                    f"--- Documento: {doc.orig_name} ---\n[saltato: budget testo esaurito]"
                )
                continue
            text = text[:remaining]
            total_chars += len(text)
            docs_block_lines.append(f"--- Documento: {doc.orig_name} ---\n{text or '[vuoto]'}")

    from datetime import date as _date
    today_str = _date.today().isoformat()

    extra = f"\n\nIstruzioni aggiuntive: {body.extra_instructions}" if body.extra_instructions else ""
    user_text = _ANALYSIS_USER.format(
        docs_block="\n\n".join(docs_block_lines) or "[solo immagini]",
        today=today_str,
    ) + extra

    content_parts.append({"type": "text", "text": user_text})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": content_parts}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()
        result = _json.loads(raw)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Il modello non ha restituito JSON valido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Persist analysis on the document when a single doc was analysed
    if len(docs) == 1:
        summary = result.get("summary", "")
        if summary:
            with get_session() as session:
                crud.update_doc_analysis(session, docs[0].id, summary)
            result["saved_to_doc"] = True

    return result


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

@app.get("/api/gantt")
async def api_gantt(request: Request):
    ctx = _get_ctx(request)
    with get_session() as session:
        return crud.get_gantt_data(session, ctx=ctx)

@app.post("/api/gantt/projects", status_code=201)
async def api_add_gantt_project(request: Request, body: GanttProjectCreate):
    ctx = _get_ctx(request)
    with get_session() as session:
        p = crud.add_gantt_project(session, name=body.name, color=body.color,
                                   ctx=ctx, is_background=body.is_background)
        return {"id": p.id, "name": p.name, "color": p.color, "is_background": p.is_background}

@app.patch("/api/gantt/projects/{project_id}")
async def api_edit_gantt_project(project_id: int, body: GanttProjectUpdate):
    with get_session() as session:
        p = crud.edit_gantt_project(session, project_id, name=body.name, color=body.color,
                                    is_background=body.is_background)
    if not p: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return {"id": p.id, "name": p.name, "color": p.color, "is_background": p.is_background}

@app.delete("/api/gantt/projects/{project_id}", status_code=204)
async def api_delete_gantt_project(project_id: int):
    with get_session() as session:
        ok = crud.delete_gantt_project(session, project_id)
    if not ok: raise HTTPException(status_code=404, detail="Progetto non trovato")

@app.post("/api/gantt/milestones", status_code=201)
async def api_add_milestone(body: MilestoneCreate, request: Request):
    from db.models import GanttProject
    ctx = _get_ctx(request)
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
    from fastapi.responses import FileResponse
    from db.paths import db_path as get_db_path
    path = get_db_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Database non trovato: {path}")
    filename = f"noted_backup_{date.today().isoformat()}.db"
    return FileResponse(path, media_type="application/octet-stream",
                        filename=filename, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

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

@app.get("/api/local-ip")
async def api_local_ip(request: Request):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    port = request.url.port or 7979
    scheme = request.url.scheme
    return {"url": f"{scheme}://{ip}:{port}", "ip": ip, "port": port}


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


class ScheduleConfig(BaseModel):
    time: str
    days: List[int]
    type: str = "daily"

@app.get("/api/schedule")
async def api_get_schedule():
    from db.config import get_schedule, get_scheduler_status
    return {**(get_schedule() or {}), "last_run": get_scheduler_status()}

@app.get("/api/schedule/status")
async def api_scheduler_status():
    from db.config import get_scheduler_status
    return get_scheduler_status() or {}

@app.post("/api/schedule")
async def api_set_schedule(cfg: ScheduleConfig):
    import re
    if not re.match(r"^\d{2}:\d{2}$", cfg.time):
        raise HTTPException(status_code=400, detail="Formato orario non valido (usa HH:MM)")
    if not all(0 <= d <= 6 for d in cfg.days):
        raise HTTPException(status_code=400, detail="Giorni non validi (0=lun, 6=dom)")
    if cfg.type not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="Tipo non valido (daily o weekly)")
    from db.config import set_schedule
    set_schedule(cfg.time, cfg.days, cfg.type)
    return {"ok": True}

@app.delete("/api/schedule")
async def api_delete_schedule():
    from db.config import set_schedule
    set_schedule(None, None)
    return {"ok": True}


# ── Voice transcription ────────────────────────────────────────────────────────

_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            import ssl, whisper
            # macOS Python non usa i certificati di sistema → patch temporanea per il download del modello
            _orig = ssl._create_default_https_context
            ssl._create_default_https_context = ssl._create_unverified_context
            try:
                _whisper_model = whisper.load_model("base")
            finally:
                ssl._create_default_https_context = _orig
        except ImportError:
            raise HTTPException(status_code=501, detail="openai-whisper non installato. Esegui: pip install -e .")
    return _whisper_model

def _ensure_ffmpeg_in_path():
    """Aggiunge le dir Homebrew al PATH se ffmpeg non è già trovabile."""
    import os, shutil
    if shutil.which("ffmpeg"):
        return
    extras = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/homebrew/sbin"]
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(extras) + (":" + current if current else "")

@app.post("/api/voice/transcribe")
async def api_voice_transcribe(audio: UploadFile = File(...)):
    import tempfile, os
    _ensure_ffmpeg_in_path()
    suffix = ".webm" if "webm" in (audio.content_type or "") else ".mp4"
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Audio vuoto")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp_path = f.name
    try:
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(None, _get_whisper_model)
        result = await loop.run_in_executor(None, lambda: model.transcribe(tmp_path, language="it"))
        return {"text": result["text"].strip()}
    except Exception as exc:
        msg = str(exc)
        if "ffmpeg" in msg.lower() or "No such file or directory" in msg:
            msg = "ffmpeg non trovato. Installalo con: brew install ffmpeg"
        raise HTTPException(status_code=500, detail=msg)
    finally:
        os.unlink(tmp_path)
