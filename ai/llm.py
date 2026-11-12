"""Client unico per l'LLM locale (Ollama). Nessun servizio cloud.

Tutte le funzionalità AI (recap, bozze email, analisi documenti, Q&A) passano
da qui, così timeout, contesto, gestione errori e il controllo di privacy
(l'endpoint deve essere locale) vivono in un solo posto.
"""
import ipaddress
import json
from collections.abc import Iterator
from typing import Optional
from urllib.parse import urlparse

import httpx


class LLMError(Exception):
    """Errore dell'LLM locale, con messaggio già pronto per l'utente."""
    status_code = 502


class LLMUnavailable(LLMError):
    status_code = 503


def is_local_url(url: str) -> bool:
    """True se l'URL punta a questa macchina o alla rete privata (LAN)."""
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "") or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _settings() -> tuple[str, str, int]:
    from db.config import get_ollama_url, get_ollama_model, get_ollama_num_ctx
    url = get_ollama_url()
    if not is_local_url(url):
        # Difesa in profondità: set_ollama_url già rifiuta, ma il file di
        # configurazione può essere modificato a mano.
        raise LLMError(
            f"Endpoint LLM non locale ({url}): bloccato per proteggere la riservatezza dei dati."
        )
    return url, get_ollama_model(), get_ollama_num_ctx()


def _payload(prompt: str, system: Optional[str], images: Optional[list[str]],
             json_mode: bool, stream: bool, num_predict: Optional[int],
             num_ctx: Optional[int] = None) -> tuple[str, dict]:
    url, model, default_ctx = _settings()
    num_ctx = max(num_ctx or 0, default_ctx)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    user: dict = {"role": "user", "content": prompt}
    if images:
        user["images"] = images
    messages.append(user)
    options: dict = {"num_ctx": num_ctx}
    if num_predict:
        options["num_predict"] = num_predict
    body: dict = {"model": model, "messages": messages, "stream": stream, "options": options}
    if json_mode:
        body["format"] = "json"
    return url, body


def _translate(exc: Exception) -> LLMError:
    if isinstance(exc, httpx.ConnectError):
        return LLMUnavailable("Ollama non raggiungibile. Avvialo con: ollama serve")
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("Ollama timeout — modello troppo lento o non ancora caricato")
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 404:
            return LLMError("Modello Ollama non trovato. Scaricalo con: ollama pull <modello>")
        return LLMError(f"Ollama ha restituito un errore ({exc.response.status_code})")
    return LLMError(f"Errore LLM locale: {exc}")


def ctx_for(prompt: str, reserve: int = 1024) -> int:
    """Stima grossolana (~3 caratteri/token in italiano) della finestra necessaria."""
    return min(len(prompt) // 3 + reserve, 32768)


def _timeout(read: float) -> httpx.Timeout:
    return httpx.Timeout(connect=5.0, read=read, write=30.0, pool=5.0)


def check_available() -> None:
    """Solleva LLMUnavailable se Ollama non risponde. Chiamata veloce (2s)."""
    url, _, _ = _settings()
    try:
        httpx.get(f"{url}/api/tags", timeout=2.0).raise_for_status()
    except Exception as exc:
        raise LLMUnavailable("Ollama non raggiungibile. Avvialo con: ollama serve") from exc


def generate(prompt: str, *, system: Optional[str] = None, images: Optional[list[str]] = None,
             json_mode: bool = False, num_predict: Optional[int] = None,
             num_ctx: Optional[int] = None, read_timeout: float = 300.0) -> str:
    url, body = _payload(prompt, system, images, json_mode, False, num_predict, num_ctx)
    try:
        res = httpx.post(f"{url}/api/chat", json=body, timeout=_timeout(read_timeout))
        res.raise_for_status()
        return res.json()["message"]["content"].strip()
    except LLMError:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


def stream(prompt: str, *, system: Optional[str] = None, num_predict: Optional[int] = None,
           num_ctx: Optional[int] = None, read_timeout: float = 300.0) -> Iterator[str]:
    url, body = _payload(prompt, system, None, False, True, num_predict, num_ctx)
    try:
        with httpx.stream("POST", f"{url}/api/chat", json=body, timeout=_timeout(read_timeout)) as res:
            res.raise_for_status()
            for line in res.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    break
    except LLMError:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


def strip_code_fence(raw: str) -> str:
    """I modelli a volte avvolgono il JSON in un blocco markdown."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def generate_json(prompt: str, *, system: Optional[str] = None, images: Optional[list[str]] = None,
                  num_predict: Optional[int] = None, num_ctx: Optional[int] = None,
                  read_timeout: float = 300.0) -> dict:
    raw = generate(prompt, system=system, images=images, json_mode=True,
                   num_predict=num_predict, num_ctx=num_ctx, read_timeout=read_timeout)
    try:
        data = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise LLMError("Il modello non ha restituito JSON valido") from exc
    if not isinstance(data, dict):
        raise LLMError("Il modello non ha restituito un oggetto JSON")
    return data
