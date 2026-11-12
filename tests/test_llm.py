"""Privacy: l'LLM deve essere locale e nessuna chiamata di rete parte da sola."""
import importlib
import json

import httpx
import pytest


def test_is_local_url():
    from ai.llm import is_local_url
    for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://192.168.1.20:11434",
                "http://10.0.0.5", "http://[::1]:11434", "http://mac.local:11434"):
        assert is_local_url(url), url
    for url in ("https://api.openai.com", "http://8.8.8.8:11434", "https://example.com"):
        assert not is_local_url(url), url


def test_remote_ollama_url_is_rejected(client):
    res = client.patch("/api/ollama/settings", json={"url": "https://example.com"})
    assert res.status_code == 400
    assert client.patch("/api/ollama/settings", json={"url": "http://localhost:11434"}).status_code == 200


def test_llm_blocks_remote_endpoint_even_if_config_edited(client, monkeypatch):
    llm = importlib.import_module("ai.llm")
    import db.config
    monkeypatch.setattr(db.config, "get_ollama_url", lambda: "https://example.com")
    with pytest.raises(llm.LLMError):
        llm.generate("ciao")


def test_stream_parses_ndjson_and_sets_context(client, monkeypatch):
    llm = importlib.import_module("ai.llm")
    seen = {}

    class _Res:
        def raise_for_status(self): pass
        def iter_lines(self):
            yield json.dumps({"message": {"content": "ci"}, "done": False})
            yield ""
            yield json.dumps({"message": {"content": "ao"}, "done": True})
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_stream(method, url, json, timeout):
        seen["url"], seen["body"] = url, json
        return _Res()

    monkeypatch.setattr(llm.httpx, "stream", fake_stream)
    assert "".join(llm.stream("prompt", num_ctx=20000)) == "ciao"
    assert seen["url"].startswith("http://localhost")
    assert seen["body"]["options"]["num_ctx"] == 20000


def test_connect_error_is_translated(client, monkeypatch):
    llm = importlib.import_module("ai.llm")

    def boom(*a, **kw):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(llm.httpx, "post", boom)
    with pytest.raises(llm.LLMUnavailable):
        llm.generate("x")


def test_update_check_is_opt_in(client, monkeypatch):
    version = importlib.import_module("web.routers.version")

    def no_network(*a, **kw):
        raise AssertionError("chiamata di rete non autorizzata")
    monkeypatch.setattr(version.urllib.request, "urlopen", no_network)
    res = client.get("/api/version")
    assert res.status_code == 200
    assert res.json()["has_update"] is False


def test_ui_loads_no_external_resources(client):
    """Offline/privacy: la pagina non deve referenziare script, stili o font esterni."""
    import re
    html = client.get("/").text
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    # link di navigazione (es. release notes) ammessi solo se <a>, non risorse caricate
    resources = re.findall(r'<(?:script|link|img)[^>]+(?:src|href)="(https?://[^"]+)"', html)
    assert resources == [], resources
    for path in re.findall(r'<script[^>]+src="(/static/vendor/[^"]+)"', html):
        assert client.get(path).status_code == 200, path
