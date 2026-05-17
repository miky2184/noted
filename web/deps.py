from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def note_dict(n):
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


def doc_dict(d):
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


def get_ctx(request: Request) -> str:
    return request.query_params.get("ctx", "default")
