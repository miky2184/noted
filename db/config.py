import json
from pathlib import Path

MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
}
DEFAULT_MODEL = "claude-sonnet-4-6"


def _config_path() -> Path:
    from db.paths import config_path
    return config_path()


def _load() -> dict:
    p = _config_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def get_model() -> str:
    return _load().get("model", DEFAULT_MODEL)


def set_model(model_id: str) -> None:
    data = _load()
    data["model"] = model_id
    _save(data)


def get_port() -> int:
    return int(_load().get("port", 7979))


def set_port(port: int) -> None:
    data = _load()
    data["port"] = port
    _save(data)
