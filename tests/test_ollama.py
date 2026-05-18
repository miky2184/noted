import importlib

import httpx


class FakeOllamaResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://ollama.test/api/chat")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("Ollama error", request=request, response=response)


class FakeAsyncClient:
    post_response = None
    get_response = None
    last_post_url = None
    last_post_payload = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        type(self).last_post_url = url
        type(self).last_post_payload = json
        return type(self).post_response

    async def get(self, url):
        return type(self).get_response


def _patch_ollama_client(monkeypatch, post_payload=None, get_payload=None, status_code=200):
    ollama = importlib.import_module("web.routers.ollama")
    FakeAsyncClient.post_response = (
        FakeOllamaResponse(post_payload, status_code=status_code) if post_payload is not None else None
    )
    FakeAsyncClient.get_response = FakeOllamaResponse(get_payload or {})
    FakeAsyncClient.last_post_url = None
    FakeAsyncClient.last_post_payload = None
    monkeypatch.setattr(ollama.httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


def test_ollama_enhance_validates_and_normalizes_output(client, monkeypatch):
    fake_client = _patch_ollama_client(
        monkeypatch,
        post_payload={
            "message": {
                "content": """
                {
                  "content": "Chiamare Marco domani per aggiornamento sprint.",
                  "tags": ["Sprint", "Call", "Extra", "Ignored"],
                  "project": " acme ",
                  "priority": "HIGH",
                  "status": "TODO"
                }
                """
            }
        },
    )

    res = client.post("/api/notes/enhance", json={"content": "chiamare marco domani sprint acme"})

    assert res.status_code == 200
    assert res.json() == {
        "content": "Chiamare Marco domani per aggiornamento sprint.",
        "tags": "sprint,call,extra",
        "project": "ACME",
        "priority": "high",
        "status": "todo",
    }
    prompt = fake_client.last_post_payload["messages"][0]["content"]
    assert '"raw_note": "chiamare marco domani sprint acme"' in prompt


def test_ollama_enhance_rejects_invalid_metadata(client, monkeypatch):
    _patch_ollama_client(
        monkeypatch,
        post_payload={
            "message": {
                "content": """
                {
                  "content": "Nota migliorata",
                  "priority": "urgent",
                  "status": "done"
                }
                """
            }
        },
    )

    res = client.post("/api/notes/enhance", json={"content": "nota raw"})

    assert res.status_code == 500
    assert res.json()["detail"] == "Ollama ha restituito metadati non validi"


def test_ollama_status_reports_models(client, monkeypatch):
    _patch_ollama_client(
        monkeypatch,
        get_payload={"models": [{"name": "llama3.2"}, {"name": "mistral"}]},
    )

    res = client.get("/api/ollama/status")

    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["models"] == ["llama3.2", "mistral"]
