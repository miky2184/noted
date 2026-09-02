import importlib
import sys

import pytest
from fastapi.testclient import TestClient


MODULE_PREFIXES = ("db.engine", "web.app", "web.routers", "web.services", "web.deps")


TEST_API_TOKEN = "test-token"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "notes.db"
    doc_root = tmp_path / "docs"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("NOTED_API_TOKEN", TEST_API_TOKEN)

    # db.config persists settings (doc_root, api_token, ...) to a real,
    # machine-wide file (see db/paths.py::config_path). Redirect it into
    # tmp_path so tests never read/write the developer's actual noted config.
    import db.paths
    monkeypatch.setattr(db.paths, "config_path", lambda: tmp_path / "config.json")

    for name in list(sys.modules):
        if name in MODULE_PREFIXES or name.startswith(MODULE_PREFIXES):
            sys.modules.pop(name)

    app_module = importlib.import_module("web.app")

    with TestClient(app_module.app) as test_client:
        test_client.headers.update({"X-Noted-Token": TEST_API_TOKEN})
        res = test_client.patch("/api/settings", json={"doc_root": str(doc_root)})
        assert res.status_code == 200
        yield test_client
