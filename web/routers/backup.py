from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from web.services.backup_service import (
    database_path,
    export_json_data,
    json_backup_filename,
    restore_json_data,
    restore_sqlite_bytes,
    sqlite_backup_filename,
)


router = APIRouter()


@router.get("/api/backup/db")
async def api_backup_db():
    path = database_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Database non trovato: {path}")
    filename = sqlite_backup_filename()
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/restore/db")
async def api_restore_db(request: Request):
    body = await request.body()
    try:
        backup_path = restore_sqlite_bytes(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "backup_path": str(backup_path) if backup_path else None}


@router.post("/api/restore/json")
async def api_restore_json(request: Request):
    body = await request.json()
    try:
        restore_json_data(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/api/backup/json")
async def api_backup_json():
    filename = json_backup_filename()
    return JSONResponse(
        content=export_json_data(),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
