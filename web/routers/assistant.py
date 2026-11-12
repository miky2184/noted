"""Panoramica "Oggi" e assistente AI locale (domande sulle note, estrazione task).

L'AI qui è solo consultiva: risponde citando le note sorgente e propone task,
ma non crea né modifica nulla da sola.
"""
import asyncio
import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ai import llm
from db import crud
from db.engine import get_session
from web.deps import doc_dict, get_ctx, note_dict

router = APIRouter()

MAX_SOURCES = 12
MAX_SOURCE_CHARS = 900


@router.get("/api/overview")
async def api_overview(request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        data = crud.get_overview(session, ctx=ctx)
        groups = {k: data[k] for k in ("wip", "waiting", "stale", "recent")}
        ids = [n.id for notes in groups.values() for n in notes]
        deps = crud.get_deps_bulk(session, ids, ctx=ctx)
        docs_map = crud.get_docs_bulk(session, ids)

        def _enrich(n):
            d = note_dict(n)
            nd = deps.get(n.id, {})
            d["blockers"] = nd.get("blocker_notes", [])
            d["blocking"] = nd.get("blocking_notes", [])
            d["docs"] = [doc_dict(doc) for doc in docs_map.get(n.id, [])]
            return d

        out = {k: [_enrich(n) for n in notes] for k, notes in groups.items()}
    out.update({
        "inbox_count": data["inbox_count"],
        "open_count": data["open_count"],
        "projects": [{"name": p, "open": c} for p, c in data["projects"]],
    })
    return out


# ── Domande sulle note (retrieval FTS5 + LLM locale, risposta con citazioni) ──

_ASK_PROMPT = """Sei l'assistente di un archivio personale di note di lavoro. Rispondi alla domanda usando ESCLUSIVAMENTE le note qui sotto.

Regole:
- Se le note non contengono la risposta, dillo chiaramente: non inventare.
- Cita le note usate con il loro riferimento tra parentesi quadre, es. [N12].
- Rispondi in italiano, in modo conciso (bullet se utile).
- Oggi è {today}. Per priorità e scadenze considera date, priorità e stato indicati tra parentesi.

Note:
{sources}

Domanda: {question}"""


class AskRequest(BaseModel):
    question: str


_TASK_INTENT = re.compile(
    r"priorit|da fare|devo fare|dovrei|task|attivit|scadenz|in scadenza|in ritardo|aperti|aperte|"
    r"pendent|in sospeso|follow|in corso|prossim[ie] (passi|azioni)|cosa faccio|su cosa", re.IGNORECASE)


_PAST_INTENT = re.compile(r"ho fatto|svolt|completat|fatto|deciso|discuss|abbiamo|ieri|scorsa", re.IGNORECASE)


def _format_priorities(tasks) -> str:
    """Elenco dei task aperti per urgenza, costruito direttamente dai dati
    (nessun modello: istantaneo, funziona offline e non può inventare nulla)."""
    if not tasks:
        return "Non hai task aperti. 🎉"
    today = date.today()
    lines = [f"**Task aperti per urgenza** · {today.strftime('%d/%m/%Y')}"]
    current = None
    for n in tasks:
        band = crud.urgency_band(n, today)
        if band != current:
            lines.append(f"\n**{crud.URGENCY_LABELS[band]}**")
            current = band
        text = " ".join(n.content.split())
        text = text if len(text) <= 110 else text[:107] + "…"
        extra = []
        if n.project:
            extra.append(n.project)
        if n.due_date:
            days = (n.due_date - today).days
            when = "oggi" if days == 0 else (f"{-days} gg fa" if days < 0 else (f"tra {days} gg" if days <= 7 else n.due_date.strftime("%d/%m")))
            extra.append(f"scad. {when}")
        if n.status in ("waiting", "blocked"):
            extra.append("⏳ in attesa" if n.status == "waiting" else "🚫 bloccato")
        lines.append(f"- {text}" + (f" — _{' · '.join(extra)}_" if extra else ""))
    return "\n".join(lines)


def _time_window(question: str) -> tuple[date, date] | None:
    """Intervallo temporale citato esplicitamente nella domanda, se c'è."""
    q = question.lower()
    today = date.today()
    if "ieri" in q:
        return today - timedelta(days=1), today - timedelta(days=1)
    if re.search(r"\boggi\b", q):
        return today, today
    if "settimana scorsa" in q:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)
    if "questa settimana" in q:
        return today - timedelta(days=today.weekday()), today
    return None


def _format_source(n) -> str:
    meta = [n.created_at.strftime("%d/%m/%Y")]
    if n.cliente:
        meta.append(f"cliente:{n.cliente}")
    if n.project:
        meta.append(f"progetto:{n.project}")
    if n.status:
        meta.append(f"stato:{n.status}")
    if n.priority and n.priority != "medium":
        meta.append(f"priorità:{n.priority}")
    if n.due_date:
        meta.append(f"scadenza:{n.due_date}")
    return f"[N{n.id}] ({', '.join(meta)})\n{n.content[:MAX_SOURCE_CHARS]}"


@router.post("/api/ask")
async def api_ask(request: Request, body: AskRequest):
    ctx = get_ctx(request)
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Domanda vuota")

    with get_session() as session:
        notes = crud.search_notes_any(session, question, ctx=ctx, limit=MAX_SOURCES)
        # Domande su priorità/scadenze/cose da fare: la risposta sta nello stato
        # dei task aperti, non nel testo delle note — li mettiamo in testa.
        planning = bool(_TASK_INTENT.search(question)) and not _PAST_INTENT.search(question)
        if planning:
            tasks = crud.get_priority_tasks(session, ctx=ctx, limit=30)
            return {"answer": _format_priorities(tasks), "mode": "tasks",
                    "sources": [note_dict(n) for n in tasks]}
        # "oggi" in una domanda di pianificazione è l'orizzonte, non il giorno di
        # creazione delle note: la finestra temporale serve solo a "cosa ho fatto…"
        window = None if planning else _time_window(question)
        if window:
            seen = {n.id for n in notes}
            for n in crud.get_notes_between(session, window[0], window[1], ctx=ctx, limit=MAX_SOURCES):
                if n.id not in seen:
                    notes.append(n)
        notes = notes[:MAX_SOURCES]
        sources = [note_dict(n) for n in notes]
        prompt = _ASK_PROMPT.format(sources="\n\n".join(_format_source(n) for n in notes),
                                    question=question, today=date.today().strftime("%d/%m/%Y")) if notes else None

    if not prompt:
        return {"answer": "Non ho trovato note pertinenti alla domanda.", "sources": [], "mode": "notes"}

    try:
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, lambda: llm.generate(prompt, num_predict=700, num_ctx=llm.ctx_for(prompt, 700)))
    except llm.LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"answer": answer, "sources": sources, "mode": "notes"}


# ── Estrazione task da una nota (solo proposte, l'utente conferma) ────────────

_EXTRACT_PROMPT = """Analizza questa nota di lavoro ed estrai le attività (azioni da compiere) ESPLICITAMENTE menzionate.

Nota:
{content}

Regole:
- Includi solo azioni realmente presenti nel testo. Se non ce ne sono, restituisci una lista vuota.
- "due_date" in formato YYYY-MM-DD solo se una scadenza è esplicitamente indicata (data di oggi: {today}); altrimenti null.
- "priority": low, medium o high (medium se non indicata).
- "title": frase breve all'infinito o imperativo, nella lingua della nota.

Rispondi SOLO con JSON valido: {{"tasks": [{{"title": "...", "due_date": null, "priority": "medium"}}]}}"""


def _clean_tasks(data: dict) -> list[dict]:
    out = []
    for t in (data.get("tasks") or [])[:20]:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or "").strip()
        if not title:
            continue
        due = t.get("due_date")
        try:
            due = date.fromisoformat(str(due)).isoformat() if due else None
        except ValueError:
            due = None
        prio = str(t.get("priority") or "medium").lower()
        out.append({"title": title, "due_date": due,
                    "priority": prio if prio in ("low", "medium", "high") else "medium"})
    return out


@router.post("/api/notes/{note_id}/extract-tasks")
async def api_extract_tasks(note_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        note = crud.get_note_for_ctx(session, note_id, ctx=ctx)
        if not note:
            raise HTTPException(status_code=404, detail="Nota non trovata")
        if not note.content.strip():
            raise HTTPException(status_code=400, detail="Nota vuota")
        content, cliente, project = note.content, note.cliente, note.project
    prompt = _EXTRACT_PROMPT.format(content=content, today=date.today().isoformat())
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: llm.generate_json(prompt, num_predict=600, num_ctx=llm.ctx_for(prompt, 600)))
    except llm.LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"tasks": _clean_tasks(data), "cliente": cliente, "project": project}
