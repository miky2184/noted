"""
noted tray — menu bar app macOS con hotkey globale ⌃⌥N.

Dipendenze opzionali:
    pip install -e '.[tray]'   # rumps + pynput + PyObjC/Cocoa
"""
import json
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import rumps
except ImportError as _e:
    raise ImportError("rumps non installato. Esegui: pip install -e '.[tray]'") from _e

try:
    import AppKit  # noqa: F401
except ImportError as _e:
    raise ImportError("PyObjC/Cocoa non installato. Esegui: pip install -e '.[tray]'") from _e

try:
    from pynput import keyboard as _kb
    _PYNPUT = True
except ImportError:
    _PYNPUT = False

_ICON = Path(__file__).parent.parent / "web" / "static" / "logo.png"
_HOTKEY = "<ctrl>+<alt>+n"


def _show_input_panel(ctx: str) -> str | None:
    """NSAlert nativo con logo noted, text field e tasto Invio per confermare."""
    from AppKit import (
        NSAlert, NSTextField, NSImage, NSMakeRect, NSApp,
        NSAlertFirstButtonReturn, NSColor, NSFont,
    )

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Nuova nota")
    alert.setInformativeText_(f"Contesto: {ctx}")
    alert.addButtonWithTitle_("Aggiungi")
    alert.addButtonWithTitle_("Annulla")

    if _ICON.exists():
        img = NSImage.alloc().initWithContentsOfFile_(str(_ICON))
        alert.setIcon_(img)

    # Text field come accessory view
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 24))
    field.setPlaceholderString_("Scrivi la nota…")
    field.setFont_(NSFont.systemFontOfSize_(14))
    alert.setAccessoryView_(field)
    alert.window().setInitialFirstResponder_(field)

    # Porta la finestra in primo piano anche da un'altra app
    NSApp.activateIgnoringOtherApps_(True)
    response = alert.runModal()

    if response == NSAlertFirstButtonReturn:
        text = field.stringValue().strip()
        return text if text else None
    return None


def _is_https(port: int) -> bool:
    from db.paths import cert_path, key_path
    return cert_path().exists() and key_path().exists()


def _base_url(port: int) -> str:
    scheme = "https" if _is_https(port) else "http"
    return f"{scheme}://127.0.0.1:{port}"


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _load_contexts() -> list[str]:
    """Legge i contesti disponibili direttamente dal DB (senza server)."""
    try:
        from db.engine import get_session, init_db
        from db import crud
        init_db()
        with get_session() as session:
            return [c.name for c in crud.get_contexts(session)]
    except Exception:
        return ["default"]


def _load_favorite_ctx() -> str:
    """Legge il contesto preferito dal config locale."""
    try:
        from db.config import get_favorite_ctx
        return get_favorite_ctx()
    except Exception:
        return "default"


class NotedTrayApp(rumps.App):
    def __init__(self, ctx: str | None = None, port: int = 7979):
        super().__init__("noted", title="📝", quit_button=None)

        # Rimuovi dal Dock — rumps ha già chiamato NSApplication.sharedApplication()
        # in super().__init__, quindi la referenza è valida subito (senza timer)
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)
        except Exception:
            pass

        if _ICON.exists():
            self.template = False
            self.icon = str(_ICON)
            self.title = ""

        # Usa il contesto preferito se non specificato esplicitamente
        self._ctx = ctx or _load_favorite_ctx()
        self._port = port
        self._triggered = False
        self._hotkey_error: str | None = None

        self._build_menu()

        self._poll_timer = rumps.Timer(self._poll, 0.15)
        self._poll_timer.start()

        if _PYNPUT:
            threading.Thread(target=self._listen_hotkey, daemon=True).start()
        else:
            rumps.notification(
                title="noted",
                subtitle="Hotkey non disponibile",
                message="Installa pynput: pip install pynput",
            )

    def _build_menu(self):
        contexts = _load_contexts()

        # Dizionario name→MenuItem per poter aggiornare le spunte senza
        # dover navigare l'albero rumps (che non espone i submenu facilmente)
        self._ctx_items: dict[str, rumps.MenuItem] = {}
        for name in contexts:
            item = rumps.MenuItem(name.upper(), callback=self._switch_ctx)
            item.state = 1 if name == self._ctx else 0   # 1 = ✓
            self._ctx_items[name] = item

        self.menu = [
            rumps.MenuItem("Apri dashboard", callback=self._open_dashboard),
            rumps.MenuItem("Aggiungi nota…", callback=self._open_input),
            None,
            rumps.MenuItem("Contesto", list(self._ctx_items.values())),
            None,
            rumps.MenuItem("Esci", callback=rumps.quit_application),
        ]

    def _switch_ctx(self, sender):
        new_ctx = sender.title.lower()
        self._ctx = new_ctx
        for name, item in self._ctx_items.items():
            item.state = 1 if name == new_ctx else 0
        # Persisti il contesto scelto come preferito
        try:
            from db.config import set_favorite_ctx
            set_favorite_ctx(new_ctx)
        except Exception:
            pass

    # ── hotkey ──────────────────────────────────────────────────────────────

    def _listen_hotkey(self):
        def _on_activate():
            self._triggered = True

        try:
            with _kb.GlobalHotKeys({_HOTKEY: _on_activate}) as h:
                h.join()
        except Exception as exc:
            self._hotkey_error = str(exc) or "Permessi Accessibilità mancanti"

    def _poll(self, _):
        if self._hotkey_error:
            message = self._hotkey_error
            self._hotkey_error = None
            rumps.notification(
                title="noted",
                subtitle="Hotkey non attiva",
                message=f"Concedi Accessibilità a Terminale/Python. Dettaglio: {message}",
            )
        if self._triggered:
            self._triggered = False
            self._open_input(None)

    # ── callbacks ───────────────────────────────────────────────────────────

    def _open_dashboard(self, _):
        import subprocess
        subprocess.Popen(["open", _base_url(self._port)])

    def _open_input(self, _):
        text = _show_input_panel(self._ctx)
        if text:
            self._post_note(text)

    # ── network ─────────────────────────────────────────────────────────────

    def _post_note(self, content: str):
        query = urllib.parse.urlencode({"ctx": self._ctx})
        url = f"{_base_url(self._port)}/api/notes?{query}"
        payload = json.dumps({"content": content}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5, context=_ssl_ctx()):
                pass
            rumps.notification(
                title="noted",
                subtitle="Nota salvata ✓",
                message=content[:100],
            )
        except urllib.error.URLError as exc:
            rumps.notification(
                title="noted",
                subtitle="Server non raggiungibile",
                message=f"Avvia prima: noted web  ({exc.reason})",
            )
        except Exception as exc:
            rumps.notification(title="noted", subtitle="Errore", message=str(exc))


def run_tray(ctx: str | None = None, port: int = 7979) -> None:
    NotedTrayApp(ctx=ctx, port=port).run()
