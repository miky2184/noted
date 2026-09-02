from datetime import date, datetime
from pathlib import Path
import shutil
import sqlite3
import tempfile

from sqlalchemy.engine import make_url
from sqlmodel import delete as sql_delete, select

from db import crud
from db.engine import DATABASE_URL, engine, get_session, init_db
from db.models import Context, Document, GanttProject, Stream, Note, NoteDependency, Recap


def sqlite_backup_filename() -> str:
    return f"noted_backup_{date.today().isoformat()}.db"


def json_backup_filename() -> str:
    return f"noted_backup_{date.today().isoformat()}.json"


def database_path() -> Path:
    url = make_url(DATABASE_URL)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("Backup SQLite disponibile solo per database SQLite su file")
    return Path(url.database)


def export_json_data() -> dict:
    with get_session() as session:
        contexts = session.exec(select(Context)).all()
        notes = session.exec(select(Note)).all()
        recaps = session.exec(select(Recap)).all()
        projects = session.exec(select(GanttProject)).all()
        streams = session.exec(select(Stream)).all()
        documents = session.exec(select(Document)).all()
        dependencies = session.exec(select(NoteDependency)).all()

    return {
        "exported_at": date.today().isoformat(),
        "version": 3,
        "contexts": [{"id": c.id, "name": c.name} for c in contexts],
        "notes": [
            {"id": n.id, "content": n.content, "tags": n.tags,
             "project": n.project, "priority": n.priority,
             "due_date": str(n.due_date) if n.due_date else None,
             "status": n.status, "assignee": n.assignee,
             "context": n.context, "sort_order": n.sort_order,
             "milestone_id": n.milestone_id,
             "created_at": n.created_at.isoformat(),
             "updated_at": n.updated_at.isoformat()}
            for n in notes
        ],
        "recaps": [
            {"id": r.id, "recap_date": str(r.recap_date), "summary": r.summary,
             "notes_count": r.notes_count, "context": r.context,
             "created_at": r.created_at.isoformat()}
            for r in recaps
        ],
        "gantt_projects": [
            {"id": p.id, "name": p.name, "color": p.color,
             "is_background": p.is_background, "archived": p.archived,
             "client_id": p.client_id,
             "start_date": str(p.start_date) if p.start_date else None,
             "end_date": str(p.end_date) if p.end_date else None,
             "context": p.context, "created_at": p.created_at.isoformat()}
            for p in projects
        ],
        "streams": [
            {"id": s.id, "project_id": s.project_id, "name": s.name,
             "start_date": str(s.start_date) if s.start_date else None,
             "end_date": str(s.end_date) if s.end_date else None,
             "note_id": s.note_id}
            for s in streams
        ],
        # Files themselves stay on disk under doc_root — only the pointer is
        # backed up here, same as the rest of the app's document handling
        # (see README "Gestione documenti"). Restoring on another machine
        # without also copying doc_root will leave these pointing at
        # not-yet-present files.
        "documents": [
            {"id": d.id, "note_id": d.note_id, "rel_path": d.rel_path,
             "orig_name": d.orig_name, "mime_type": d.mime_type,
             "size_bytes": d.size_bytes, "sha256": d.sha256, "analysis": d.analysis,
             "created_at": d.created_at.isoformat()}
            for d in documents
        ],
        "dependencies": [
            {"id": dep.id, "note_id": dep.note_id, "blocker_id": dep.blocker_id,
             "created_at": dep.created_at.isoformat()}
            for dep in dependencies
        ],
    }


def restore_json_data(body: dict) -> None:
    if "notes" not in body:
        raise ValueError("JSON non valido")

    with get_session() as session:
        # children first (FK order), so a partial restore never leaves
        # dangling Document/NoteDependency rows behind
        session.exec(sql_delete(Document))
        session.exec(sql_delete(NoteDependency))
        session.exec(sql_delete(Stream))
        session.exec(sql_delete(GanttProject))
        session.exec(sql_delete(Recap))
        session.exec(sql_delete(Note))
        session.exec(sql_delete(Context))

        for c in body.get("contexts", []):
            session.add(Context(id=c["id"], name=c["name"]))

        for n in body.get("notes", []):
            session.add(Note(
                id=n["id"], content=n["content"], tags=n.get("tags", ""),
                project=n.get("project"), priority=n.get("priority", "medium"),
                due_date=date.fromisoformat(n["due_date"]) if n.get("due_date") else None,
                status=n.get("status"), assignee=n.get("assignee"),
                context=n.get("context", "default"),
                sort_order=n.get("sort_order", 0),
                milestone_id=n.get("milestone_id"),
                created_at=datetime.fromisoformat(n["created_at"]),
                updated_at=datetime.fromisoformat(n.get("updated_at", n["created_at"])),
            ))

        for r in body.get("recaps", []):
            session.add(Recap(
                id=r["id"], recap_date=date.fromisoformat(r["recap_date"]),
                summary=r["summary"], notes_count=r.get("notes_count", 0),
                context=r.get("context", "default"),
                created_at=datetime.fromisoformat(r["created_at"]),
            ))

        for p in body.get("gantt_projects", []):
            session.add(GanttProject(
                id=p["id"], name=p["name"], color=p.get("color", "#818cf8"),
                is_background=p.get("is_background", False), archived=p.get("archived", False),
                # client_id non ripristinato: Client non fa parte del backup JSON
                # (gap pre-esistente), quindi un id qui punterebbe a una riga
                # inesistente — il progetto torna semplicemente "senza cliente".
                start_date=date.fromisoformat(p["start_date"]) if p.get("start_date") else None,
                end_date=date.fromisoformat(p["end_date"]) if p.get("end_date") else None,
                context=p.get("context", "default"),
                created_at=datetime.fromisoformat(p["created_at"]),
            ))

        # "streams" è il nome corrente; "milestones" resta supportato in lettura
        # per i backup JSON esportati prima del rename Milestone -> Stream.
        for s in body.get("streams") or body.get("milestones") or []:
            session.add(Stream(
                id=s["id"], project_id=s["project_id"], name=s["name"],
                start_date=date.fromisoformat(s["start_date"]) if s.get("start_date") else None,
                end_date=date.fromisoformat(s["end_date"]) if s.get("end_date") else None,
                note_id=s.get("note_id"),
            ))

        for d in body.get("documents", []):
            session.add(Document(
                id=d["id"], note_id=d.get("note_id"), rel_path=d["rel_path"],
                orig_name=d["orig_name"], mime_type=d.get("mime_type"),
                size_bytes=d.get("size_bytes"), sha256=d.get("sha256"),
                analysis=d.get("analysis"),
                created_at=datetime.fromisoformat(d["created_at"]),
            ))

        for dep in body.get("dependencies", []):
            session.add(NoteDependency(
                id=dep["id"], note_id=dep["note_id"], blocker_id=dep["blocker_id"],
                created_at=datetime.fromisoformat(dep["created_at"]),
            ))

        session.commit()


def _validate_sqlite_file(path: Path) -> None:
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA schema_version").fetchone()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError("File non valido: database SQLite non leggibile") from exc

    if not integrity or integrity[0] != "ok":
        raise ValueError("File non valido: integrity_check fallito")


def _sidecar_paths(path: Path) -> list[Path]:
    return [path.with_name(path.name + suffix) for suffix in ("-wal", "-shm")]


def _backup_current_database(path: Path) -> Path | None:
    if not path.exists():
        return None

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.pre_restore_{stamp}")
    try:
        with sqlite3.connect(path) as src, sqlite3.connect(backup_path) as dst:
            src.backup(dst)
    except sqlite3.DatabaseError:
        shutil.copy2(path, backup_path)
        for sidecar in _sidecar_paths(path):
            if sidecar.exists():
                shutil.copy2(sidecar, backup_path.with_name(backup_path.name + sidecar.name.removeprefix(path.name)))
    return backup_path


def restore_sqlite_bytes(body: bytes) -> Path | None:
    if not body.startswith(b"SQLite format 3"):
        raise ValueError("File non valido: non è un database SQLite")

    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".restore", delete=False) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)

    try:
        _validate_sqlite_file(tmp_path)
        backup_path = _backup_current_database(path)
        engine.dispose()

        for sidecar in _sidecar_paths(path):
            sidecar.unlink(missing_ok=True)

        tmp_path.replace(path)
        init_db()
        return backup_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
