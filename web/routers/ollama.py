from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import httpx, json as _json

router = APIRouter()

_ENHANCE_PROMPT = """You are a work note assistant. Given this raw note, do two things:
1. Rewrite the text clearly and concisely (fix typos, keep it short, same language as the input)
2. Extract metadata from the content

Raw note: {content}

Rules:
- "tags": 1-3 lowercase keywords comma-separated, or "" if none
- "project": the main project/company name in UPPERCASE, or null if absent
- "priority": one of low / medium / high
- "status": one of todo / backlog / wip / null (null if it's just a note, not a task)

Example input: "chiamare marco domani per aggiornamento sprint finops banca acme"
Example output: {{"content": "Chiamare Marco domani per aggiornamento sprint.", "tags": "sprint,call", "project": "ACME", "priority": "medium", "status": "todo"}}

Now process the raw note above. Reply with ONLY valid JSON, nothing else:"""


class EnhanceRequest(BaseModel):
    content: str


class OllamaSettings(BaseModel):
    url: Optional[str] = None
    model: Optional[str] = None


@router.post("/api/notes/enhance")
async def api_enhance_note(body: EnhanceRequest):
    from db.config import get_ollama_url, get_ollama_model
    url   = get_ollama_url()
    model = get_ollama_model()

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Contenuto vuoto")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": _ENHANCE_PROMPT.format(content=body.content)}],
        "stream": False,
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{url}/api/chat", json=payload)
        res.raise_for_status()
        raw = res.json()["message"]["content"].strip()
        result = _json.loads(raw)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama non raggiungibile. Avvialo con: ollama serve")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama timeout — modello troppo lento o non caricato")
    except (_json.JSONDecodeError, KeyError):
        raise HTTPException(status_code=500, detail="Ollama non ha restituito JSON valido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "content":  result.get("content", body.content),
        "tags":     result.get("tags") or "",
        "project":  result.get("project") or None,
        "priority": result.get("priority") or "medium",
        "status":   result.get("status") or None,
    }


@router.get("/api/ollama/status")
async def api_ollama_status():
    from db.config import get_ollama_url, get_ollama_model
    url   = get_ollama_url()
    model = get_ollama_model()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{url}/api/tags")
        models = [m["name"] for m in res.json().get("models", [])]
        return {"ok": True, "url": url, "model": model, "models": models}
    except Exception:
        return {"ok": False, "url": url, "model": model, "models": []}


@router.get("/api/ollama/settings")
async def api_get_ollama_settings():
    from db.config import get_ollama_url, get_ollama_model
    return {"url": get_ollama_url(), "model": get_ollama_model()}


@router.patch("/api/ollama/settings")
async def api_set_ollama_settings(body: OllamaSettings):
    from db.config import set_ollama_url, set_ollama_model
    if body.url is not None:
        set_ollama_url(body.url.strip())
    if body.model is not None:
        set_ollama_model(body.model.strip())
    return {"ok": True}
