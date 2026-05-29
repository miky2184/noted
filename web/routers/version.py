"""Version check endpoint."""
import urllib.request
import json
from datetime import datetime, timedelta

from fastapi import APIRouter

router = APIRouter()

CURRENT_VERSION = "0.1.0"
GITHUB_REPO = "miky2184/noted"
_CHECK_INTERVAL_HOURS = 6


def _load_config() -> dict:
    from db.config import _config_path
    p = _config_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    from db.config import _config_path
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def _parse_version(v: str) -> tuple:
    v = v.lstrip('v')
    try:
        return tuple(int(x) for x in v.split('.')[:3])
    except Exception:
        return (0, 0, 0)


def check_for_update(force: bool = False) -> dict:
    """Check GitHub for latest release. Cached for _CHECK_INTERVAL_HOURS."""
    cfg = _load_config()
    cache = cfg.get("update_check", {})

    last_check = cache.get("last_check")
    if not force and last_check:
        try:
            last_dt = datetime.fromisoformat(last_check)
            if datetime.now() - last_dt < timedelta(hours=_CHECK_INTERVAL_HOURS):
                return cache
        except Exception:
            pass

    result = {
        "current": CURRENT_VERSION,
        "latest": CURRENT_VERSION,
        "has_update": False,
        "release_url": "",
        "release_name": "",
        "last_check": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }

    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "noted-app/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        latest = data.get("tag_name", "").lstrip("v")
        if latest:
            result["latest"] = latest
            result["has_update"] = _parse_version(latest) > _parse_version(CURRENT_VERSION)
            result["release_url"] = data.get("html_url", "")
            result["release_name"] = data.get("name", f"v{latest}")
    except Exception as e:
        result["error"] = str(e)

    cfg["update_check"] = result
    _save_config(cfg)
    return result


@router.get("/api/version")
async def api_version():
    return check_for_update()
