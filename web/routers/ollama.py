import json as _json
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError, field_validator

router = APIRouter()

_ENHANCE_PROMPT = """You are a work note assistant. Given this JSON payload, do two things:
1. Rewrite the text clearly and concisely (fix typos, keep it short, same language as the input)
2. Extract metadata from the content

Payload JSON: {payload}

Rules:
- "tags": 1-3 lowercase keywords comma-separated, or "" if none
- "project": the main project/company name in UPPERCASE, or null if absent
- "priority": one of low / medium / high
- "status": one of todo / backlog / wip / null (null if it's just a note, not a task)

Example input: "chiamare marco domani per aggiornamento sprint finops banca acme"
Example output: {{"content": "Chiamare Marco domani per aggiornamento sprint.", "tags": "sprint,call", "project": "ACME", "priority": "medium", "status": "todo"}}

Now process the raw note above. Reply with ONLY valid JSON, nothing else:"""


Priority = Literal["low", "medium", "high"]
Status = Literal["todo", "backlog", "wip"]


class EnhanceRequest(BaseModel):
    content: str


class OllamaSettings(BaseModel):
    url: Optional[str] = None
    model: Optional[str] = None


class EnhancedNote(BaseModel):
    content: str
    tags: str = ""
    project: Optional[str] = None
    priority: Priority = "medium"
    status: Optional[Status] = None

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, list):
            parts = [str(tag).strip().lower() for tag in value]
        else:
            parts = [part.strip().lower() for part in str(value).split(",")]
        parts = [part for part in parts if part][:3]
        return ",".join(parts)

    @field_validator("project", mode="before")
    @classmethod
    def normalize_project(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        project = str(value).strip()
        return project.upper() if project else None

    @field_validator("priority", "status", mode="before")
    @classmethod
    def normalize_enum(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None


def _parse_enhanced_note(raw_content: str, original_content: str) -> EnhancedNote:
    result = _json.loads(raw_content)
    if not isinstance(result, dict):
        raise ValueError("Ollama JSON response must be an object")
    result.setdefault("content", original_content)
    return EnhancedNote.model_validate(result)


@router.post("/api/notes/enhance")
async def api_enhance_note(body: EnhanceRequest):
    from db.config import get_ollama_url, get_ollama_model
    url   = get_ollama_url()
    model = get_ollama_model()

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Contenuto vuoto")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": _ENHANCE_PROMPT.format(
                    payload=_json.dumps({"raw_note": body.content}, ensure_ascii=False)
                ),
            }
        ],
        "stream": False,
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{url}/api/chat", json=payload)
        res.raise_for_status()
        raw = res.json()["message"]["content"].strip()
        result = _parse_enhanced_note(raw, body.content)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama non raggiungibile. Avvialo con: ollama serve")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama timeout — modello troppo lento o non caricato")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Ollama ha restituito un errore")
    except ValidationError:
        raise HTTPException(status_code=500, detail="Ollama ha restituito metadati non validi")
    except (_json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=500, detail="Ollama non ha restituito JSON valido")

    return {
        "content": result.content or body.content,
        "tags": result.tags,
        "project": result.project,
        "priority": result.priority,
        "status": result.status,
    }


@router.get("/api/ollama/status")
async def api_ollama_status():
    from db.config import get_ollama_url, get_ollama_model
    url   = get_ollama_url()
    model = get_ollama_model()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{url}/api/tags")
        res.raise_for_status()
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
