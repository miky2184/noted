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
        f"/api/notes/{note['id']}?ctx=work",
        json={"status": "done", "due_date": "2026-05-20"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"
    assert patched.json()["due_date"] == "2026-05-20"

    notes = client.get("/api/notes?ctx=work")
    assert notes.status_code == 200
    assert notes.json()[0]["status"] == "done"


def test_note_update_and_delete_are_scoped_to_context(client):
    """PATCH/DELETE /api/notes/{id} must not leak across contexts just
    because the caller omits ?ctx= (it defaults to "default")."""
    work_note = client.post("/api/notes?ctx=work", json={"content": "work task"}).json()

    # no ?ctx= → resolves to the "default" context, which doesn't own this note
    wrong_ctx_patch = client.patch(f"/api/notes/{work_note['id']}", json={"status": "done"})
    assert wrong_ctx_patch.status_code == 404

    wrong_ctx_delete = client.delete(f"/api/notes/{work_note['id']}")
    assert wrong_ctx_delete.status_code == 404

    still_there = client.get("/api/notes?ctx=work").json()
    assert any(n["id"] == work_note["id"] for n in still_there)

    ok_patch = client.patch(f"/api/notes/{work_note['id']}?ctx=work", json={"status": "done"})
    assert ok_patch.status_code == 200

    ok_delete = client.delete(f"/api/notes/{work_note['id']}?ctx=work")
    assert ok_delete.status_code == 204


def test_delete_note_cascades_dependencies(client):
    """Deleting a note must not leave orphaned NoteDependency rows behind —
    neither where it was the blocked note nor where it was the blocker."""
    a = client.post("/api/notes?ctx=work", json={"content": "A"}).json()
    b = client.post("/api/notes?ctx=work", json={"content": "B"}).json()
    c = client.post("/api/notes?ctx=work", json={"content": "C"}).json()

    # B blocks A, and B is blocked by C
    client.post(f"/api/notes/{a['id']}/deps?ctx=work", json={"blocker_id": b["id"]})
    client.post(f"/api/notes/{b['id']}/deps?ctx=work", json={"blocker_id": c["id"]})

    assert client.delete(f"/api/notes/{b['id']}?ctx=work").status_code == 204

    deps_a = client.get(f"/api/notes/{a['id']}/deps?ctx=work").json()
    assert deps_a["blockers"] == []

    deps_c = client.get(f"/api/notes/{c['id']}/deps?ctx=work").json()
    assert deps_c["blocking"] == []


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


def test_today_activity_buckets_and_priority(client):
    from datetime import date, timedelta
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    far_future = (today + timedelta(days=5)).isoformat()
    today_iso = today.isoformat()

    overdue = client.post("/api/notes?ctx=work", json={
        "content": "scaduta ieri", "due_date": yesterday,
    }).json()
    due_today = client.post("/api/notes?ctx=work", json={
        "content": "scade oggi", "due_date": today_iso,
    }).json()
    # entra in "due_soon" pur non scadendo esattamente oggi (finestra di 2 giorni)
    due_tomorrow = client.post("/api/notes?ctx=work", json={
        "content": "scade domani", "due_date": tomorrow,
    }).json()
    # senza due_date, così non collide con "due_soon" e finisce in "starting_today"
    starting_today = client.post("/api/notes?ctx=work", json={
        "content": "inizia oggi", "start_date": today_iso,
    }).json()
    no_date = client.post("/api/notes?ctx=work", json={
        "content": "senza nessuna data",
    }).json()
    # non deve comparire in nessun bucket: troppo lontana per la finestra "due_soon"
    future = client.post("/api/notes?ctx=work", json={
        "content": "tutta futura", "due_date": far_future,
    }).json()
    # nota completata: esclusa di default, visibile solo con include_done=true
    done = client.post("/api/notes?ctx=work", json={
        "content": "scaduta ieri ma fatta", "due_date": yesterday, "status": "done",
    }).json()

    res = client.get("/api/notes/today-activity?ctx=work")
    assert res.status_code == 200
    data = res.json()
    assert [n["id"] for n in data["overdue"]] == [overdue["id"]]
    assert [n["id"] for n in data["due_soon"]] == [due_today["id"], due_tomorrow["id"]]
    assert [n["id"] for n in data["starting_today"]] == [starting_today["id"]]
    assert [n["id"] for n in data["no_date"]] == [no_date["id"]]
    all_ids = {n["id"] for bucket in data.values() for n in bucket}
    assert future["id"] not in all_ids
    assert done["id"] not in all_ids

    with_done = client.get("/api/notes/today-activity?ctx=work&include_done=true").json()
    assert done["id"] in [n["id"] for n in with_done["overdue"]]

    # scoping per contesto
    assert client.get("/api/notes/today-activity?ctx=home").json() == {
        "overdue": [], "due_soon": [], "starting_today": [], "no_date": []
    }


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

    stream = client.post(
        "/api/gantt/streams?ctx=work",
        json={"project_id": project.json()["id"], "name": "Release"},
    )
    assert stream.status_code == 201

    phase = client.post(
        "/api/gantt/phases?ctx=work",
        json={
            "stream_id": stream.json()["id"],
            "name": "Release",
            "start_date": "2026-05-16",
            "end_date": "2026-05-20",
        },
    )
    assert phase.status_code == 201

    gantt = client.get("/api/gantt?ctx=work")
    assert gantt.status_code == 200
    assert gantt.json()["projects"][0]["streams"][0]["name"] == "Release"
    assert gantt.json()["projects"][0]["streams"][0]["phases"][0]["progress_total"] == 1

    invalid_phase = client.post(
        "/api/gantt/phases?ctx=work",
        json={
            "stream_id": stream.json()["id"],
            "name": "Invalid",
            "start_date": "2026-05-21",
            "end_date": "2026-05-20",
        },
    )
    assert invalid_phase.status_code == 400

    hidden_project = client.post(
        "/api/gantt/projects?ctx=home",
        json={"name": "HOME", "color": "#60a5fa"},
    ).json()
    hidden_stream = client.post(
        "/api/gantt/streams?ctx=home",
        json={"project_id": hidden_project["id"], "name": "Cross"},
    ).json()
    cross_context = client.post(
        "/api/gantt/phases?ctx=work",
        json={
            "stream_id": hidden_stream["id"],
            "name": "Cross context",
            "start_date": "2026-05-16",
            "end_date": "2026-05-20",
        },
    )
    assert cross_context.status_code == 404

    edited = client.patch(
        f"/api/gantt/phases/{phase.json()['id']}?ctx=work",
        json={"name": "Release finale", "end_date": "2026-05-22"},
    )
    assert edited.status_code == 200
    due_after_edit = client.get("/api/notes/due?ctx=work")
    assert any(n["content"] == "Release finale" and n["due_date"] == "2026-05-22" for n in due_after_edit.json())

    linked_note = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "task collegato alla fase",
            "project": "ACME",
            "status": "todo",
            "due_date": "2026-05-21",
        },
    ).json()
    client.patch(
        f"/api/notes/{linked_note['id']}?ctx=work",
        json={"milestone_id": phase.json()["id"]},
    )
    gantt_after_link = client.get("/api/gantt?ctx=work").json()
    phase_data = gantt_after_link["projects"][0]["streams"][0]["phases"][0]
    assert any(n["id"] == linked_note["id"] for n in phase_data["linked_notes"])
    assert all(n["id"] != linked_note["id"] for n in gantt_after_link["projects"][0]["notes"])


def test_gantt_client_crud(client):
    created = client.post("/api/gantt/clients?ctx=work", json={"name": "ACME Corp"})
    assert created.status_code == 201
    cid = created.json()["id"]

    listed = client.get("/api/gantt/clients?ctx=work").json()
    assert any(c["id"] == cid and c["name"] == "ACME Corp" for c in listed)

    renamed = client.patch(f"/api/gantt/clients/{cid}?ctx=work", json={"name": "ACME S.p.A."})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "ACME S.p.A."

    # 404 su cliente di un altro contesto
    cross_ctx = client.patch(f"/api/gantt/clients/{cid}?ctx=home", json={"name": "x"})
    assert cross_ctx.status_code == 404

    deleted = client.delete(f"/api/gantt/clients/{cid}?ctx=work")
    assert deleted.status_code == 204
    assert not any(c["id"] == cid for c in client.get("/api/gantt/clients?ctx=work").json())


def test_note_cliente_field_auto_syncs_gantt_project_client(client):
    """La nota è la fonte di verità: scrivere una nota con project+cliente
    deve creare/collegare automaticamente il Client nel Gantt, senza
    passaggi manuali nella sidebar."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "FINOPS"}).json()
    assert project["client_id"] is None if "client_id" in project else True

    note = client.post("/api/notes?ctx=work", json={
        "content": "verificare campi tabella",
        "cliente": "CREDEM", "project": "FINOPS", "start_date": "2026-09-01",
    }).json()
    assert note["cliente"] == "CREDEM"
    assert note["start_date"] == "2026-09-01"

    clients = client.get("/api/gantt/clients?ctx=work").json()
    assert any(c["name"] == "CREDEM" for c in clients)
    credem_id = next(c["id"] for c in clients if c["name"] == "CREDEM")

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = next(p for p in gantt["projects"] if p["id"] == project["id"])
    assert proj["client_id"] == credem_id
    assert proj["client_name"] == "CREDEM"

    # una seconda nota con lo stesso cliente non crea un duplicato
    client.post("/api/notes?ctx=work", json={
        "content": "altra nota stesso cliente", "cliente": "credem", "project": "FINOPS",
    })
    clients_after = client.get("/api/gantt/clients?ctx=work").json()
    assert sum(1 for c in clients_after if c["name"].lower() == "credem") == 1


def test_note_cliente_and_project_auto_creates_gantt_project(client):
    """Se il progetto Gantt non esiste ancora, scrivere una nota con
    project+cliente deve crearlo — zero setup manuale nel Gantt."""
    assert client.get("/api/gantt?ctx=work").json()["projects"] == []

    client.post("/api/notes?ctx=work", json={
        "content": "call con il cliente", "cliente": "CREDEM", "project": "FINOPS",
    })

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = next((p for p in gantt["projects"] if p["name"] == "FINOPS"), None)
    assert proj is not None
    assert proj["client_name"] == "CREDEM"

    # una seconda nota sullo stesso progetto non crea un duplicato
    client.post("/api/notes?ctx=work", json={
        "content": "altra nota", "cliente": "CREDEM", "project": "finops",
    })
    gantt2 = client.get("/api/gantt?ctx=work").json()
    assert sum(1 for p in gantt2["projects"] if p["name"].lower() == "finops") == 1


def test_note_with_only_done_status_does_not_auto_create_project(client):
    """Una nota (storica) già "done" fin dall'inizio, con cliente+progetto mai
    visti prima, non deve generare un progetto Gantt "fantasma" — solo il
    lavoro ancora aperto merita un progetto visibile in automatico."""
    note = client.post("/api/notes?ctx=work", json={
        "content": "corso già fatto", "cliente": "AGBG", "project": "AGBG", "status": "done",
    }).json()
    gantt = client.get("/api/gantt?ctx=work").json()
    assert not any(p["name"] == "AGBG" for p in gantt["projects"])

    # riaprire la nota (status non più "done") deve far scattare la creazione,
    # come se fosse la prima nota "attiva" del gruppo
    client.patch(f"/api/notes/{note['id']}?ctx=work", json={"status": "todo"})
    gantt2 = client.get("/api/gantt?ctx=work").json()
    assert any(p["name"] == "AGBG" for p in gantt2["projects"])


def test_project_with_active_note_survives_when_note_marked_done(client):
    """Un progetto creato da una nota attiva non deve sparire se quella nota
    viene poi segnata "done" — restare visibile finché non viene archiviato
    a mano è il comportamento voluto (niente sparizioni automatiche)."""
    note = client.post("/api/notes?ctx=work", json={
        "content": "task attivo", "cliente": "DB", "project": "DB", "status": "todo",
    }).json()
    assert any(p["name"] == "DB" for p in client.get("/api/gantt?ctx=work").json()["projects"])

    client.patch(f"/api/notes/{note['id']}?ctx=work", json={"status": "done"})
    gantt = client.get("/api/gantt?ctx=work").json()
    assert any(p["name"] == "DB" for p in gantt["projects"])


def test_gantt_client_delete_unlinks_projects_not_cascade(client):
    cid = client.post("/api/gantt/clients?ctx=work", json={"name": "ACME"}).json()["id"]
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "SITO"}).json()

    assigned = client.patch(f"/api/gantt/projects/{project['id']}/client?ctx=work", json={"client_id": cid})
    assert assigned.status_code == 200
    assert assigned.json()["client_id"] == cid

    client.delete(f"/api/gantt/clients/{cid}?ctx=work")

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = next(p for p in gantt["projects"] if p["id"] == project["id"])
    assert proj["client_id"] is None
    assert proj["client_name"] is None


def test_gantt_stream_crud(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()

    created = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Collection"})
    assert created.status_code == 201
    stream_id = created.json()["id"]

    renamed = client.patch(f"/api/gantt/streams/{stream_id}?ctx=work", json={"name": "Collection v2"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Collection v2"

    # 404 su stream di un progetto in un altro contesto
    cross_ctx = client.patch(f"/api/gantt/streams/{stream_id}?ctx=home", json={"name": "x"})
    assert cross_ctx.status_code == 404

    deleted = client.delete(f"/api/gantt/streams/{stream_id}?ctx=work")
    assert deleted.status_code == 204
    assert client.delete(f"/api/gantt/streams/{stream_id}?ctx=work").status_code == 404


def test_stream_own_dates_used_only_without_phases(client):
    """Uno Stream senza Fasi può avere proprie start_date/end_date (usate per
    piazzarlo comunque sulla timeline); appena ha una Fase, nel Gantt vince
    l'aggregato min/max delle date delle sue Fasi, non più le date proprie."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()

    created = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Attività extra",
        "start_date": "2026-09-01", "end_date": "2026-09-10",
    })
    assert created.status_code == 201
    stream_id = created.json()["id"]
    assert created.json()["start_date"] == "2026-09-01"

    gantt = client.get("/api/gantt?ctx=work").json()
    stream_data = gantt["projects"][0]["streams"][0]
    assert stream_data["start_date"] == "2026-09-01"
    assert stream_data["end_date"] == "2026-09-10"

    # date invertite rifiutate anche in creazione
    invalid = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Invalid",
        "start_date": "2026-09-20", "end_date": "2026-09-10",
    })
    assert invalid.status_code == 400

    # aggiungere una fase con date diverse fa vincere l'aggregato, non più le date proprie
    client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream_id, "name": "Analisi",
        "start_date": "2026-10-01", "end_date": "2026-10-15",
    })
    client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream_id, "name": "Implementazione",
        "start_date": "2026-10-20", "end_date": "2026-11-30",
    })
    gantt2 = client.get("/api/gantt?ctx=work").json()
    stream_data2 = gantt2["projects"][0]["streams"][0]
    assert stream_data2["start_date"] == "2026-10-01"  # min tra le fasi
    assert stream_data2["end_date"] == "2026-11-30"     # max tra le fasi

    # modificare le date "proprie" dello stream a questo punto non ha effetto
    # visibile nel Gantt (restano superate dall'aggregato delle fasi)
    client.patch(f"/api/gantt/streams/{stream_id}?ctx=work",
                 json={"start_date": "2020-01-01", "end_date": "2020-01-02"})
    gantt3 = client.get("/api/gantt?ctx=work").json()
    stream_data3 = gantt3["projects"][0]["streams"][0]
    assert stream_data3["start_date"] == "2026-10-01"
    assert stream_data3["end_date"] == "2026-11-30"


def test_phase_crud_and_cross_context_404(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Analisi"}).json()

    created = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Raccolta requisiti",
        "start_date": "2026-09-15", "end_date": "2026-09-30",
    })
    assert created.status_code == 201
    phase_id = created.json()["id"]
    assert created.json()["start_date"] == "2026-09-15"

    # date invertite rifiutate
    invalid = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Invalid",
        "start_date": "2026-10-01", "end_date": "2026-09-01",
    })
    assert invalid.status_code == 400

    renamed = client.patch(f"/api/gantt/phases/{phase_id}?ctx=work", json={"name": "Raccolta v2"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Raccolta v2"

    # 404 su fase di uno stream in un altro contesto
    cross_ctx = client.patch(f"/api/gantt/phases/{phase_id}?ctx=home", json={"name": "x"})
    assert cross_ctx.status_code == 404

    deleted = client.delete(f"/api/gantt/phases/{phase_id}?ctx=work")
    assert deleted.status_code == 204
    assert client.delete(f"/api/gantt/phases/{phase_id}?ctx=work").status_code == 404


def test_phase_delete_unlinks_note_not_delete(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Analisi"}).json()
    phase = client.post("/api/gantt/phases?ctx=work", json={"stream_id": stream["id"], "name": "Raccolta"}).json()
    note = client.post("/api/notes?ctx=work", json={"content": "step 1", "milestone_id": phase["id"]}).json()

    assert client.delete(f"/api/gantt/phases/{phase['id']}?ctx=work").status_code == 204

    gantt = client.get("/api/gantt?ctx=work").json()
    # lo Stream sopravvive (contenitore), semplicemente senza più fasi
    assert gantt["projects"][0]["streams"][0]["phases"] == []

    updated_note = next(n for n in client.get("/api/notes?ctx=work").json() if n["id"] == note["id"])
    assert updated_note["milestone_id"] is None


def test_standard_phases_creates_three_templates(client):
    """Il bottone "+ fasi standard" crea in un colpo solo le 4 fasi tipiche
    (Analisi e Requisiti / Implementazione / UAT / Rilascio in PROD), senza date."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Filtro consumi"}).json()

    res = client.post("/api/gantt/phases/standard?ctx=work", json={"stream_id": stream["id"]})
    assert res.status_code == 201
    names = [ph["name"] for ph in res.json()["phases"]]
    assert names == ["Analisi e Requisiti", "Implementazione", "UAT", "Rilascio in PROD"]
    assert all(ph["start_date"] is None for ph in res.json()["phases"])

    gantt = client.get("/api/gantt?ctx=work").json()
    phases = gantt["projects"][0]["streams"][0]["phases"]
    assert [ph["name"] for ph in phases] == ["Analisi e Requisiti", "Implementazione", "UAT", "Rilascio in PROD"]

    # chiamarlo una seconda volta aggiunge altre 4 fasi, non sostituisce le esistenti
    client.post("/api/gantt/phases/standard?ctx=work", json={"stream_id": stream["id"]})
    gantt2 = client.get("/api/gantt?ctx=work").json()
    assert len(gantt2["projects"][0]["streams"][0]["phases"]) == 8

    # 404 su stream di un altro contesto
    assert client.post("/api/gantt/phases/standard?ctx=home", json={"stream_id": stream["id"]}).status_code == 404


def test_phases_ordered_by_start_date_not_creation(client):
    """Le fasi vanno mostrate in ordine cronologico di inizio, non nell'ordine
    in cui sono state create — qui creo apposta "Rilascio in PROD" (a fine
    lavoro) prima di "Implementazione" (che inizia prima)."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "CREDEM"}).json()
    stream = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "FINOPS"}).json()

    analisi = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Analisi e Requisiti",
        "start_date": "2026-09-15", "end_date": "2026-09-30",
    }).json()
    rilascio = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Rilascio in PROD",
        "start_date": "2026-11-02", "end_date": "2026-11-03",
    }).json()
    implementazione = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Implementazione",
        "start_date": "2026-10-03", "end_date": "2026-10-23",
    }).json()
    uat = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "UAT",
        "start_date": "2026-10-26", "end_date": "2026-10-30",
    }).json()
    # fase senza data: deve finire in coda, non rompere l'ordinamento
    senza_data = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Idea futura",
    }).json()

    gantt = client.get("/api/gantt?ctx=work").json()
    ids_in_order = [ph["id"] for ph in gantt["projects"][0]["streams"][0]["phases"]]
    assert ids_in_order == [analisi["id"], implementazione["id"], uat["id"], rilascio["id"], senza_data["id"]]


def test_gantt_streams_all_endpoint_includes_breadcrumb(client):
    """Usato dal campo di ricerca "stream" nel form nota — deve includere ogni
    Fase (non lo Stream, che è un puro contenitore) con etichetta completa
    "Progetto > Stream > Fase", perché le note si agganciano alla Fase."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    analisi = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Analisi"}).json()
    collection = client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Collection"}).json()
    client.post("/api/gantt/phases?ctx=work", json={"stream_id": analisi["id"], "name": "Raccolta requisiti"})
    client.post("/api/gantt/phases?ctx=work", json={"stream_id": collection["id"], "name": "Sviluppo"})

    res = client.get("/api/gantt/streams/all?ctx=work")
    assert res.status_code == 200
    labels = {s["label"] for s in res.json()["streams"]}
    assert "ACME > Analisi > Raccolta requisiti" in labels
    assert "ACME > Collection > Sviluppo" in labels

    # scoping per contesto: non deve comparire nell'altro contesto
    assert client.get("/api/gantt/streams/all?ctx=home").json()["streams"] == []


def test_client_projects_endpoint_for_note_form_autocomplete(client):
    """Usato dal campo "progetto" nel form nota per suggerire solo i progetti
    del cliente già inserito — leggero, niente fasi/progress."""
    client.post("/api/notes?ctx=work", json={
        "content": "nota 1", "cliente": "CREDEM", "project": "FINOPS DASHBOARD FATTURAZIONE",
    })
    client.post("/api/notes?ctx=work", json={
        "content": "nota 2", "cliente": "AGBG", "project": "ACADEMY",
    })
    # un progetto "sfondo" (es. Ferie) non è un progetto cliente reale
    client.post("/api/gantt/projects?ctx=work", json={"name": "Ferie", "is_background": True})

    res = client.get("/api/gantt/client-projects?ctx=work")
    assert res.status_code == 200
    data = res.json()
    by_name = {p["name"]: p["client_name"] for p in data}
    assert by_name["FINOPS DASHBOARD FATTURAZIONE"] == "CREDEM"
    assert by_name["ACADEMY"] == "AGBG"
    assert "Ferie" not in by_name

    # scoping per contesto
    assert client.get("/api/gantt/client-projects?ctx=home").json() == []


def test_gantt_absence_crud_and_context_scoping(client):
    created = client.post("/api/gantt/absences?ctx=work", json={
        "person": "Marco", "start_date": "2026-09-01", "end_date": "2026-09-14",
    })
    assert created.status_code == 201
    absence_id = created.json()["id"]
    assert created.json()["person"] == "Marco"

    listed = client.get("/api/gantt/absences?ctx=work").json()
    assert any(a["id"] == absence_id for a in listed)

    # non deve comparire in un altro contesto
    assert client.get("/api/gantt/absences?ctx=home").json() == []

    # compare anche nella risposta aggregata del Gantt
    gantt = client.get("/api/gantt?ctx=work").json()
    assert any(a["id"] == absence_id for a in gantt["absences"])

    # date invertite rifiutate
    invalid = client.post("/api/gantt/absences?ctx=work", json={
        "person": "Marco", "start_date": "2026-09-14", "end_date": "2026-09-01",
    })
    assert invalid.status_code == 400

    # elimina, non cancellabile due volte, non cancellabile da un altro contesto
    assert client.delete(f"/api/gantt/absences/{absence_id}?ctx=home").status_code == 404
    assert client.delete(f"/api/gantt/absences/{absence_id}?ctx=work").status_code == 204
    assert client.delete(f"/api/gantt/absences/{absence_id}?ctx=work").status_code == 404


def test_gantt_absence_color_override(client):
    created = client.post("/api/gantt/absences?ctx=work", json={
        "person": "Giulia", "start_date": "2026-09-01", "end_date": "2026-09-05", "color": "#34d399",
    })
    assert created.status_code == 201
    assert created.json()["color"] == "#34d399"
    absence_id = created.json()["id"]

    # colore non valido rifiutato in creazione
    rejected = client.post("/api/gantt/absences?ctx=work", json={
        "person": "Giulia", "start_date": "2026-09-01", "end_date": "2026-09-05", "color": "not-a-color",
    })
    assert rejected.status_code == 400

    # PATCH aggiorna il colore
    patched = client.patch(f"/api/gantt/absences/{absence_id}?ctx=work", json={"color": "#f472b6"})
    assert patched.status_code == 200
    assert patched.json()["color"] == "#f472b6"

    # PATCH con colore non valido rifiutato
    assert client.patch(f"/api/gantt/absences/{absence_id}?ctx=work", json={"color": "red"}).status_code == 400

    # PATCH con null torna al colore automatico
    reset = client.patch(f"/api/gantt/absences/{absence_id}?ctx=work", json={"color": None})
    assert reset.status_code == 200
    assert reset.json()["color"] is None

    # non modificabile da un altro contesto
    assert client.patch(f"/api/gantt/absences/{absence_id}?ctx=home", json={"color": "#fbbf24"}).status_code == 404


def test_stream_linked_notes_ordered_by_period_not_creation(client):
    """Le note collegate a una fase vanno mostrate in ordine cronologico
    (start_date, poi due_date), non nell'ordine in cui sono state create/il
    loro id — qui creo apposta la nota "più tardi" per prima."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()
    phase = client.post("/api/gantt/phases?ctx=work",
                         json={"stream_id": stream["id"], "name": "Raccolta"}).json()

    # entrambe le date sono nel passato rispetto a "oggi": la nota senza data
    # (il cui sort key ricade sulla data di creazione, cioè oggi) deve finire
    # dopo entrambe, in coda.
    later = client.post("/api/notes?ctx=work", json={
        "content": "step del 15 agosto", "milestone_id": phase["id"], "start_date": "2026-08-15",
    }).json()
    earlier = client.post("/api/notes?ctx=work", json={
        "content": "step del 1 agosto", "milestone_id": phase["id"], "start_date": "2026-08-01",
    }).json()
    no_date = client.post("/api/notes?ctx=work", json={
        "content": "step senza data", "milestone_id": phase["id"],
    }).json()

    gantt = client.get("/api/gantt?ctx=work").json()
    linked = gantt["projects"][0]["streams"][0]["phases"][0]["linked_notes"]
    ids_in_order = [n["id"] for n in linked]
    # earlier (1 agosto) prima di later (15 agosto), nonostante creata dopo;
    # la nota senza data va in coda (fallback sulla data di creazione = oggi)
    assert ids_in_order.index(earlier["id"]) < ids_in_order.index(later["id"])
    assert ids_in_order[-1] == no_date["id"]


def test_note_linked_directly_to_stream_acts_as_phase(client):
    """Una nota può agganciarsi direttamente a uno Stream (senza passare da una
    Fase) per lavoro semplice che non merita una scomposizione in fasi — la
    nota stessa compare come "fase" nel Gantt, con le sue date e il suo status."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "DB"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Attività extra"}).json()

    note = client.post("/api/notes?ctx=work", json={
        "content": "copertura a supporto FASE2", "stream_id": stream["id"],
        "start_date": "2026-09-01", "due_date": "2026-12-31",
    }).json()
    assert note["stream_id"] == stream["id"]
    assert note["milestone_id"] is None

    gantt = client.get("/api/gantt?ctx=work").json()
    stream_data = gantt["projects"][0]["streams"][0]
    assert stream_data["progress_total"] == 1
    phase_like = stream_data["phases"][0]
    assert phase_like["name"] == "copertura a supporto FASE2"
    assert phase_like["start_date"] == "2026-09-01"
    assert phase_like["end_date"] == "2026-12-31"
    assert phase_like["is_note"] is True
    assert phase_like["note_id"] == note["id"]

    # non deve comparire ANCHE come nota-con-scadenza "libera" del progetto
    # (sarebbe una duplicazione: è già rappresentata come fase dello stream)
    assert gantt["projects"][0]["notes"] == []

    # segnarla "done" alza il progress dello stream
    client.patch(f"/api/notes/{note['id']}?ctx=work", json={"status": "done"})
    gantt2 = client.get("/api/gantt?ctx=work").json()
    assert gantt2["projects"][0]["streams"][0]["progress"] == 100

    # milestone_id e stream_id sono mutuamente esclusivi
    phase = client.post("/api/gantt/phases?ctx=work",
                         json={"stream_id": stream["id"], "name": "Fase vera"}).json()
    client.patch(f"/api/notes/{note['id']}?ctx=work", json={"milestone_id": phase["id"]})
    note_after = next(n for n in client.get("/api/notes?ctx=work").json() if n["id"] == note["id"])
    assert note_after["milestone_id"] == phase["id"]
    assert note_after["stream_id"] is None


def test_stream_delete_unlinks_directly_attached_note(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "DB"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Attività extra"}).json()
    note = client.post("/api/notes?ctx=work", json={
        "content": "copertura extra", "stream_id": stream["id"],
    }).json()

    assert client.delete(f"/api/gantt/streams/{stream['id']}?ctx=work").status_code == 204

    updated = next(n for n in client.get("/api/notes?ctx=work").json() if n["id"] == note["id"])
    assert updated["stream_id"] is None


def test_stream_dateless_and_note_link_progress(client):
    """Una Fase è creabile senza date (esiste come contenitore di note) e la
    sua % — aggregata anche a livello di Stream — si calcola sulle note
    collegate via milestone_id."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Analisi",
    }).json()

    phase = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Raccolta",
    })
    assert phase.status_code == 201
    assert phase.json()["start_date"] is None
    phase_id = phase.json()["id"]

    n1 = client.post("/api/notes?ctx=work", json={"content": "step 1", "status": "done", "milestone_id": phase_id}).json()
    n2 = client.post("/api/notes?ctx=work", json={"content": "step 2", "status": "todo"}).json()
    client.patch(f"/api/notes/{n2['id']}?ctx=work", json={"milestone_id": phase_id})

    gantt = client.get("/api/gantt?ctx=work").json()
    stream_data = gantt["projects"][0]["streams"][0]
    phase_data = stream_data["phases"][0]
    assert stream_data["progress_total"] == 2
    assert stream_data["progress_done"] == 1
    assert stream_data["progress"] == 50
    assert phase_data["progress_total"] == 2
    assert phase_data["progress"] == 50
    assert {n["id"] for n in phase_data["linked_notes"]} == {n1["id"], n2["id"]}

    # aggiungere le date dopo deve funzionare (fase creata senza, valorizzata in seguito)
    dated = client.patch(f"/api/gantt/phases/{phase_id}?ctx=work",
                          json={"start_date": "2026-06-01", "end_date": "2026-06-10"})
    assert dated.status_code == 200
    assert dated.json()["start_date"] == "2026-06-01"

    # clear_milestone rimuove la nota dalla fase
    client.patch(f"/api/notes/{n2['id']}?ctx=work", json={"clear_milestone": True})
    gantt2 = client.get("/api/gantt?ctx=work").json()
    phase_data2 = gantt2["projects"][0]["streams"][0]["phases"][0]
    assert phase_data2["progress_total"] == 1
    assert phase_data2["progress"] == 100


def test_project_progress_aggregates_all_streams(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()

    stream_a = client.post("/api/gantt/streams?ctx=work",
                            json={"project_id": project["id"], "name": "A"}).json()
    stream_b = client.post("/api/gantt/streams?ctx=work",
                            json={"project_id": project["id"], "name": "B"}).json()
    phase_a = client.post("/api/gantt/phases?ctx=work", json={"stream_id": stream_a["id"], "name": "Fase A"}).json()
    phase_b = client.post("/api/gantt/phases?ctx=work", json={"stream_id": stream_b["id"], "name": "Fase B"}).json()

    n1 = client.post("/api/notes?ctx=work", json={"content": "a1", "status": "done", "milestone_id": phase_a["id"]}).json()
    n2 = client.post("/api/notes?ctx=work", json={"content": "b1", "status": "todo", "milestone_id": phase_b["id"]}).json()
    n3 = client.post("/api/notes?ctx=work", json={"content": "b2", "status": "todo", "milestone_id": phase_b["id"]}).json()

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = gantt["projects"][0]
    # 1 done su 3 totali, sommando entrambi gli stream/fasi del progetto
    assert proj["progress"] == 33


def test_gantt_stream_delete_unlinks_note_not_delete(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()
    phase = client.post("/api/gantt/phases?ctx=work",
                         json={"stream_id": stream["id"], "name": "Raccolta"}).json()
    note = client.post("/api/notes?ctx=work", json={"content": "step 1", "milestone_id": phase["id"]}).json()

    assert client.delete(f"/api/gantt/streams/{stream['id']}?ctx=work").status_code == 204

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = gantt["projects"][0]
    assert proj["streams"] == []

    # la nota resta, solo scollegata (lo stream — e con esso la sua fase — è
    # stato cancellato per davvero, non "svuotato")
    updated_note = next(n for n in client.get("/api/notes?ctx=work").json() if n["id"] == note["id"])
    assert updated_note["milestone_id"] is None


def test_gantt_project_delete_unlinks_streams(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()
    phase = client.post("/api/gantt/phases?ctx=work",
                         json={"stream_id": stream["id"], "name": "Raccolta"}).json()
    note = client.post("/api/notes?ctx=work", json={"content": "step 1", "milestone_id": phase["id"]}).json()

    release_stream = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Release",
    }).json()
    release_phase = client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": release_stream["id"], "name": "Release",
        "start_date": "2026-05-16", "end_date": "2026-05-20",
    }).json()
    release_note = client.post("/api/notes?ctx=work", json={"content": "release note"}).json()
    client.patch(f"/api/notes/{release_note['id']}?ctx=work", json={"milestone_id": release_phase["id"]})

    assert client.delete(f"/api/gantt/projects/{project['id']}?ctx=work").status_code == 204

    notes = client.get("/api/notes?ctx=work").json()
    assert next(n for n in notes if n["id"] == note["id"])["milestone_id"] is None
    assert next(n for n in notes if n["id"] == release_note["id"])["milestone_id"] is None
    # anche la nota auto-creata dalla fase deve restare (non cancellata) — non
    # compare nel tab Note di default (v. test_milestone_tracking_note_hidden_*),
    # ma resta recuperabile cercandola esplicitamente per tag
    tagged_notes = client.get("/api/notes?ctx=work&tag=milestone").json()
    assert any(n["content"] == "Release" for n in tagged_notes)


def test_fiscal_year_setting_and_board_filter(client):
    """L'anno fiscale è configurabile (default settembre, come Accenture) e usato
    dal filtro "scadenze" della board — con mese di inizio 1 (gennaio) coincide
    con l'anno solare."""
    from datetime import date, timedelta
    from db.config import fiscal_year_bounds

    settings = client.get("/api/settings").json()
    assert settings["fiscal_year_start_month"] == 9

    invalid = client.patch("/api/settings", json={"fiscal_year_start_month": 13})
    assert invalid.status_code == 400

    ok = client.patch("/api/settings", json={"fiscal_year_start_month": 1})
    assert ok.status_code == 200
    assert client.get("/api/settings").json()["fiscal_year_start_month"] == 1

    today = date.today()
    fy_start, fy_end = fiscal_year_bounds(today, 1)
    assert fy_start == date(today.year, 1, 1) and fy_end == date(today.year, 12, 31)

    inside = client.post("/api/notes?ctx=work", json={
        "content": "dentro l'anno fiscale", "status": "todo", "due_date": today.isoformat(),
    }).json()
    outside = client.post("/api/notes?ctx=work", json={
        "content": "fuori dall'anno fiscale", "status": "todo",
        "due_date": (fy_end + timedelta(days=5)).isoformat(),
    }).json()

    res = client.get("/api/board?ctx=work&due=fiscal_year")
    ids = [n["id"] for n in res.json()["todo"]]
    assert inside["id"] in ids
    assert outside["id"] not in ids


def test_board_filters(client):
    alpha = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "preparare piano operativo ACME",
            "project": "ACME",
            "cliente": "CREDEM",
            "tags": "ops,cliente",
            "priority": "high",
            "status": "todo",
            "due_date": "2026-06-01",
            "assignee": "mario",
        },
    ).json()
    beta = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "bozza interna",
            "project": "BETA",
            "tags": "draft",
            "priority": "low",
            "status": "todo",
        },
    ).json()
    loose = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "nota da classificare",
            "priority": "medium",
            "status": "todo",
        },
    ).json()

    by_tag = client.get("/api/board?ctx=work&tag=ops")
    assert [n["id"] for n in by_tag.json()["todo"]] == [alpha["id"]]

    by_priority = client.get("/api/board?ctx=work&priority=low")
    assert [n["id"] for n in by_priority.json()["todo"]] == [beta["id"]]

    by_query = client.get("/api/board?ctx=work&q=operativo")
    assert [n["id"] for n in by_query.json()["todo"]] == [alpha["id"]]

    by_due = client.get("/api/board?ctx=work&due=has")
    assert [n["id"] for n in by_due.json()["todo"]] == [alpha["id"]]

    created_today = client.get("/api/board?ctx=work&created=today")
    ids = [n["id"] for n in created_today.json()["todo"]]
    assert alpha["id"] in ids and beta["id"] in ids and loose["id"] in ids

    no_project = client.get("/api/board?ctx=work&no_project=true")
    assert [n["id"] for n in no_project.json()["todo"]] == [loose["id"]]

    no_tag = client.get("/api/board?ctx=work&no_tag=true")
    assert [n["id"] for n in no_tag.json()["todo"]] == [loose["id"]]

    by_cliente = client.get("/api/board?ctx=work&cliente=CREDEM")
    assert [n["id"] for n in by_cliente.json()["todo"]] == [alpha["id"]]

    no_cliente = client.get("/api/board?ctx=work&no_cliente=true")
    ids = [n["id"] for n in no_cliente.json()["todo"]]
    assert beta["id"] in ids and loose["id"] in ids and alpha["id"] not in ids


def test_board_filters_by_phase_and_stream(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()
    phase = client.post("/api/gantt/phases?ctx=work",
                         json={"stream_id": stream["id"], "name": "Raccolta"}).json()
    other_stream = client.post("/api/gantt/streams?ctx=work",
                                json={"project_id": project["id"], "name": "Attività extra"}).json()

    on_phase = client.post("/api/notes?ctx=work", json={
        "content": "task sulla fase", "milestone_id": phase["id"], "status": "todo",
    }).json()
    on_stream = client.post("/api/notes?ctx=work", json={
        "content": "task sullo stream diretto", "stream_id": other_stream["id"], "status": "todo",
    }).json()
    unrelated = client.post("/api/notes?ctx=work", json={
        "content": "nota non collegata", "status": "todo",
    }).json()

    by_phase = client.get(f"/api/board?ctx=work&milestone_id={phase['id']}")
    assert [n["id"] for n in by_phase.json()["todo"]] == [on_phase["id"]]

    by_stream = client.get(f"/api/board?ctx=work&stream_id={other_stream['id']}")
    assert [n["id"] for n in by_stream.json()["todo"]] == [on_stream["id"]]

    # senza filtro compaiono entrambe (più quella non collegata)
    all_todo = client.get("/api/board?ctx=work").json()["todo"]
    assert {n["id"] for n in all_todo} == {on_phase["id"], on_stream["id"], unrelated["id"]}


def test_milestone_tracking_note_hidden_from_board_and_activity(client):
    """La nota di tracking auto-creata per uno Stream (tag "milestone") è già
    rappresentata dalla barra dello Stream nel Gantt — non deve comparire né
    in Board, né in Attività, né nel tab Note, altrimenti sembra una vera
    task da fare."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Release",
    }).json()
    client.post("/api/gantt/phases?ctx=work", json={
        "stream_id": stream["id"], "name": "Release",
        "start_date": "2026-06-01", "end_date": "2026-06-10",
    })
    # la nota di tracking è quella creata automaticamente da add_phase,
    # riconoscibile dal tag "milestone" e dal contenuto = nome della fase
    real_note = client.post("/api/notes?ctx=work", json={
        "content": "task vera collegata allo stream", "project": "ACME",
        "due_date": "2026-06-05", "status": "todo",
    }).json()

    board = client.get("/api/board?ctx=work").json()
    board_ids = {n["id"] for col in board.values() for n in col}
    assert real_note["id"] in board_ids
    assert all(n["content"] != "Release" for col in board.values() for n in col)

    activity = client.get("/api/notes/today-activity?ctx=work").json()
    activity_ids = {n["id"] for bucket in activity.values() for n in bucket}
    assert all(n["content"] != "Release" for bucket in activity.values() for n in bucket)

    notes = client.get("/api/notes?ctx=work").json()
    notes_ids = {n["id"] for n in notes}
    assert real_note["id"] in notes_ids
    assert all(n["content"] != "Release" for n in notes)

    gantt = client.get("/api/gantt?ctx=work").json()
    assert gantt["projects"][0]["streams"][0]["name"] == "Release"


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


def test_document_path_traversal_is_rejected(client, tmp_path):
    """A Document row with a malicious rel_path (e.g. from a tampered/legacy
    DB) must never let file/open/open-folder/delete escape doc_root."""
    from db import crud
    from db.engine import get_session

    note = client.post("/api/notes?ctx=work", json={"content": "doc note"}).json()

    canary = tmp_path / "canary.txt"
    canary.write_text("outside doc_root")

    with get_session() as session:
        doc = crud.add_document(
            session, note_id=note["id"], rel_path="../canary.txt",
            orig_name="canary.txt", mime_type="text/plain", size_bytes=len(b"outside doc_root"),
            sha256="deadbeef",
        )
        doc_id = doc.id

    assert client.get(f"/api/docs/{doc_id}/file").status_code == 403
    assert client.post(f"/api/docs/{doc_id}/open").status_code == 403
    assert client.post(f"/api/docs/{doc_id}/open-folder").status_code == 403
    assert client.delete(f"/api/docs/{doc_id}?remove_file=true").status_code == 403
    assert canary.read_text() == "outside doc_root"


def test_folder_scan_finds_untracked_files_ignoring_noise(client, tmp_path):
    """Un file già presente fisicamente in doc_root (mai allegato tramite
    noted) deve comparire nello scan; rumore (dotfile, cartelle nascoste/di
    sistema) e file già tracciati come Document no."""
    doc_root = tmp_path / "docs"
    doc_root.mkdir(exist_ok=True)
    (doc_root / "relazione.txt").write_text("contenuto")
    (doc_root / ".DS_Store").write_text("noise")
    hidden_dir = doc_root / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "config").write_text("noise")
    sub = doc_root / "progetto"
    sub.mkdir()
    (sub / "specifiche.pdf").write_text("contenuto pdf")

    # un file allegato tramite noted (tracciato in Document) non deve
    # ricomparire come "trovato" — sarebbe un duplicato nella lista
    note = client.post("/api/notes?ctx=work", json={"content": "doc note"}).json()
    uploaded = client.post(
        f"/api/notes/{note['id']}/docs",
        files={"file": ("allegata.txt", b"gia' nota", "text/plain")},
    ).json()

    res = client.get("/api/docs/folder-scan")
    assert res.status_code == 200
    found = {d["rel_path"]: d for d in res.json()}

    assert "relazione.txt" in found
    assert "progetto/specifiche.pdf" in found
    assert found["relazione.txt"]["orig_name"] == "relazione.txt"
    assert found["relazione.txt"]["size_bytes"] == len("contenuto")

    assert ".DS_Store" not in found
    assert not any(rel.startswith(".git") for rel in found)
    assert uploaded["rel_path"] not in found


def test_analyze_docs_accepts_folder_scanned_files(client, monkeypatch, tmp_path):
    """/api/analyze-docs deve accettare anche file trovati via folder-scan
    (folder_paths), non solo documenti già allegati (doc_ids)."""
    doc_root = tmp_path / "docs"
    doc_root.mkdir(exist_ok=True)
    (doc_root / "appunti.txt").write_text("testo di prova per l'analisi")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _FakeContent:
        text = '{"summary": "ok", "insights": [], "items": []}'
    class _FakeResponse:
        content = [_FakeContent()]
    class _FakeMessages:
        def create(self_inner, **kwargs):
            return _FakeResponse()
    class _FakeAnthropic:
        def __init__(self_inner, *a, **kw):
            self_inner.messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", _FakeAnthropic)

    res = client.post("/api/analyze-docs", json={
        "doc_ids": [], "folder_paths": ["appunti.txt"], "depth": "low",
    })
    assert res.status_code == 200
    assert res.json()["summary"] == "ok"
    # nessuna riga Document per un file solo-scansionato: niente da salvare
    assert "saved_to_doc" not in res.json()


def test_analyze_docs_rejects_when_nothing_selected(client):
    res = client.post("/api/analyze-docs", json={})
    assert res.status_code == 400


def test_backup_json_and_restore_json(client):
    note = client.post("/api/notes?ctx=work", json={"content": "backup me"}).json()

    backup = client.get("/api/backup/json")
    assert backup.status_code == 200
    payload = backup.json()
    assert any(n["id"] == note["id"] for n in payload["notes"])

    client.delete(f"/api/notes/{note['id']}?ctx=work")
    assert client.get("/api/notes?ctx=work").json() == []

    restored = client.post("/api/restore/json", json=payload)
    assert restored.status_code == 200

    notes = client.get("/api/notes?ctx=work")
    assert [n["content"] for n in notes.json()] == ["backup me"]


def test_backup_json_roundtrips_documents_and_dependencies(client):
    a = client.post("/api/notes?ctx=work", json={"content": "A"}).json()
    b = client.post("/api/notes?ctx=work", json={"content": "B"}).json()
    client.post(f"/api/notes/{a['id']}/deps?ctx=work", json={"blocker_id": b["id"]})
    client.post(
        f"/api/notes/{a['id']}/docs",
        files={"file": ("hello.txt", b"hello noted", "text/plain")},
    )

    payload = client.get("/api/backup/json").json()
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["orig_name"] == "hello.txt"
    assert len(payload["dependencies"]) == 1
    assert payload["dependencies"][0] == {
        "id": payload["dependencies"][0]["id"], "note_id": a["id"], "blocker_id": b["id"],
        "created_at": payload["dependencies"][0]["created_at"],
    }

    restored = client.post("/api/restore/json", json=payload)
    assert restored.status_code == 200

    docs = client.get(f"/api/notes/{a['id']}/docs").json()
    assert [d["orig_name"] for d in docs] == ["hello.txt"]

    deps = client.get(f"/api/notes/{a['id']}/deps?ctx=work").json()
    assert [d["id"] for d in deps["blockers"]] == [b["id"]]


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


def test_email_draft_requires_api_key(client, monkeypatch):
    note = client.post("/api/notes?ctx=work", json={"content": "chiedere aggiornamento a Marco"}).json()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post(f"/api/notes/{note['id']}/email-draft?ctx=work", json={})
    assert res.status_code == 400
    assert res.json()["detail"] == "ANTHROPIC_API_KEY non impostata"


def test_email_draft_404_on_missing_or_cross_context_note(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    note = client.post("/api/notes?ctx=work", json={"content": "nota"}).json()
    assert client.post("/api/notes/999999/email-draft?ctx=work", json={}).status_code == 404
    assert client.post(f"/api/notes/{note['id']}/email-draft?ctx=home", json={}).status_code == 404


def test_email_draft_rejects_empty_note_without_draft(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    note = client.post("/api/notes?ctx=work", json={"content": "   "}).json()
    res = client.post(f"/api/notes/{note['id']}/email-draft?ctx=work", json={})
    assert res.status_code == 400


def test_email_draft_generates_saves_and_reuses_without_calling_ai_again(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    email_module = importlib.import_module("ai.email_draft")
    calls = []
    monkeypatch.setattr(
        email_module, "generate_email_draft",
        lambda content: calls.append(("generate", content)) or {"subject": "Aggiornamento sprint", "body": "Ciao Marco,\n\ntesto."},
    )
    monkeypatch.setattr(
        email_module, "refine_email_draft",
        lambda content, subject, body, instruction: calls.append(("refine", instruction)) or {"subject": "Aggiornamento sprint (breve)", "body": "Corpo breve."},
    )

    note = client.post("/api/notes?ctx=work", json={"content": "chiedere aggiornamento a Marco"}).json()

    # prima generazione: chiama l'AI e salva sulla nota
    first = client.post(f"/api/notes/{note['id']}/email-draft?ctx=work", json={})
    assert first.status_code == 200
    assert first.json() == {"subject": "Aggiornamento sprint", "body": "Ciao Marco,\n\ntesto."}
    assert calls == [("generate", "chiedere aggiornamento a Marco")]

    saved_note = client.get("/api/notes?ctx=work&day=" + note["created_at"][:10]).json()[0]
    assert saved_note["email_subject"] == "Aggiornamento sprint"
    assert saved_note["email_body"] == "Ciao Marco,\n\ntesto."

    # secondo giro senza istruzioni: bozza già salvata, l'AI non viene richiamata
    second = client.post(f"/api/notes/{note['id']}/email-draft?ctx=work", json={})
    assert second.status_code == 200
    assert second.json() == {"subject": "Aggiornamento sprint", "body": "Ciao Marco,\n\ntesto."}
    assert calls == [("generate", "chiedere aggiornamento a Marco")]  # nessuna nuova chiamata

    # con un'istruzione: richiama l'AI in modalità "refine", non "generate"
    third = client.post(f"/api/notes/{note['id']}/email-draft?ctx=work", json={"instruction": "rendila più breve"})
    assert third.status_code == 200
    assert third.json() == {"subject": "Aggiornamento sprint (breve)", "body": "Corpo breve."}
    assert calls[-1] == ("refine", "rendila più breve")


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


def test_format_gantt_reads_streams_shape(client):
    """_format_gantt deve leggere project["streams"] (non più "milestones") e
    non esplodere su uno Stream senza date (end_date None)."""
    from datetime import date
    from ai.recap import _format_gantt

    gantt = {
        "projects": [{
            "name": "ACME",
            "streams": [
                {"name": "Stream A", "phases": [{"name": "Analisi", "start_date": None, "end_date": None}]},
                {"name": "Stream B", "phases": [{"name": "Release", "start_date": "2026-09-01", "end_date": "2026-09-10"}]},
            ],
        }]
    }
    text = _format_gantt(gantt, date(2026, 9, 5))
    assert "Release" in text
    assert "Analisi" not in text  # senza date, non è "attivo" per il recap
