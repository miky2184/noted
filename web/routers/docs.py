import asyncio
from datetime import date
from functools import partial
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from db import crud
from db.engine import get_session
from db.models import Document
from web.deps import doc_dict, get_ctx
from web.services.document_service import DEPTH_LIMITS, MAX_DOCS, MAX_IMAGE_BYTES, extract_text, open_path


router = APIRouter()


# ── Documents ─────────────────────────────────────────────────────────────────

@router.post("/api/notes/{note_id}/docs", status_code=201)
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
    return doc_dict(doc)


@router.get("/api/notes/{note_id}/docs")
async def api_get_docs(note_id: int):
    with get_session() as session:
        docs = crud.get_docs_for_note(session, note_id)
    return [doc_dict(d) for d in docs]


@router.delete("/api/docs/{doc_id}", status_code=204)
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


@router.post("/api/docs/{doc_id}/open")
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
    open_path(fp)
    return {"ok": True}


@router.post("/api/docs/{doc_id}/open-folder")
async def api_open_doc_folder(doc_id: int):
    from db.config import get_doc_root
    with get_session() as session:
        doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404)
    folder = (Path(get_doc_root()).expanduser() / doc.rel_path).parent
    folder.mkdir(parents=True, exist_ok=True)
    open_path(folder)
    return {"ok": True}


@router.post("/api/docs/open-folder-root")
async def api_open_doc_root():
    from db.config import get_doc_root
    folder = Path(get_doc_root()).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    open_path(folder)
    return {"ok": True}


@router.get("/api/docs/{doc_id}/file")
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


# ── Document listing ───────────────────────────────────────────────────────────

@router.get("/api/docs")
async def api_list_docs(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        docs = crud.get_all_documents(session, ctx=ctx)
    return [doc_dict(d) for d in docs]


# ── Document analysis ──────────────────────────────────────────────────────────

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


@router.post("/api/analyze-docs")
async def api_analyze_docs(request: Request, body: AnalyzeDocsRequest):
    import base64, json as _json
    from db.config import get_doc_root, get_model
    from anthropic import Anthropic

    if not body.doc_ids:
        raise HTTPException(status_code=400, detail="Nessun documento selezionato")
    if len(body.doc_ids) > MAX_DOCS:
        raise HTTPException(status_code=400,
            detail=f"Massimo {MAX_DOCS} documenti per analisi (selezionati: {len(body.doc_ids)})")

    limits = DEPTH_LIMITS.get(body.depth, DEPTH_LIMITS["medium"])
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
        text, mode = extract_text(fp, doc.mime_type, chars_limit=max_chars_per_doc)
        if mode == "image":
            img_bytes = fp.read_bytes()
            if len(img_bytes) > MAX_IMAGE_BYTES:
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
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(
                client.messages.create,
                model=model,
                max_tokens=max_tokens,
                system=_ANALYSIS_SYSTEM,
                messages=[{"role": "user", "content": content_parts}],
            ),
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
