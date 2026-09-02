"""Minimal shared-token auth for the /api/* surface.

noted has no user/password system: it is meant to run on one trusted
machine, optionally reachable from other personal devices on the same LAN
(e.g. to use the microphone from a phone). Every request under /api/* must
carry the shared secret in the ``X-Noted-Token`` header; the token itself
is generated once (or set via NOTED_API_TOKEN) — see db/config.get_api_token.

The index page (``/``) and static assets are intentionally left out: they
contain no per-device secret to protect and gating them would need a
cookie/login flow, which is more than this single-user tool needs.
"""
import hmac

from starlette.requests import Request
from starlette.responses import JSONResponse

from db.config import get_api_token

TOKEN_HEADER = "X-Noted-Token"

# Paths under /api/ that must stay reachable without the token, if any.
_EXEMPT_PREFIXES: tuple[str, ...] = ()


def _is_valid(token: str | None) -> bool:
    if not token:
        return False
    # constant-time compare to avoid leaking the token via timing
    return hmac.compare_digest(token, get_api_token())


async def token_auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(_EXEMPT_PREFIXES):
        if not _is_valid(request.headers.get(TOKEN_HEADER)):
            return JSONResponse(
                {"detail": "Token mancante o non valido. Impostazioni → 🔑 Accesso."},
                status_code=401,
            )
    return await call_next(request)
