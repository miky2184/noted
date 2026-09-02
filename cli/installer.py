"""Logica di installazione/rimozione del servizio per Mac, Linux, Windows."""
import sys
import subprocess
from pathlib import Path


HOST = "noted.local"
PORT = 7979


def _python() -> str:
    return sys.executable


def _noted_cmd() -> str:
    # se installato come script, è nel PATH; altrimenti usiamo il modulo
    import shutil
    cmd = shutil.which("noted")
    return cmd or f"{_python()} -m cli.main"


# ── macOS ──────────────────────────────────────────────────────────────────────

LAUNCHD_LABEL = "com.noted.app"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _mac_env_vars() -> str:
    # Secrets (ANTHROPIC_API_KEY, NOTED_API_TOKEN, ...) are deliberately NOT
    # embedded here in plaintext: cli/main.py loads .env from the repo root
    # via an absolute path (Path(__file__).parent.parent / ".env") on every
    # invocation, LaunchAgent included, so there's nothing to duplicate here
    # — and duplicating it would mean two places to keep in sync and two
    # places a secret can leak from.
    return """
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>"""


def install_mac(port: int) -> None:
    from db.paths import log_path
    log = log_path()
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{_noted_cmd()}</string>
        <string>web</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>{_mac_env_vars()}
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST.write_text(plist)
    subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST)], check=True)


def uninstall_mac() -> None:
    if LAUNCHD_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], capture_output=True)
        LAUNCHD_PLIST.unlink()


LAUNCHD_TRAY_LABEL = "com.noted.tray"
LAUNCHD_TRAY_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_TRAY_LABEL}.plist"


def install_mac_tray(ctx: str = "default", port: int = 7979) -> None:
    from db.paths import log_path
    log = log_path().parent / "tray.log"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_TRAY_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{_noted_cmd()}</string>
        <string>tray</string>
        <string>--ctx</string>
        <string>{ctx}</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>{_mac_env_vars()}
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""
    LAUNCHD_TRAY_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_TRAY_PLIST.write_text(plist)
    subprocess.run(["launchctl", "unload", str(LAUNCHD_TRAY_PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(LAUNCHD_TRAY_PLIST)], check=True)


def uninstall_mac_tray() -> None:
    if LAUNCHD_TRAY_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCHD_TRAY_PLIST)], capture_output=True)
        LAUNCHD_TRAY_PLIST.unlink()


def restart_mac_tray() -> None:
    if LAUNCHD_TRAY_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCHD_TRAY_PLIST)], capture_output=True)
        subprocess.run(["launchctl", "load", str(LAUNCHD_TRAY_PLIST)], check=True)


# ── Linux ──────────────────────────────────────────────────────────────────────

SYSTEMD_UNIT = Path.home() / ".config" / "systemd" / "user" / "noted.service"


def install_linux(port: int) -> None:
    from db.paths import log_path
    # Secrets are not embedded here — see the comment in _mac_env_vars().
    unit = f"""[Unit]
Description=noted — appunti giornalieri
After=network.target

[Service]
ExecStart={_noted_cmd()} web --host 0.0.0.0 --port {port}
Restart=on-failure
RestartSec=5
StandardOutput=append:{log_path()}
StandardError=append:{log_path()}

[Install]
WantedBy=default.target
"""
    SYSTEMD_UNIT.parent.mkdir(parents=True, exist_ok=True)
    SYSTEMD_UNIT.write_text(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "noted"], check=True)


def uninstall_linux() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", "noted"], capture_output=True)
    if SYSTEMD_UNIT.exists():
        SYSTEMD_UNIT.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


# ── Windows ───────────────────────────────────────────────────────────────────

TASK_NAME = "noted-app"


def install_windows(port: int) -> None:
    cmd = f'{_noted_cmd()} web --host 127.0.0.1 --port {port}'
    subprocess.run([
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/TR", cmd,
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
    ], check=True)
    # avvia subito
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True)


def uninstall_windows() -> None:
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True)


# ── hosts file ────────────────────────────────────────────────────────────────

def hosts_file() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\Windows\System32\drivers\etc\hosts")
    return Path("/etc/hosts")


def add_hosts_entry() -> bool:
    """Aggiunge 127.0.0.1 noted.local a /etc/hosts. Richiede privilegi elevati."""
    hf = hosts_file()
    try:
        content = hf.read_text()
        if HOST in content:
            return True
        entry = f"\n127.0.0.1 {HOST}\n"
        if sys.platform == "win32":
            with open(hf, "a") as f:
                f.write(entry)
        else:
            subprocess.run(
                ["sudo", "sh", "-c", f'echo "127.0.0.1 {HOST}" >> {hf}'],
                check=True,
            )
        return True
    except Exception:
        return False


def remove_hosts_entry() -> None:
    hf = hosts_file()
    try:
        lines = hf.read_text().splitlines(keepends=True)
        filtered = [l for l in lines if HOST not in l]
        if sys.platform == "win32":
            hf.write_text("".join(filtered))
        else:
            subprocess.run(
                ["sudo", "sh", "-c", f"cat > {hf}"],
                input="".join(filtered), text=True, check=True,
            )
    except Exception:
        pass
