def _add(client, **kw):
    return client.post("/api/links?ctx=work", json=kw)


def test_manual_link_crud_and_search(client):
    a = _add(client, url="https://acme.sharepoint.com/doc1", title="Specifiche ingestion",
             cliente="ACME", project="DATA PLATFORM")
    assert a.status_code == 201 and a.json()["source"] == "SharePoint"
    _add(client, url="https://drive.google.com/file/d/1", title="Budget FinOps", cliente="BETA", project="FINOPS")
    _add(client, url="https://example.com/x", title="Zeta senza cliente")

    # ricerca su titolo, cliente, progetto e URL
    assert [l["title"] for l in client.get("/api/links?ctx=work&q=ingestion").json()] == ["Specifiche ingestion"]
    assert [l["title"] for l in client.get("/api/links?ctx=work&q=finops").json()] == ["Budget FinOps"]
    assert len(client.get("/api/links?ctx=work&q=drive.google").json()) == 1
    assert client.get("/api/links?ctx=work&q=acme%20platform").json()[0]["title"] == "Specifiche ingestion"
    # filtro e ordinamento
    assert len(client.get("/api/links?ctx=work&cliente=beta").json()) == 1
    by_title = [l["title"] for l in client.get("/api/links?ctx=work&sort=title").json()]
    assert by_title == sorted(by_title, key=str.lower)
    by_cliente = [l["cliente"] for l in client.get("/api/links?ctx=work&sort=cliente").json()]
    assert by_cliente == ["ACME", "BETA", None]          # senza cliente in fondo

    # modifica, duplicato, isolamento contesto, eliminazione
    lid = a.json()["id"]
    assert client.patch(f"/api/links/{lid}?ctx=work", json={"title": "Nuovo"}).json()["title"] == "Nuovo"
    assert _add(client, url="https://acme.sharepoint.com/doc1").status_code == 409
    assert client.patch(f"/api/links/{lid}?ctx=home", json={"title": "x"}).status_code == 404
    assert client.get("/api/links?ctx=home").json() == []
    assert client.delete(f"/api/links/{lid}?ctx=work").status_code == 204
    assert client.delete(f"/api/links/{lid}?ctx=work").status_code == 404


def test_only_http_links_accepted(client):
    for bad in ("javascript:alert(1)", "ftp://x.y/z", "not a url", "https://"):
        assert _add(client, url=bad).status_code == 400, bad
    ok = client.patch("/api/links/1?ctx=work", json={"url": "javascript:alert(1)"})
    assert ok.status_code == 400


def test_links_detected_from_notes(client):
    note = client.post("/api/notes?ctx=work", json={
        "content": "Specifiche in https://acme.sharepoint.com/s/spec.docx, vedi anche https://1drv.ms/w/abc.",
        "cliente": "ACME", "project": "DATA PLATFORM"}).json()
    links = client.get("/api/links?ctx=work&sort=title").json()
    assert {l["url"] for l in links} == {"https://acme.sharepoint.com/s/spec.docx", "https://1drv.ms/w/abc"}
    assert all(l["cliente"] == "ACME" and l["project"] == "DATA PLATFORM" and l["note_id"] == note["id"] for l in links)
    assert links[0]["title"].startswith("Specifiche in")

    # modificare la nota con lo stesso URL non duplica; un nuovo URL viene aggiunto
    client.patch(f"/api/notes/{note['id']}?ctx=work",
                 json={"content": "Specifiche in https://acme.sharepoint.com/s/spec.docx e https://drive.google.com/d/9"})
    assert len(client.get("/api/links?ctx=work").json()) == 3
    # nota senza link: nessun effetto, e il salvataggio nota non fallisce
    assert client.post("/api/notes?ctx=work", json={"content": "niente url"}).status_code == 201
    assert len(client.get("/api/links?ctx=work").json()) == 3


def test_link_inherits_missing_client_but_never_overwrites(client):
    _add(client, url="https://example.com/a", title="Mio nome", cliente="MANUALE")
    client.post("/api/notes?ctx=work", json={"content": "ecco https://example.com/a",
                                             "cliente": "ALTRO", "project": "P1"})
    link = client.get("/api/links?ctx=work").json()[0]
    assert (link["title"], link["cliente"], link["project"]) == ("Mio nome", "MANUALE", "P1")


def test_import_links_from_existing_notes_and_backup_roundtrip(client):
    client.post("/api/notes?ctx=work", json={"content": "vecchia nota https://example.com/old"})
    # i link creati alla scrittura vengono eliminati per simulare note pre-esistenti
    for l in client.get("/api/links?ctx=work").json():
        client.delete(f"/api/links/{l['id']}?ctx=work")
    assert client.post("/api/links/import-from-notes?ctx=work").json() == {"created": 1}
    assert client.post("/api/links/import-from-notes?ctx=work").json() == {"created": 0}

    backup = client.get("/api/backup/json").json()
    assert [l["url"] for l in backup["links"]] == ["https://example.com/old"]
    for l in client.get("/api/links?ctx=work").json():
        client.delete(f"/api/links/{l['id']}?ctx=work")
    assert client.post("/api/restore/json", json=backup).status_code == 200
    assert [l["url"] for l in client.get("/api/links?ctx=work").json()] == ["https://example.com/old"]
