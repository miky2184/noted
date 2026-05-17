from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.engine import get_session
from db import crud


router = APIRouter()


# ── Context ────────────────────────────────────────────────────────────────────

@router.get("/api/contexts")
async def api_get_contexts():
    with get_session() as session:
        return [{"id": c.id, "name": c.name} for c in crud.get_contexts(session)]

class ContextCreate(BaseModel):
    name: str

@router.post("/api/contexts", status_code=201)
async def api_add_context(body: ContextCreate):
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nome non valido")
    with get_session() as session:
        c = crud.add_context(session, name)
    return {"id": c.id, "name": c.name}

class ContextUpdate(BaseModel):
    name: str

@router.patch("/api/contexts/{ctx_id}")
async def api_rename_context(ctx_id: int, body: ContextUpdate):
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nome non valido")
    with get_session() as session:
        c = crud.rename_context(session, ctx_id, name)
    if not c:
        raise HTTPException(status_code=404, detail="Contesto non trovato")
    return {"id": c.id, "name": c.name}

@router.delete("/api/contexts/{ctx_id}", status_code=204)
async def api_delete_context(ctx_id: int):
    with get_session() as session:
        ok = crud.delete_context(session, ctx_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Contesto non eliminabile")
