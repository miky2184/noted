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
        json={
            "project_id": project.json()["id"],
            "name": "Release",
            "start_date": "2026-05-16",
            "end_date": "2026-05-20",
        },
    )
    assert stream.status_code == 201

    gantt = client.get("/api/gantt?ctx=work")
    assert gantt.status_code == 200
    assert gantt.json()["projects"][0]["streams"][0]["name"] == "Release"
    assert gantt.json()["projects"][0]["streams"][0]["progress_total"] == 1

    invalid_stream = client.post(
        "/api/gantt/streams?ctx=work",
        json={
            "project_id": project.json()["id"],
            "name": "Invalid",
            "start_date": "2026-05-21",
            "end_date": "2026-05-20",
        },
    )
    assert invalid_stream.status_code == 400

    hidden_project = client.post(
        "/api/gantt/projects?ctx=home",
        json={"name": "HOME", "color": "#60a5fa"},
    ).json()
    cross_context = client.post(
        "/api/gantt/streams?ctx=work",
        json={
            "project_id": hidden_project["id"],
            "name": "Cross context",
            "start_date": "2026-05-16",
            "end_date": "2026-05-20",
        },
    )
    assert cross_context.status_code == 404

    edited = client.patch(
        f"/api/gantt/streams/{stream.json()['id']}?ctx=work",
        json={"name": "Release finale", "end_date": "2026-05-22"},
    )
    assert edited.status_code == 200
    due_after_edit = client.get("/api/notes/due?ctx=work")
    assert any(n["content"] == "Release finale" and n["due_date"] == "2026-05-22" for n in due_after_edit.json())

    linked_note = client.post(
        "/api/notes?ctx=work",
        json={
            "content": "task collegato allo stream",
            "project": "ACME",
            "status": "todo",
            "due_date": "2026-05-21",
        },
    ).json()
    client.patch(
        f"/api/notes/{linked_note['id']}?ctx=work",
        json={"milestone_id": stream.json()["id"]},
    )
    gantt_after_link = client.get("/api/gantt?ctx=work").json()
    stream_data = gantt_after_link["projects"][0]["streams"][0]
    assert any(n["id"] == linked_note["id"] for n in stream_data["linked_notes"])
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


def test_gantt_streams_all_endpoint_includes_breadcrumb(client):
    """Usato dal campo di ricerca "stream" nel form nota — deve includere ogni
    Stream del progetto con etichetta completa "Progetto > Stream"."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Analisi"})
    client.post("/api/gantt/streams?ctx=work", json={"project_id": project["id"], "name": "Collection"})

    res = client.get("/api/gantt/streams/all?ctx=work")
    assert res.status_code == 200
    labels = {s["label"] for s in res.json()["streams"]}
    assert "ACME > Analisi" in labels
    assert "ACME > Collection" in labels

    # scoping per contesto: non deve comparire nell'altro contesto
    assert client.get("/api/gantt/streams/all?ctx=home").json()["streams"] == []


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
    """Le note collegate a uno stream vanno mostrate in ordine cronologico
    (start_date, poi due_date), non nell'ordine in cui sono state creare/il
    loro id — qui creo apposta la nota "più tardi" per prima."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()

    # entrambe le date sono nel passato rispetto a "oggi": la nota senza data
    # (il cui sort key ricade sulla data di creazione, cioè oggi) deve finire
    # dopo entrambe, in coda.
    later = client.post("/api/notes?ctx=work", json={
        "content": "step del 15 agosto", "milestone_id": stream["id"], "start_date": "2026-08-15",
    }).json()
    earlier = client.post("/api/notes?ctx=work", json={
        "content": "step del 1 agosto", "milestone_id": stream["id"], "start_date": "2026-08-01",
    }).json()
    no_date = client.post("/api/notes?ctx=work", json={
        "content": "step senza data", "milestone_id": stream["id"],
    }).json()

    gantt = client.get("/api/gantt?ctx=work").json()
    linked = gantt["projects"][0]["streams"][0]["linked_notes"]
    ids_in_order = [n["id"] for n in linked]
    # earlier (1 agosto) prima di later (15 agosto), nonostante creata dopo;
    # la nota senza data va in coda (fallback sulla data di creazione = oggi)
    assert ids_in_order.index(earlier["id"]) < ids_in_order.index(later["id"])
    assert ids_in_order[-1] == no_date["id"]


def test_stream_dateless_and_note_link_progress(client):
    """Uno Stream è creabile senza date (esiste come contenitore di note) e la
    sua % si calcola sulle note collegate via milestone_id."""
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()

    stream = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Analisi",
    })
    assert stream.status_code == 201
    assert stream.json()["start_date"] is None
    stream_id = stream.json()["id"]

    n1 = client.post("/api/notes?ctx=work", json={"content": "step 1", "status": "done", "milestone_id": stream_id}).json()
    n2 = client.post("/api/notes?ctx=work", json={"content": "step 2", "status": "todo"}).json()
    client.patch(f"/api/notes/{n2['id']}?ctx=work", json={"milestone_id": stream_id})

    gantt = client.get("/api/gantt?ctx=work").json()
    stream_data = gantt["projects"][0]["streams"][0]
    assert stream_data["progress_total"] == 2
    assert stream_data["progress_done"] == 1
    assert stream_data["progress"] == 50
    assert {n["id"] for n in stream_data["linked_notes"]} == {n1["id"], n2["id"]}

    # aggiungere le date dopo deve funzionare (stream creato senza, valorizzato in seguito)
    dated = client.patch(f"/api/gantt/streams/{stream_id}?ctx=work",
                          json={"start_date": "2026-06-01", "end_date": "2026-06-10"})
    assert dated.status_code == 200
    assert dated.json()["start_date"] == "2026-06-01"

    # clear_milestone rimuove la nota dallo stream
    client.patch(f"/api/notes/{n2['id']}?ctx=work", json={"clear_milestone": True})
    gantt2 = client.get("/api/gantt?ctx=work").json()
    stream_data2 = gantt2["projects"][0]["streams"][0]
    assert stream_data2["progress_total"] == 1
    assert stream_data2["progress"] == 100


def test_project_progress_aggregates_all_streams(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()

    stream_a = client.post("/api/gantt/streams?ctx=work",
                            json={"project_id": project["id"], "name": "A"}).json()
    stream_b = client.post("/api/gantt/streams?ctx=work",
                            json={"project_id": project["id"], "name": "B"}).json()

    n1 = client.post("/api/notes?ctx=work", json={"content": "a1", "status": "done", "milestone_id": stream_a["id"]}).json()
    n2 = client.post("/api/notes?ctx=work", json={"content": "b1", "status": "todo", "milestone_id": stream_b["id"]}).json()
    n3 = client.post("/api/notes?ctx=work", json={"content": "b2", "status": "todo", "milestone_id": stream_b["id"]}).json()

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = gantt["projects"][0]
    # 1 done su 3 totali, sommando entrambi gli stream del progetto
    assert proj["progress"] == 33


def test_gantt_stream_delete_unlinks_note_not_delete(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()
    note = client.post("/api/notes?ctx=work", json={"content": "step 1", "milestone_id": stream["id"]}).json()

    assert client.delete(f"/api/gantt/streams/{stream['id']}?ctx=work").status_code == 204

    gantt = client.get("/api/gantt?ctx=work").json()
    proj = gantt["projects"][0]
    assert proj["streams"] == []

    # la nota resta, solo scollegata (lo stream è stato cancellato per davvero,
    # non "svuotato" — è la stessa entità, non più un contenitore separato)
    updated_note = next(n for n in client.get("/api/notes?ctx=work").json() if n["id"] == note["id"])
    assert updated_note["milestone_id"] is None


def test_gantt_project_delete_unlinks_streams(client):
    project = client.post("/api/gantt/projects?ctx=work", json={"name": "ACME"}).json()
    stream = client.post("/api/gantt/streams?ctx=work",
                          json={"project_id": project["id"], "name": "Analisi"}).json()
    note = client.post("/api/notes?ctx=work", json={"content": "step 1", "milestone_id": stream["id"]}).json()

    release = client.post("/api/gantt/streams?ctx=work", json={
        "project_id": project["id"], "name": "Release",
        "start_date": "2026-05-16", "end_date": "2026-05-20",
    }).json()
    release_note = client.post("/api/notes?ctx=work", json={"content": "release note"}).json()
    client.patch(f"/api/notes/{release_note['id']}?ctx=work", json={"milestone_id": release["id"]})

    assert client.delete(f"/api/gantt/projects/{project['id']}?ctx=work").status_code == 204

    notes = client.get("/api/notes?ctx=work").json()
    assert next(n for n in notes if n["id"] == note["id"])["milestone_id"] is None
    assert next(n for n in notes if n["id"] == release_note["id"])["milestone_id"] is None
    # anche la nota auto-creata dallo stream deve restare (non cancellata)
    assert any(n["content"] == "Release" for n in notes)


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
                {"name": "Analisi", "start_date": None, "end_date": None},
                {"name": "Release", "start_date": "2026-09-01", "end_date": "2026-09-10"},
            ],
        }]
    }
    text = _format_gantt(gantt, date(2026, 9, 5))
    assert "Release" in text
    assert "Analisi" not in text  # senza date, non è "attivo" per il recap
