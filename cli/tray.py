"""
noted tray — menu bar app macOS con hotkey globale ⌘⇧N.

Dipendenze opzionali:
    pip install -e '.[tray]'   # rumps + pynput
"""
import json
import ssl
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import rumps
except ImportError as _e:
    raise ImportError("rumps non installato. Esegui: pip install -e '.[tray]'") from _e

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


class NotedTrayApp(rumps.App):
    def __init__(self, ctx: str = "default", port: int = 7979):
        super().__init__("noted", title="📝", quit_button=None)

        if _ICON.exists():
            self.template = False   # deve essere impostato PRIMA di icon
            self.icon = str(_ICON)
            self.title = ""

        # Rimuove l'icona dal Dock dopo che il run loop è partito
        rumps.Timer(self._hide_dock, 0.1).start()
        self._ctx = ctx
        self._port = port
        self._triggered = False

        self.menu = [
            rumps.MenuItem("Apri dashboard", callback=self._open_dashboard),
            rumps.MenuItem(f"Contesto: {ctx}"),
            None,
            rumps.MenuItem("Aggiungi nota…", callback=self._open_input),
            None,
            rumps.MenuItem("Esci", callback=rumps.quit_application),
        ]

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

    # ── dock ────────────────────────────────────────────────────────────────

    def _hide_dock(self, timer):
        timer.stop()
        try:
            from AppKit import NSApp
            NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
        except Exception:
            pass

    # ── hotkey ──────────────────────────────────────────────────────────────

    def _listen_hotkey(self):
        def _on_activate():
            self._triggered = True

        try:
            with _kb.GlobalHotKeys({_HOTKEY: _on_activate}) as h:
                h.join()
        except Exception:
            pass  # Accessibility permissions non concesse

    def _poll(self, _):
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
        url = f"{_base_url(self._port)}/api/notes?ctx={self._ctx}"
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


def run_tray(ctx: str = "default", port: int = 7979) -> None:
    NotedTrayApp(ctx=ctx, port=port).run()
