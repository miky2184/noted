"""Raccoglitore di link (OneDrive, Google Drive, SharePoint, web) per cliente/progetto."""
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import select

from db import crud
from db.engine import get_session
from db.models import Note
from web.deps import get_ctx

router = APIRouter()


def _clean_url(url: str) -> str:
    """Solo http(s): un href `javascript:` salvato e poi reso cliccabile sarebbe un XSS."""
    url = (url or "").strip()
    if urlparse(url).scheme.lower() not in ("http", "https") or not urlparse(url).netloc:
        raise HTTPException(status_code=400, detail="Link non valido: deve iniziare con http:// o https://")
    return url


def link_dict(l) -> dict:
    return {
        "id": l.id, "url": l.url, "title": l.title, "cliente": l.cliente, "project": l.project,
        "note_id": l.note_id, "source": crud.link_source(l.url),
        "created_at": l.created_at.isoformat(),
    }


class LinkCreate(BaseModel):
    url: str
    title: str = ""
    cliente: Optional[str] = None
    project: Optional[str] = None


class LinkUpdate(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    cliente: Optional[str] = None
    project: Optional[str] = None


@router.get("/api/links")
async def api_links(request: Request, q: str = Query(""), cliente: str = Query(""),
                    project: str = Query(""), sort: str = Query("recent")):
    ctx = get_ctx(request)
    with get_session() as session:
        links = crud.get_links(session, ctx=ctx, query=q.strip(), cliente=cliente or None,
                               project=project or None, sort=sort)
    return [link_dict(l) for l in links]


@router.post("/api/links", status_code=201)
async def api_add_link(request: Request, body: LinkCreate):
    ctx = get_ctx(request)
    url = _clean_url(body.url)
    with get_session() as session:
        if session.exec(select(crud.Link).where(crud.Link.context == ctx, crud.Link.url == url)).first():
            raise HTTPException(status_code=409, detail="Questo link è già salvato")
        link = crud.add_link(session, url, body.title, body.cliente, body.project, ctx=ctx)
    return link_dict(link)


@router.patch("/api/links/{link_id}")
async def api_update_link(link_id: int, request: Request, body: LinkUpdate):
    ctx = get_ctx(request)
    url = _clean_url(body.url) if body.url is not None else None
    with get_session() as session:
        link = crud.edit_link(session, link_id, ctx, url=url, title=body.title,
                              cliente=body.cliente, project=body.project)
    if not link:
        raise HTTPException(status_code=404, detail="Link non trovato")
    return link_dict(link)


@router.delete("/api/links/{link_id}", status_code=204)
async def api_delete_link(link_id: int, request: Request):
    ctx = get_ctx(request)
    with get_session() as session:
        ok = crud.delete_link(session, link_id, ctx)
    if not ok:
        raise HTTPException(status_code=404, detail="Link non trovato")


@router.post("/api/links/import-from-notes")
async def api_import_links_from_notes(request: Request):
    """Cerca gli URL nelle note già esistenti e li salva (senza duplicare)."""
    ctx = get_ctx(request)
    created = 0
    with get_session() as session:
        for note in session.exec(select(Note).where(Note.context == ctx, Note.content.like("%http%"))).all():
            created += crud.sync_links_from_note(session, note)
    return {"created": created}
