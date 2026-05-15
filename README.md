<p align="center">
  <img src="web/static/logo.png" width="96" alt="noted logo">
</p>

# noted

Note di lavoro giornaliere con recap AI, board kanban, Gantt e gestione contesti. Dashboard web locale, avvio automatico al boot.

---

## Requisiti

- Python 3.11+
- Una API key Anthropic (per i recap AI) → [console.anthropic.com](https://console.anthropic.com)

---

## Installazione

### 1. Clona il progetto

```bash
git clone <repo-url> noted
cd noted
```

### 2. Crea un ambiente virtuale e installa le dipendenze

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

### 3. Configura la API key

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

> Senza API key i recap AI non funzionano, ma tutto il resto (note, board, Gantt, scadenze) sì.

### 4. Installa come servizio (avvio automatico al boot)

```bash
noted install
```

Registra noted come **LaunchAgent** (macOS), **servizio systemd** (Linux) o **Task Scheduler** (Windows), aggiunge `noted.local` a `/etc/hosts` e lo avvia automaticamente ad ogni login su **http://noted.local:7979**.

```bash
noted uninstall         # rimuove il servizio (i dati restano intatti)
```

### 5. Avvio manuale

```bash
noted web               # http://127.0.0.1:7979
noted web --port 8080
```

---

## Dove vengono salvati i dati

| Piattaforma | Dati | Configurazione |
|-------------|------|----------------|
| macOS       | `~/Library/Application Support/noted/` | `~/Library/Preferences/noted/` |
| Linux       | `~/.local/share/noted/` | `~/.config/noted/` |
| Windows     | `%APPDATA%\noted\` | `%APPDATA%\noted\` |

Il database SQLite si chiama `notes.db`. Per usare una posizione personalizzata (es. cartella Dropbox o iCloud):

```bash
export DATABASE_URL="sqlite:////Users/me/iCloud Drive/noted/notes.db"
```

---

## Dashboard web

Apri **http://noted.local:7979** (o `http://127.0.0.1:7979`).

### Contesti

Ogni contesto è un database logico separato — note, recap e Gantt non si mescolano mai tra contesti diversi. Il selettore `📁 CONTEXT ▾` in alto a sinistra permette di:

- **Switchare** tra contesti con un click (es. `WORK`, `HOME`, `GYM`)
- **Creare** un nuovo contesto dal campo in fondo al menu
- **Rinominare** con l'icona ✎ (il rename si propaga su tutti i dati associati)
- **Impostare un preferito** con la ★ — l'app lo carica automaticamente all'apertura
- **Eliminare** con ✕ (richiede conferma, cancella tutti i dati del contesto)

### Tab Oggi

- Aggiunta rapida con `Enter` (a capo con `Shift+Enter`)
- Campi: `#tag`, progetto, `@persona`, scadenza, stato, priorità
- **Tag**: separati da `,` `|` `;` — normalizzati automaticamente in camelCase (`flusso acquiring` → `flussoAcquiring`)
- **Progetti**: sempre in UPPERCASE
- Modifica inline di contenuto, tag, progetto, assegnatario e scadenza direttamente sulla nota
- Navigazione tra giorni con le frecce `‹ ›`

### Tab Board

Kanban a 7 colonne: **Inbox** · **Backlog** · **Todo** · **WIP** · **Waiting** · **Blocked** · **Done**

- **Inbox** raccoglie le note senza stato degli ultimi 7 giorni (non si perdono tra i giorni)
- Click sullo stato per avanzarlo nel ciclo
- Filtri per progetto e assegnatario

### Tab Scadenze

Note con `due_date` impostata raggruppate in: ⚠️ Scadute · 🔴 Oggi · 🟡 Prossimi 7 giorni · 📆 Dopo

### Tab Gantt

Timeline visiva per pianificare progetti:

- **Progetti** con colore personalizzabile (10 palette predefinite)
- **Milestone** con date di inizio/fine — barre colorate sulla timeline
- **Note con scadenza** appaiono come ◆ rossi sulla riga del progetto corrispondente; il tooltip mostra contenuto, data e assegnatario; click → vai alla nota
- Zoom automatico: giornaliero / settimanale / mensile in base all'arco temporale
- Linea verticale "oggi" sempre visibile

### Recap AI

- **🤖 Daily** — recap strutturato delle note di oggi, tiene conto delle milestone Gantt attive per contestualizzare rischi e ritardi
- **📅 Weekly** — resume delle note degli ultimi 7 giorni con le milestone in corso
- Salvataggio automatico al termine della generazione
- Lista "Ultimi recap" nella sidebar: click su un recap per visualizzarlo, orario visibile per distinguere più recap dello stesso giorno
- Selezione modello AI: ⚡ Haiku 4.5 · ✦ Sonnet 4.6 · ◆ Opus 4.7

### Backup

Il bottone `⬇` in alto a destra offre due formati:

| Formato | Uso |
|---------|-----|
| `SQLite (.db)` | Backup completo ripristinabile — copia il file e sostituiscilo in caso di necessità |
| `JSON (.json)` | Export leggibile di tutti i dati (note, recap, Gantt, contesti) — utile per migrazioni o analisi esterne |

I file vengono nominati `noted_backup_YYYY-MM-DD.db / .json`.

### Scorciatoie da tastiera

| Tasto | Azione |
|-------|--------|
| `N` | Nuova nota (focus su input) |
| `1` | Tab Oggi |
| `2` | Tab Board |
| `3` | Tab Scadenze |
| `?` | Mostra scorciatoie |
| `Esc` | Chiudi / annulla modifica |
| `Enter` | Salva nota / conferma modifica |
| `Shift+Enter` | A capo nell'editor |

---

## Comandi CLI

### Note

```bash
noted add "standup: allineamento finops con Global ACN"
noted add "problema DAG scheduler" --tag airflow --project deutsche-bank
noted add "deploy entro venerdì" --due 2026-01-17 --priority high --status todo
noted add "review PR" --assignee marco
```

| Opzione | Descrizione |
|---------|-------------|
| `--tag` / `-t` | Tag separati da virgola: `airflow,bigquery` |
| `--project` / `-p` | Progetto (salvato in UPPERCASE) |
| `--priority` / `-P` | `low` \| `medium` (default) \| `high` |
| `--due` / `-d` | Scadenza: `YYYY-MM-DD` |
| `--status` / `-s` | `backlog` \| `todo` \| `wip` \| `waiting` \| `blocked` \| `done` |
| `--assignee` / `-a` | Assegnatario |

```bash
noted list                          # ultime 20 note di oggi
noted list --tag airflow            # filtra per tag
noted list --project finops         # filtra per progetto
noted list --date 2026-01-15        # data specifica
noted list --status wip             # filtra per stato
noted list --assignee marco         # filtra per assegnatario

noted search "deploy"               # ricerca full-text

noted edit 42 "nuovo testo"
noted edit 42 --status done
noted edit 42 --due 2026-01-20
noted edit 42 --clear-due

noted delete 42
```

### Recap AI

```bash
noted recap                         # recap di oggi
noted recap --date 2026-01-15       # recap di un giorno specifico
noted recap --weekly                # recap settimanale
noted delete-recap 7
```

### Modello AI

```bash
noted model                         # modello attivo
noted set-model haiku               # veloce ed economico
noted set-model sonnet              # bilanciato (default)
noted set-model opus                # più potente
```

### Servizio

```bash
noted install                       # avvio automatico + noted.local
noted install --port 8080
noted install --no-hosts            # non modifica /etc/hosts
noted uninstall
noted restart                       # riavvia dopo modifiche al codice
noted upgrade                       # git pull + pip install + restart
noted upgrade --no-restart
```

---

## Struttura del progetto

```
noted/
├── cli/
│   ├── main.py          # Typer CLI
│   └── installer.py     # install/uninstall (Mac/Linux/Windows)
├── db/
│   ├── models.py        # SQLModel — Note, Recap, GanttProject, Milestone, Context
│   ├── engine.py        # connessione DB + migration automatica
│   ├── crud.py          # operazioni CRUD (filtrate per context)
│   ├── config.py        # configurazione (modello AI, porta)
│   └── paths.py         # percorsi dati cross-platform (platformdirs)
├── ai/
│   └── recap.py         # Anthropic API streaming + integrazione dati Gantt
├── web/
│   ├── app.py           # FastAPI + tutti gli endpoint REST
│   └── templates/
│       └── index.html   # SPA Jinja2 — Oggi, Board, Scadenze, Gantt
└── pyproject.toml
```
