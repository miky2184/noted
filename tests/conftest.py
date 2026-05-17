import importlib
import sys

import pytest
from fastapi.testclient import TestClient


MODULE_PREFIXES = ("db.engine", "web.app", "web.routers", "web.services", "web.deps")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "notes.db"
    doc_root = tmp_path / "docs"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    for name in list(sys.modules):
        if name in MODULE_PREFIXES or name.startswith(MODULE_PREFIXES):
            sys.modules.pop(name)

    app_module = importlib.import_module("web.app")

    with TestClient(app_module.app) as test_client:
        res = test_client.patch("/api/settings", json={"doc_root": str(doc_root)})
        assert res.status_code == 200
        yield test_client
