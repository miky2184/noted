from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from db import crud
from db.engine import get_session
from web.deps import get_ctx
from web.services.recap_service import RecapError, stream_daily_recap, stream_weekly_recap


router = APIRouter()


def _recap_response(stream_factory):
    try:
        generator = stream_factory()
        return StreamingResponse(generator, media_type="text/plain")
    except RecapError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/recap")
async def api_generate_recap(request: Request):
    ctx = get_ctx(request)
    return _recap_response(lambda: stream_daily_recap(ctx))


@router.post("/api/recap/weekly")
async def api_generate_weekly_recap(request: Request):
    ctx = get_ctx(request)
    return _recap_response(lambda: stream_weekly_recap(ctx))


@router.get("/api/recaps/recent")
async def api_recent_recaps(request: Request, days: int = 7):
    ctx = get_ctx(request)
    with get_session() as session:
        recaps = crud.get_recent_recaps(session, days=days, ctx=ctx)
    return [
        {"id": r.id, "recap_date": r.recap_date.isoformat(),
         "created_at": r.created_at.isoformat(),
         "notes_count": r.notes_count, "summary": r.summary}
        for r in recaps
    ]


@router.get("/api/recaps/{recap_id}")
async def api_get_recap(recap_id: int):
    from db.models import Recap
    with get_session() as session:
        r = session.get(Recap, recap_id)
    if not r:
        raise HTTPException(status_code=404, detail="Recap non trovato")
    return {"id": r.id, "recap_date": r.recap_date.isoformat(),
            "created_at": r.created_at.isoformat(),
            "notes_count": r.notes_count, "summary": r.summary}


@router.delete("/api/recaps/{recap_id}", status_code=204)
async def api_delete_recap(recap_id: int):
    with get_session() as session:
        ok = crud.delete_recap(session, recap_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Recap non trovato")
