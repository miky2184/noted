from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


router = APIRouter()


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/api/settings")
async def api_get_settings():
    from db.config import get_doc_root
    return {"doc_root": get_doc_root()}


@router.get("/api/settings/favorite-ctx")
async def api_get_favorite_ctx():
    from db.config import get_favorite_ctx
    return {"favorite_ctx": get_favorite_ctx()}


class FavoriteCtxUpdate(BaseModel):
    name: str

@router.patch("/api/settings/favorite-ctx")
async def api_set_favorite_ctx(body: FavoriteCtxUpdate):
    from db.config import set_favorite_ctx
    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Nome contesto non valido")
    set_favorite_ctx(name)
    return {"ok": True, "favorite_ctx": name}


class SettingsUpdate(BaseModel):
    doc_root: Optional[str] = None


@router.patch("/api/settings", status_code=200)
async def api_update_settings(body: SettingsUpdate):
    from db.config import set_doc_root
    if body.doc_root is not None:
        set_doc_root(body.doc_root.strip())
    return {"ok": True}

# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/api/local-ip")
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


@router.get("/api/config/model")
async def api_get_model():
    from db.config import get_model, MODELS
    current = get_model()
    return {"model": current, "label": next((k for k, v in MODELS.items() if v == current), current)}

@router.post("/api/config/model")
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

@router.get("/api/schedule")
async def api_get_schedule():
    from db.config import get_schedule, get_scheduler_status
    return {**(get_schedule() or {}), "last_run": get_scheduler_status()}

@router.get("/api/schedule/status")
async def api_scheduler_status():
    from db.config import get_scheduler_status
    return get_scheduler_status() or {}

@router.post("/api/schedule")
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

@router.delete("/api/schedule")
async def api_delete_schedule():
    from db.config import set_schedule
    set_schedule(None, None)
    return {"ok": True}
