import importlib


def _mk(client, ctx="work", **kw):
    body = {"content": "x", **kw}
    res = client.post(f"/api/notes?ctx={ctx}", json=body)
    assert res.status_code == 201
    return res.json()


def test_overview_groups_open_work(client):
    _mk(client, content="nota libera")                       # inbox (nessuno stato)
    _mk(client, content="in corso", status="wip", project="ALFA")
    _mk(client, content="attesa cliente", status="waiting", project="ALFA")
    _mk(client, content="fatto", status="done")
    data = client.get("/api/overview?ctx=work").json()
    assert [n["content"] for n in data["wip"]] == ["in corso"]
    assert [n["content"] for n in data["waiting"]] == ["attesa cliente"]
    assert data["inbox_count"] == 1
    assert data["open_count"] == 2
    assert data["projects"] == [{"name": "ALFA", "open": 2}]
    assert len(data["recent"]) == 4
    # isolamento per contesto
    assert client.get("/api/overview?ctx=home").json()["open_count"] == 0


def test_ask_cites_sources_and_skips_llm_when_nothing_found(client, monkeypatch):
    llm = importlib.import_module("ai.llm")
    prompts = []
    monkeypatch.setattr(llm, "generate", lambda prompt, **kw: prompts.append(prompt) or "Deciso il rilascio [N1]")
    n = _mk(client, content="Decisione: rilascio in produzione del progetto Atlante venerdì")
    _mk(client, content="pranzo con il team")

    res = client.post("/api/ask?ctx=work", json={"question": "Cosa abbiamo deciso sul rilascio di Atlante?"})
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "Deciso il rilascio [N1]"
    assert [s["id"] for s in body["sources"]] == [n["id"]]
    assert f"[N{n['id']}]" in prompts[0] and "pranzo" not in prompts[0]

    prompts.clear()
    res = client.post("/api/ask?ctx=work", json={"question": "zxqwv inesistente"})
    assert res.json()["sources"] == [] and prompts == []   # nessuna chiamata AI, niente invenzioni

    assert client.post("/api/ask?ctx=work", json={"question": "  "}).status_code == 400


def test_ask_reports_llm_unavailable(client, monkeypatch):
    llm = importlib.import_module("ai.llm")

    def down(*a, **kw):
        raise llm.LLMUnavailable("Ollama non raggiungibile. Avvialo con: ollama serve")
    monkeypatch.setattr(llm, "generate", down)
    _mk(client, content="roadmap Atlante")
    res = client.post("/api/ask?ctx=work", json={"question": "roadmap Atlante?"})
    assert res.status_code == 503 and "Ollama" in res.json()["detail"]


def test_extract_tasks_returns_validated_proposals_only(client, monkeypatch):
    llm = importlib.import_module("ai.llm")
    monkeypatch.setattr(llm, "generate_json", lambda *a, **kw: {"tasks": [
        {"title": "Inviare il report", "due_date": "2026-12-01", "priority": "HIGH"},
        {"title": "Chiamare Marco", "due_date": "domani", "priority": "boh"},
        {"title": "  "}, "spazzatura",
    ]})
    note = _mk(client, content="Meeting: inviare report entro 1/12, chiamare Marco", project="ALFA")
    res = client.post(f"/api/notes/{note['id']}/extract-tasks?ctx=work")
    assert res.status_code == 200
    assert res.json()["tasks"] == [
        {"title": "Inviare il report", "due_date": "2026-12-01", "priority": "high"},
        {"title": "Chiamare Marco", "due_date": None, "priority": "medium"},
    ]
    assert res.json()["project"] == "ALFA"
    # non distruttivo: nessuna nota creata
    assert len(client.get("/api/notes?ctx=work").json()) == 1
    assert client.post("/api/notes/9999/extract-tasks?ctx=work").status_code == 404


def test_deleted_gantt_project_does_not_resurrect(client):
    note = _mk(client, content="lavoro", cliente="ACME", project="ATLANTE", status="todo")
    gantt = client.get("/api/gantt?ctx=work").json()
    proj = next(p for p in gantt["projects"] if p["name"].lower() == "atlante")
    assert client.delete(f"/api/gantt/projects/{proj['id']}?ctx=work").status_code == 204
    again = client.get("/api/gantt?ctx=work").json()
    assert not any(p["name"].lower() == "atlante" for p in again["projects"])
    # la nota resta, con testo e cliente intatti
    kept = [n for n in client.get("/api/notes?ctx=work").json() if n["id"] == note["id"]][0]
    assert kept["content"] == "lavoro" and kept["cliente"] == "ACME" and kept["project"] is None


def test_index_assets_are_versioned(client):
    import re
    html = client.get("/").text
    assert re.search(r'/static/js/app\.js\?v=\d+', html)


def test_gantt_is_derived_from_tasks(client):
    """Scrivere una nota con cliente+progetto+date basta: il Gantt la mostra
    senza creare Stream/Fasi, e il progresso viene dallo stato delle note."""
    a = _mk(client, content="Analisi", cliente="ACME", project="ATLANTE",
            start_date="2026-12-01", due_date="2026-12-05", status="done")
    b = _mk(client, content="Rilascio", cliente="ACME", project="ATLANTE",
            start_date="2026-12-06", due_date="2026-12-10", status="todo")
    _mk(client, content="altro cliente", cliente="BETA", project="ZETA", status="todo")

    projects = {p["name"]: p for p in client.get("/api/gantt?ctx=work").json()["projects"]}
    atlante = projects["ATLANTE"]
    assert atlante["client_name"] == "ACME"
    assert atlante["streams"] == []
    assert [n["id"] for n in atlante["notes"]] == [a["id"], b["id"]]   # per periodo
    assert (atlante["tasks_total"], atlante["tasks_done"], atlante["progress"]) == (2, 1, 50)
    assert [n["content"] for n in projects["ZETA"]["notes"]] == ["altro cliente"]


def test_ask_with_time_words_does_not_crash(client, monkeypatch):
    """Domande con "oggi/ieri/settimana" aggiungono una finestra temporale al
    retrieval: la query per data deve funzionare (regressione: 500 per datetime naive)."""
    llm = importlib.import_module("ai.llm")
    monkeypatch.setattr(llm, "generate", lambda prompt, **kw: "ok")
    n = _mk(client, content="riunione di oggi sul monitoring")
    for q in ("Cosa ho fatto oggi?", "Cosa ho fatto ieri?", "Cosa ho fatto questa settimana?",
              "Cosa ho fatto la settimana scorsa?"):
        res = client.post("/api/ask?ctx=work", json={"question": q})
        assert res.status_code == 200, (q, res.text)
    res = client.post("/api/ask?ctx=work", json={"question": "Cosa ho fatto oggi?"}).json()
    assert [s["id"] for s in res["sources"]] == [n["id"]]


def test_ask_about_priorities_is_built_from_data_without_llm(client, monkeypatch):
    from datetime import date, timedelta
    llm = importlib.import_module("ai.llm")

    def never(*a, **kw):
        raise AssertionError("per le priorità non serve il modello")
    monkeypatch.setattr(llm, "generate", never)
    d = lambda n: (date.today() + timedelta(days=n)).isoformat()
    late = _mk(client, content="report scaduto", status="todo", due_date=d(-3), project="ALFA")
    soon = _mk(client, content="invio offerta", status="todo", due_date=d(2))
    high = _mk(client, content="studio architettura", status="todo", priority="high")
    wip = _mk(client, content="sviluppo script", status="wip")
    later = _mk(client, content="riordino archivio", status="todo", due_date=d(60))
    _mk(client, content="già fatto", status="done", due_date=d(-1))
    _mk(client, content="appunto generico senza stato")

    res = client.post("/api/ask?ctx=work", json={"question": "quali sono le mie priorità per oggi?"})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "tasks"
    assert [s["id"] for s in body["sources"]] == [late["id"], soon["id"], high["id"], wip["id"], later["id"]]
    a = body["answer"]
    assert a.index("Scaduti") < a.index("In scadenza") < a.index("Priorità alta") < a.index("In corso") < a.index("Altri aperti")
    assert "report scaduto" in a and "ALFA" in a and "3 gg fa" in a and "tra 2 gg" in a
    assert "già fatto" not in a and "senza stato" not in a
    assert "Non hai task aperti" in client.post("/api/ask?ctx=home", json={"question": "cosa devo fare?"}).json()["answer"]
