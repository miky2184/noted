from datetime import date, datetime
from pathlib import Path
import shutil
import sqlite3
import tempfile

from sqlalchemy.engine import make_url
from sqlmodel import delete as sql_delete, select

from db import crud
from db.engine import DATABASE_URL, engine, get_session, init_db
from db.models import Context, GanttProject, Milestone, Note, Recap


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
        milestones = session.exec(select(Milestone)).all()

    return {
        "exported_at": date.today().isoformat(),
        "version": 1,
        "contexts": [{"id": c.id, "name": c.name} for c in contexts],
        "notes": [
            {"id": n.id, "content": n.content, "tags": n.tags,
             "project": n.project, "priority": n.priority,
             "due_date": str(n.due_date) if n.due_date else None,
             "status": n.status, "assignee": n.assignee,
             "context": n.context, "created_at": n.created_at.isoformat(),
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
             "context": p.context, "created_at": p.created_at.isoformat()}
            for p in projects
        ],
        "milestones": [
            {"id": m.id, "project_id": m.project_id, "name": m.name,
             "start_date": str(m.start_date), "end_date": str(m.end_date)}
            for m in milestones
        ],
    }


def restore_json_data(body: dict) -> None:
    if "notes" not in body:
        raise ValueError("JSON non valido")

    with get_session() as session:
        session.exec(sql_delete(Milestone))
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
                context=p.get("context", "default"),
                created_at=datetime.fromisoformat(p["created_at"]),
            ))

        for m in body.get("milestones", []):
            session.add(Milestone(
                id=m["id"], project_id=m["project_id"], name=m["name"],
                start_date=date.fromisoformat(m["start_date"]),
                end_date=date.fromisoformat(m["end_date"]),
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
