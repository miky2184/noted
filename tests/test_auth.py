from tests.conftest import TEST_API_TOKEN


def test_api_request_without_token_is_rejected(client):
    res = client.get("/api/settings", headers={"X-Noted-Token": ""})
    assert res.status_code == 401


def test_api_request_with_wrong_token_is_rejected(client):
    res = client.get("/api/settings", headers={"X-Noted-Token": "not-the-token"})
    assert res.status_code == 401


def test_api_request_with_correct_token_succeeds(client):
    # the `client` fixture already sets the right header by default
    res = client.get("/api/settings")
    assert res.status_code == 200


def test_index_page_does_not_require_token(client):
    res = client.get("/", headers={"X-Noted-Token": ""})
    assert res.status_code == 200


def test_settings_token_endpoint_reports_current_token(client):
    # the `client` fixture pins NOTED_API_TOKEN, so both the middleware and
    # this endpoint must agree on the same value
    shown = client.get("/api/settings/token").json()
    assert shown["token"] == TEST_API_TOKEN


def test_regenerate_api_token_rotates_and_invalidates_old_value(tmp_path, monkeypatch):
    """Unit-level check of the rotation logic itself (db.config), without the
    NOTED_API_TOKEN env override the `client` fixture uses for a stable
    header — that override always wins in get_api_token(), so exercising
    real rotation needs it absent."""
    monkeypatch.delenv("NOTED_API_TOKEN", raising=False)
    import db.paths
    monkeypatch.setattr(db.paths, "config_path", lambda: tmp_path / "config.json")

    from db import config as db_config

    first = db_config.get_api_token()
    assert db_config.get_api_token() == first  # stable across calls

    second = db_config.regenerate_api_token()
    assert second != first
    assert db_config.get_api_token() == second  # rotation persisted


def test_regenerate_api_token_is_a_noop_when_env_override_set(monkeypatch):
    monkeypatch.setenv("NOTED_API_TOKEN", "pinned-token")
    from db import config as db_config

    assert db_config.get_api_token() == "pinned-token"
    assert db_config.regenerate_api_token() == "pinned-token"
