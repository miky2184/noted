from pathlib import Path
import importlib
import sqlite3


def test_context_lifecycle(client):
    created = client.post("/api/contexts", json={"name": "Work"})
    assert created.status_code == 201
    ctx = created.json()
    assert ctx["name"] == "work"

    renamed = client.patch(f"/api/contexts/{ctx['id']}", json={"name": "Clients"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "clients"

    contexts = client.get("/api/contexts")
    assert contexts.status_code == 200
    assert any(c["name"] == "clients" for c in contexts.json())

    deleted = client.delete(f"/api/contexts/{ctx['id']}")
    assert deleted.status_code == 204


def test_notes_search_and_update(client):
    created = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "review contratto Acme per fatturazione finale",
            "project": "ACME",
            "tags": "contratti",
            "status": "todo",
        },
    )
    assert created.status_code == 201
    note = created.json()

    search = client.get("/api/search?ctx=work&q=fattura acme")
    assert search.status_code == 200
    assert [n["id"] for n in search.json()] == [note["id"]]

    patched = client.patch(
        f"/api/notes/{note['id']}",
        json={"status": "done", "due_date": "2026-05-20"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"
    assert patched.json()["due_date"] == "2026-05-20"

    notes = client.get("/api/notes?ctx=work")
    assert notes.status_code == 200
    assert notes.json()[0]["status"] == "done"


def test_dependencies_are_scoped_to_context(client):
    work_note = client.post("/api/notes?ctx=work", json={"content": "work task"}).json()
    work_blocker = client.post("/api/notes?ctx=work", json={"content": "work blocker"}).json()
    home_blocker = client.post("/api/notes?ctx=home", json={"content": "home blocker"}).json()

    same_context = client.post(
        f"/api/notes/{work_note['id']}/deps?ctx=work",
        json={"blocker_id": work_blocker["id"]},
    )
    assert same_context.status_code == 201

    cross_context = client.post(
        f"/api/notes/{work_note['id']}/deps?ctx=work",
        json={"blocker_id": home_blocker["id"]},
    )
    assert cross_context.status_code == 404

    deps = client.get(f"/api/notes/{work_note['id']}/deps?ctx=work")
    assert deps.status_code == 200
    assert deps.json()["blockers"] == [
        {"id": work_blocker["id"], "content": "work blocker", "status": None}
    ]


def test_board_due_and_gantt_smoke(client):
    note = client.post(
        "/api/notes?ctx=work",
        json={"content": "finish release", "status": "todo", "due_date": "2026-05-20"},
    ).json()

    board = client.get("/api/board?ctx=work")
    assert board.status_code == 200
    assert any(n["id"] == note["id"] for n in board.json()["todo"])

    discuss_note = client.post(
        "/api/notes?ctx=work",
        json={"content": "discutere scope", "status": "discuss"},
    ).json()
    board = client.get("/api/board?ctx=work")
    assert any(n["id"] == discuss_note["id"] for n in board.json()["discuss"])

    due = client.get("/api/notes/due?ctx=work")
    assert due.status_code == 200
    assert [n["id"] for n in due.json()] == [note["id"]]

    project = client.post(
        "/api/gantt/projects?ctx=work",
        json={"name": "ACME", "color": "#818cf8"},
    )
    assert project.status_code == 201

    milestone = client.post(
        "/api/gantt/milestones?ctx=work",
        json={
            "project_id": project.json()["id"],
            "name": "Release",
            "start_date": "2026-05-16",
            "end_date": "2026-05-20",
        },
    )
    assert milestone.status_code == 201

    gantt = client.get("/api/gantt?ctx=work")
    assert gantt.status_code == 200
    assert gantt.json()["projects"][0]["milestones"][0]["name"] == "Release"
    assert gantt.json()["projects"][0]["milestones"][0]["progress_total"] == 1

    invalid_milestone = client.post(
        "/api/gantt/milestones?ctx=work",
        json={
            "project_id": project.json()["id"],
            "name": "Invalid",
            "start_date": "2026-05-21",
            "end_date": "2026-05-20",
        },
    )
    assert invalid_milestone.status_code == 400

    hidden_project = client.post(
        "/api/gantt/projects?ctx=home",
        json={"name": "HOME", "color": "#60a5fa"},
    ).json()
    cross_context = client.post(
        "/api/gantt/milestones?ctx=work",
        json={
            "project_id": hidden_project["id"],
            "name": "Cross context",
            "start_date": "2026-05-16",
            "end_date": "2026-05-20",
        },
    )
    assert cross_context.status_code == 404

    edited = client.patch(
        f"/api/gantt/milestones/{milestone.json()['id']}?ctx=work",
        json={"name": "Release finale", "end_date": "2026-05-22"},
    )
    assert edited.status_code == 200
    due_after_edit = client.get("/api/notes/due?ctx=work")
    assert any(n["content"] == "Release finale" and n["due_date"] == "2026-05-22" for n in due_after_edit.json())

    linked_note = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "task collegato alla milestone",
            "project": "ACME",
            "status": "todo",
            "due_date": "2026-05-21",
        },
    ).json()
    client.patch(
        f"/api/notes/{linked_note['id']}?ctx=work",
        json={"milestone_id": milestone.json()["id"]},
    )
    gantt_after_link = client.get("/api/gantt?ctx=work").json()
    milestone_data = gantt_after_link["projects"][0]["milestones"][0]
    assert any(n["id"] == linked_note["id"] for n in milestone_data["linked_notes"])
    assert all(n["id"] != linked_note["id"] for n in gantt_after_link["projects"][0]["notes"])


def test_document_upload_list_download_and_delete(client, tmp_path):
    note = client.post("/api/notes?ctx=work", json={"content": "doc note", "project": "ACME"}).json()

    upload = client.post(
        f"/api/notes/{note['id']}/docs",
        files={"file": ("hello.txt", b"hello noted", "text/plain")},
    )
    assert upload.status_code == 201
    doc = upload.json()
    assert doc["rel_path"].startswith("work/acme/")
    assert doc["rel_path"].endswith("_hello.txt")

    docs = client.get("/api/docs?ctx=work")
    assert docs.status_code == 200
    assert docs.json()[0]["id"] == doc["id"]

    file_res = client.get(f"/api/docs/{doc['id']}/file")
    assert file_res.status_code == 200
    assert file_res.content == b"hello noted"

    deleted = client.delete(f"/api/docs/{doc['id']}?remove_file=true")
    assert deleted.status_code == 204
    assert not (tmp_path / "docs" / Path(doc["rel_path"])).exists()


def test_backup_json_and_restore_json(client):
    note = client.post("/api/notes?ctx=work", json={"content": "backup me"}).json()

    backup = client.get("/api/backup/json")
    assert backup.status_code == 200
    payload = backup.json()
    assert any(n["id"] == note["id"] for n in payload["notes"])

    client.delete(f"/api/notes/{note['id']}")
    assert client.get("/api/notes?ctx=work").json() == []

    restored = client.post("/api/restore/json", json=payload)
    assert restored.status_code == 200

    notes = client.get("/api/notes?ctx=work")
    assert [n["content"] for n in notes.json()] == ["backup me"]


def test_invalid_restore_json_is_rejected(client):
    res = client.post("/api/restore/json", json={"wrong": []})
    assert res.status_code == 400


def test_invalid_restore_db_is_rejected(client):
    res = client.post("/api/restore/db", content=b"not sqlite")
    assert res.status_code == 400
    assert "SQLite" in res.json()["detail"]


def test_restore_db_is_atomic_and_creates_pre_restore_backup(client, tmp_path):
    original = client.post("/api/notes?ctx=work", json={"content": "original"}).json()

    replacement = tmp_path / "replacement.db"
    with sqlite3.connect(replacement) as conn:
        conn.execute("""
            CREATE TABLE note (
                id INTEGER PRIMARY KEY,
                content VARCHAR NOT NULL,
                tags VARCHAR NOT NULL DEFAULT '',
                project VARCHAR,
                priority VARCHAR NOT NULL DEFAULT 'medium',
                due_date DATE,
                status VARCHAR,
                assignee VARCHAR,
                context VARCHAR NOT NULL DEFAULT 'default',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO note(content, tags, priority, context, sort_order, created_at, updated_at)
            VALUES ('restored from db', '', 'medium', 'work', 0, '2026-05-16 10:00:00', '2026-05-16 10:00:00')
        """)
        conn.commit()

    restore = client.post("/api/restore/db", content=replacement.read_bytes())
    assert restore.status_code == 200
    backup_path = Path(restore.json()["backup_path"])
    assert backup_path.exists()

    notes = client.get("/api/notes?ctx=work")
    assert notes.status_code == 200
    assert [n["content"] for n in notes.json()] == ["restored from db"]

    with sqlite3.connect(backup_path) as conn:
        original_rows = conn.execute("SELECT content FROM note WHERE id = ?", (original["id"],)).fetchall()
    assert original_rows == [("original",)]


def test_recap_requires_api_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post("/api/recap?ctx=work")
    assert res.status_code == 400
    assert res.json()["detail"] == "ANTHROPIC_API_KEY non impostata"


def test_daily_recap_streams_and_saves(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recap_module = importlib.import_module("ai.recap")
    monkeypatch.setattr(recap_module, "stream_recap", lambda notes, target_date, gantt=None: iter(["daily", " recap"]))

    client.post("/api/notes?ctx=work", json={"content": "done today"})
    res = client.post("/api/recap?ctx=work")
    assert res.status_code == 200
    assert res.text == "daily recap"

    recent = client.get("/api/recaps/recent?ctx=work&days=1")
    assert recent.status_code == 200
    assert recent.json()[0]["summary"] == "daily recap"
    assert recent.json()[0]["notes_count"] == 1


def test_weekly_recap_streams_and_saves(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recap_module = importlib.import_module("ai.recap")
    monkeypatch.setattr(recap_module, "stream_weekly_from_notes", lambda notes, gantt=None: iter(["weekly", " recap"]))

    client.post("/api/notes?ctx=work", json={"content": "weekly item"})
    res = client.post("/api/recap/weekly?ctx=work")
    assert res.status_code == 200
    assert res.text == "weekly recap"

    recent = client.get("/api/recaps/recent?ctx=work&days=1")
    assert recent.status_code == 200
    assert recent.json()[0]["summary"] == "weekly recap"
