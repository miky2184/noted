#!/usr/bin/env python3
"""
noted — CLI per appunti giornalieri con recap AI

Uso rapido:
  noted add "standup: allineamento finops con Global ACN"
  noted add "problema DAG scheduler" --tag airflow --project deutsche-bank
  noted list
  noted list --today
  noted recap
  noted recap --save
  noted web
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import typer
from datetime import date, datetime
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint

from db.engine import init_db, get_session
from db import crud

app = typer.Typer(
    name="noted",
    help="📝 Appunti giornalieri con recap AI",
    no_args_is_help=True,
)
console = Console()


def _init():
    init_db()


# ── ADD ────────────────────────────────────────────────────────────────────────

PRIORITY_COLORS = {"high": "red", "medium": "yellow", "low": "green"}
STATUS_ICONS = {"backlog": "🗂", "todo": "⬜", "wip": "🔄", "waiting": "⏳", "blocked": "🚫", "done": "✅"}
STATUS_COLORS = {"backlog": "dim", "todo": "blue", "wip": "yellow", "waiting": "magenta", "blocked": "red", "done": "green"}

@app.command()
def add(
    content: str = typer.Argument(..., help="Testo della nota"),
    tag: str = typer.Option("", "--tag", "-t", help="Tag (comma-separated): 'airflow,bigquery'"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Progetto: 'finops', 'deutsche-bank'"),
    priority: str = typer.Option("medium", "--priority", "-P", help="Priorità: low | medium | high"),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Scadenza: YYYY-MM-DD"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Stato: backlog | todo | wip | waiting | blocked | done"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assegna a: 'mario' o '@mario'"),
):
    """Aggiungi una nota."""
    _init()
    due_date = None
    if due:
        try:
            due_date = date.fromisoformat(due)
        except ValueError:
            console.print("[red]Formato data non valido. Usa YYYY-MM-DD[/red]")
            raise typer.Exit(1)
    if priority not in ("low", "medium", "high"):
        console.print("[red]Priorità non valida. Usa: low | medium | high[/red]")
        raise typer.Exit(1)
    if status and status not in ("backlog", "todo", "wip", "waiting", "blocked", "done"):
        console.print("[red]Stato non valido. Usa: backlog | todo | wip | waiting | blocked | done[/red]")
        raise typer.Exit(1)
    # Strip leading @ from assignee if present
    if assignee:
        assignee = assignee.lstrip("@")
    with get_session() as session:
        note = crud.add_note(session, content=content, tags=tag, project=project, priority=priority, due_date=due_date, status=status, assignee=assignee)
    color = PRIORITY_COLORS[note.priority]
    proj_str = f" [{note.project}]" if note.project else ""
    tag_str = f" #{note.tags}" if note.tags else ""
    due_str = f" 📅 {note.due_date}" if note.due_date else ""
    status_str = f" {STATUS_ICONS.get(note.status, '')} {note.status}" if note.status else ""
    assignee_str = f" @{note.assignee}" if note.assignee else ""
    console.print(f"✅ [green]Nota #{note.id} salvata[/green]{proj_str}{tag_str} [{color}]{note.priority}[/{color}]{due_str}{status_str}{assignee_str}")


# ── LIST ───────────────────────────────────────────────────────────────────────

@app.command(name="list")
def list_notes(
    today: bool = typer.Option(False, "--today", help="Solo note di oggi"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filtra per tag"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filtra per progetto"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Filtra per assegnatario"),
    limit: int = typer.Option(20, "--limit", "-n", help="Numero massimo di note"),
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Data specifica: YYYY-MM-DD"),
):
    """Elenca le note."""
    _init()

    target_date = None
    if today:
        target_date = date.today()
    elif date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            console.print("[red]Formato data non valido. Usa YYYY-MM-DD[/red]")
            raise typer.Exit(1)

    with get_session() as session:
        notes = crud.get_notes(session, day=target_date, tag=tag, project=project, assignee=assignee, limit=limit)

    if not notes:
        console.print("[yellow]Nessuna nota trovata.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="dim", width=5)
    table.add_column("Data", width=11)
    table.add_column("Ora", width=6)
    table.add_column("Stato", width=8)
    table.add_column("P", width=3)
    table.add_column("Scadenza", width=11)
    table.add_column("Progetto", width=14)
    table.add_column("Nota")

    for n in notes:
        p_color = PRIORITY_COLORS.get(n.priority, "white")
        p_icon = {"high": "▲", "medium": "●", "low": "▼"}.get(n.priority, "●")
        due_str = str(n.due_date) if n.due_date else ""
        if n.due_date and n.due_date < date.today():
            due_str = f"[red]{due_str}[/red]"
        s_icon = STATUS_ICONS.get(n.status, "")
        s_color = STATUS_COLORS.get(n.status, "white")
        status_str = f"[{s_color}]{s_icon} {n.status}[/{s_color}]" if n.status else ""
        table.add_row(
            str(n.id),
            n.created_at.strftime("%d/%m/%Y"),
            n.created_at.strftime("%H:%M"),
            status_str,
            f"[{p_color}]{p_icon}[/{p_color}]",
            due_str,
            n.project or "",
            n.content,
        )

    date_label = target_date.strftime("%d/%m/%Y") if target_date else "tutte"
    console.print(f"\n📝 Note ({date_label}) — {len(notes)} risultati\n")
    console.print(table)


# ── DELETE ─────────────────────────────────────────────────────────────────────

@app.command()
def delete(
    note_id: int = typer.Argument(..., help="ID della nota da eliminare"),
):
    """Elimina una nota per ID."""
    _init()
    with get_session() as session:
        ok = crud.delete_note(session, note_id)
    if ok:
        console.print(f"🗑️  [green]Nota #{note_id} eliminata.[/green]")
    else:
        console.print(f"[red]Nota #{note_id} non trovata.[/red]")


# ── EDIT ───────────────────────────────────────────────────────────────────────

@app.command()
def edit(
    note_id: int = typer.Argument(..., help="ID della nota da modificare"),
    content: Optional[str] = typer.Argument(None, help="Nuovo testo della nota"),
    priority: Optional[str] = typer.Option(None, "--priority", "-P", help="Nuova priorità: low | medium | high"),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Nuova scadenza: YYYY-MM-DD"),
    clear_due: bool = typer.Option(False, "--clear-due", help="Rimuovi la scadenza"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Stato: backlog | todo | wip | waiting | blocked | done"),
    clear_status: bool = typer.Option(False, "--clear-status", help="Rimuovi lo stato"),
    assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Assegna a: 'mario' o '@mario'"),
):
    """Modifica una nota esistente."""
    _init()
    if priority and priority not in ("low", "medium", "high"):
        console.print("[red]Priorità non valida. Usa: low | medium | high[/red]")
        raise typer.Exit(1)
    if status and status not in ("backlog", "todo", "wip", "waiting", "blocked", "done"):
        console.print("[red]Stato non valido. Usa: backlog | todo | wip | waiting | blocked | done[/red]")
        raise typer.Exit(1)
    due_date = None
    if due:
        try:
            due_date = date.fromisoformat(due)
        except ValueError:
            console.print("[red]Formato data non valido. Usa YYYY-MM-DD[/red]")
            raise typer.Exit(1)
    if assignee:
        assignee = assignee.lstrip("@")
    with get_session() as session:
        note = crud.edit_note(session, note_id, content=content, priority=priority, due_date=due_date, clear_due=clear_due, status=status, clear_status=clear_status, assignee=assignee)
    if note:
        console.print(f"✏️  [green]Nota #{note_id} aggiornata.[/green]")
    else:
        console.print(f"[red]Nota #{note_id} non trovata.[/red]")


# ── SEARCH ──────────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(..., help="Testo da cercare nelle note"),
    limit: int = typer.Option(20, "--limit", "-n", help="Numero massimo di risultati"),
):
    """Cerca nelle note per testo."""
    _init()
    with get_session() as session:
        notes = crud.search_notes(session, query=query, limit=limit)

    if not notes:
        console.print(f"[yellow]Nessuna nota trovata per \"{query}\".[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="dim", width=5)
    table.add_column("Data", width=12)
    table.add_column("Ora", width=6)
    table.add_column("Progetto", width=14)
    table.add_column("Nota")

    for n in notes:
        # evidenzia la query nel testo
        highlighted = n.content.replace(query, f"[bold yellow]{query}[/bold yellow]")
        table.add_row(
            str(n.id),
            n.created_at.strftime("%d/%m/%Y"),
            n.created_at.strftime("%H:%M"),
            n.project or "",
            highlighted,
        )

    console.print(f"\n🔍 [bold]{len(notes)}[/bold] risultati per [yellow]\"{query}\"[/yellow]\n")
    console.print(table)


# ── RECAP ──────────────────────────────────────────────────────────────────────

@app.command()
def recap(
    save: bool = typer.Option(False, "--save", "-s", help="Salva il recap nel DB"),
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Data: YYYY-MM-DD (default: oggi)"),
    weekly: bool = typer.Option(False, "--weekly", "-w", help="Recap settimanale"),
):
    """Genera un recap AI delle note del giorno (o della settimana)."""
    _init()

    try:
        from ai.recap import stream_recap, stream_weekly_recap
    except ImportError:
        console.print("[red]anthropic non installato. Esegui: pip install anthropic[/red]")
        raise typer.Exit(1)

    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[red]ANTHROPIC_API_KEY non impostata. Aggiungila al file .env[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        if weekly:
            recaps = crud.get_recent_recaps(session, days=7)
            if not recaps:
                console.print("[yellow]Nessun recap salvato nell'ultima settimana.[/yellow]")
                return
            recaps_text = "\n\n".join(
                f"=== {r.recap_date.strftime('%d/%m/%Y')} ===\n{r.summary}" for r in recaps
            )
            console.print("[dim]🤖 Generazione recap settimanale...[/dim]\n")
            chunks = []
            for chunk in stream_weekly_recap(recaps_text):
                print(chunk, end="", flush=True)
                chunks.append(chunk)
            print()
            summary = "".join(chunks)
            return

        target_date = date.today()
        if date_str:
            try:
                target_date = date.fromisoformat(date_str)
            except ValueError:
                console.print("[red]Formato data non valido. Usa YYYY-MM-DD[/red]")
                raise typer.Exit(1)

        notes = crud.get_notes_for_recap(session, day=target_date)

        if not notes:
            console.print(f"[yellow]Nessuna nota per {target_date.strftime('%d/%m/%Y')}.[/yellow]")
            return

        console.print(f"[dim]🤖 Analisi di {len(notes)} note...[/dim]\n")
        chunks = []
        for chunk in stream_recap(notes, target_date):
            print(chunk, end="", flush=True)
            chunks.append(chunk)
        print()
        summary = "".join(chunks)

        if save:
            crud.save_recap(session, summary=summary, notes_count=len(notes), recap_date=target_date)
            console.print("\n💾 [green]Recap salvato nel DB.[/green]")
        else:
            console.print("\n[dim]Suggerimento: usa --save per salvare il recap[/dim]")


# ── DELETE-RECAP ───────────────────────────────────────────────────────────────

@app.command(name="delete-recap")
def delete_recap(
    recap_id: int = typer.Argument(..., help="ID del recap da eliminare"),
):
    """Elimina un recap per ID."""
    _init()
    with get_session() as session:
        ok = crud.delete_recap(session, recap_id)
    if ok:
        console.print(f"🗑️  [green]Recap #{recap_id} eliminato.[/green]")
    else:
        console.print(f"[red]Recap #{recap_id} non trovato.[/red]")


# ── WEB ────────────────────────────────────────────────────────────────────────

@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="Host"),
    port: Optional[int] = typer.Option(None, help="Porta (default: dalla config, 7979)"),
):
    """Avvia la dashboard web."""
    _init()
    from db.config import get_port
    if port is None:
        port = get_port()
    try:
        import uvicorn
        from web.app import app as web_app
        console.print(f"🌐 Dashboard su http://{host}:{port}")
        uvicorn.run(web_app, host=host, port=port)
    except ImportError:
        console.print("[red]fastapi/uvicorn non installati. Esegui: pip install fastapi uvicorn jinja2[/red]")
        raise typer.Exit(1)


# ── SET-MODEL ──────────────────────────────────────────────────────────────────

@app.command(name="set-model")
def set_model(
    model: str = typer.Argument(..., help="Modello: haiku | sonnet | opus"),
):
    """Imposta il modello AI usato per i recap."""
    from db.config import MODELS, set_model as _set, get_model
    if model not in MODELS:
        console.print(f"[red]Modello non valido. Scegli tra: {', '.join(MODELS)}[/red]")
        raise typer.Exit(1)
    _set(MODELS[model])
    console.print(f"✅ Modello impostato: [cyan]{model}[/cyan] ({MODELS[model]})")


@app.command(name="model")
def show_model():
    """Mostra il modello AI attualmente selezionato."""
    from db.config import get_model, MODELS
    current = get_model()
    label = next((k for k, v in MODELS.items() if v == current), current)
    console.print(f"🤖 Modello attivo: [cyan]{label}[/cyan] ({current})")


# ── INSTALL / UNINSTALL ────────────────────────────────────────────────────────

@app.command()
def install(
    port: Optional[int] = typer.Option(None, help="Porta del server (default: 7979)"),
    no_hosts: bool = typer.Option(False, "--no-hosts", help="Non modificare /etc/hosts"),
):
    """Installa noted come servizio di sistema (avvio automatico al boot)."""
    from db.config import get_port, set_port
    from cli.installer import (
        install_mac, install_linux, install_windows,
        add_hosts_entry, HOST, PORT,
    )
    import platform

    if port is None:
        port = get_port()
    else:
        set_port(port)

    system = sys.platform
    console.print(f"[cyan]Installazione noted su {platform.system()} (porta {port})...[/cyan]")

    try:
        if system == "darwin":
            install_mac(port)
            console.print("✅ [green]LaunchAgent installato — noted si avvierà ad ogni login.[/green]")
        elif system.startswith("linux"):
            install_linux(port)
            console.print("✅ [green]Servizio systemd installato — noted si avvierà ad ogni login.[/green]")
        elif system == "win32":
            install_windows(port)
            console.print("✅ [green]Task di Windows Task Scheduler installato — noted si avvierà ad ogni login.[/green]")
        else:
            console.print(f"[red]Piattaforma non supportata: {system}[/red]")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Errore durante l'installazione del servizio: {e}[/red]")
        raise typer.Exit(1)

    if not no_hosts:
        console.print(f"[dim]Aggiunta di {HOST} a /etc/hosts (potrebbe chiedere la password sudo)...[/dim]")
        ok = add_hosts_entry()
        if ok:
            console.print(f"✅ [green]Puoi raggiungere noted su http://{HOST}:{port}[/green]")
        else:
            console.print(f"[yellow]Non riuscito ad aggiungere {HOST} a /etc/hosts. Puoi farlo manualmente:[/yellow]")
            console.print(f"[dim]  echo '127.0.0.1 {HOST}' | sudo tee -a /etc/hosts[/dim]")
            console.print(f"[dim]  noted sarà comunque raggiungibile su http://127.0.0.1:{port}[/dim]")


@app.command()
def uninstall(
    keep_hosts: bool = typer.Option(False, "--keep-hosts", help="Non rimuovere la voce da /etc/hosts"),
):
    """Rimuove noted dal sistema (disabilita l'avvio automatico)."""
    from cli.installer import (
        uninstall_mac, uninstall_linux, uninstall_windows,
        remove_hosts_entry,
    )

    system = sys.platform
    try:
        if system == "darwin":
            uninstall_mac()
            console.print("✅ [green]LaunchAgent rimosso.[/green]")
        elif system.startswith("linux"):
            uninstall_linux()
            console.print("✅ [green]Servizio systemd rimosso.[/green]")
        elif system == "win32":
            uninstall_windows()
            console.print("✅ [green]Task di Windows Task Scheduler rimosso.[/green]")
        else:
            console.print(f"[red]Piattaforma non supportata: {system}[/red]")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Errore durante la rimozione: {e}[/red]")
        raise typer.Exit(1)

    if not keep_hosts:
        remove_hosts_entry()
        console.print("✅ [green]Voce rimossa da /etc/hosts.[/green]")

    console.print("[dim]I tuoi dati (note, DB, configurazione) non sono stati toccati.[/dim]")


# ── RESTART ────────────────────────────────────────────────────────────────────

def _restart_service() -> None:
    """Riavvia il servizio noted sulla piattaforma corrente."""
    import subprocess
    from cli.installer import LAUNCHD_PLIST, LAUNCHD_LABEL, SYSTEMD_UNIT, TASK_NAME

    system = sys.platform
    if system == "darwin":
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], capture_output=True)
        subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST)], check=True)
    elif system.startswith("linux"):
        subprocess.run(["systemctl", "--user", "restart", "noted"], check=True)
    elif system == "win32":
        subprocess.run(["schtasks", "/End", "/TN", TASK_NAME], capture_output=True)
        subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], check=True)
    else:
        raise RuntimeError(f"Piattaforma non supportata: {system}")


@app.command()
def restart():
    """Riavvia il servizio noted (dopo modifiche al codice o alla configurazione)."""
    try:
        _restart_service()
        console.print("✅ [green]noted riavviato.[/green]")
    except Exception as e:
        console.print(f"[red]Errore durante il riavvio: {e}[/red]")
        console.print("[dim]Hai eseguito 'noted install'?[/dim]")
        raise typer.Exit(1)


# ── UPGRADE ────────────────────────────────────────────────────────────────────

@app.command()
def upgrade(
    no_restart: bool = typer.Option(False, "--no-restart", help="Non riavviare il servizio dopo l'aggiornamento"),
):
    """Aggiorna noted: git pull + pip install + restart."""
    import subprocess

    project_root = Path(__file__).parent.parent.resolve()

    if not (project_root / ".git").exists():
        console.print("[red]La cartella del progetto non è un repository git.[/red]")
        console.print(f"[dim]Cartella rilevata: {project_root}[/dim]")
        raise typer.Exit(1)

    # 1. git pull
    console.print("[cyan]Scarico gli aggiornamenti...[/cyan]")
    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]git pull fallito:[/red]\n{result.stderr.strip()}")
        console.print("[dim]Controlla che non ci siano modifiche locali non committate (git status).[/dim]")
        raise typer.Exit(1)

    if "Already up to date" in result.stdout:
        console.print("[green]Già aggiornato — nessuna modifica da applicare.[/green]")
        return

    console.print(result.stdout.strip())

    # 2. reinstalla dipendenze se pyproject.toml è cambiato
    changed_files = result.stdout
    if "pyproject.toml" in changed_files:
        console.print("[cyan]pyproject.toml modificato — reinstallo le dipendenze...[/cyan]")
        pip_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
            cwd=project_root,
        )
        if pip_result.returncode != 0:
            console.print("[red]pip install fallito. Esegui manualmente: pip install -e .[/red]")
            raise typer.Exit(1)
        console.print("✅ [green]Dipendenze aggiornate.[/green]")

    # 3. restart
    if no_restart:
        console.print("[dim]Restart saltato (--no-restart). Riavvia manualmente con: noted restart[/dim]")
        return

    console.print("[cyan]Riavvio il servizio...[/cyan]")
    try:
        _restart_service()
        console.print("✅ [green]noted aggiornato e riavviato.[/green]")
    except Exception as e:
        console.print(f"[yellow]Aggiornamento applicato ma restart fallito: {e}[/yellow]")
        console.print("[dim]Riavvia manualmente con: noted restart[/dim]")


# ── INSTALL-CRON ───────────────────────────────────────────────────────────────

@app.command(name="install-cron")
def install_cron(
    time: str = typer.Option("17:30", help="Orario recap giornaliero (HH:MM)"),
):
    """Installa il cron job per il recap automatico."""
    import subprocess
    hour, minute = time.split(":")
    noted_path = Path(__file__).resolve()
    python_path = sys.executable
    cron_line = f"{minute} {hour} * * 1-5 {python_path} {noted_path} recap --save >> ~/.noted/recap.log 2>&1"

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    if "noted" in existing:
        console.print("[yellow]Cron job per noted già presente. Rimuovilo prima con: crontab -e[/yellow]")
        return

    new_crontab = existing.rstrip() + f"\n{cron_line}\n"
    subprocess.run(["crontab", "-"], input=new_crontab, text=True)
    console.print(f"⏰ [green]Cron installato: recap automatico ogni giorno lun-ven alle {time}[/green]")
    console.print(f"[dim]Log: ~/.noted/recap.log[/dim]")


if __name__ == "__main__":
    app()
