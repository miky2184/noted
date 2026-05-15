# noted 📝

Appunti giornalieri con recap AI. Dashboard web locale, avvio automatico al boot, accessibile da browser come `noted.local`.

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

Crea un file `.env` nella root del progetto:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

> La API key viene letta automaticamente all'avvio. Senza di essa i comandi `recap` e la generazione del recap da web non funzionano, ma tutto il resto (note, lista, dashboard) sì.

### 4. Installa come servizio (avvio automatico al boot)

```bash
noted install
```

Questo comando:
- Registra noted come **LaunchAgent** (macOS), **servizio systemd** (Linux) o **Task Scheduler** (Windows)
- Aggiunge `noted.local` a `/etc/hosts` (potrebbe chiedere la password sudo su Mac/Linux)
- Da quel momento, noted si avvia automaticamente ad ogni login e risponde su **http://noted.local:7979**

Per disinstallare:

```bash
noted uninstall
```

> I tuoi dati (note, DB, configurazione) non vengono mai cancellati.

### 5. Avvio manuale (senza installazione)

```bash
noted web           # http://127.0.0.1:7979
noted web --port 8080
```

---

## Dove vengono salvati i dati

I dati vengono salvati in cartelle sicure e specifiche per piattaforma, al riparo da cancellazioni accidentali:

| Piattaforma | Cartella dati | Configurazione |
|-------------|---------------|----------------|
| macOS       | `~/Library/Application Support/noted/` | `~/Library/Preferences/noted/` |
| Linux       | `~/.local/share/noted/` | `~/.config/noted/` |
| Windows     | `%APPDATA%\noted\` | `%APPDATA%\noted\` |

Il database SQLite si chiama `notes.db`, la configurazione `config.json`, il log `noted.log`.

---

## Comandi CLI

### Note

```bash
noted add "standup: allineamento finops con Global ACN"
noted add "problema DAG scheduler" --tag airflow --project deutsche-bank
noted add "deploy entro venerdì" --due 2025-01-17 --priority high --status todo
```

| Opzione | Descrizione |
|---------|-------------|
| `--tag` / `-t` | Tag (comma-separated): `airflow,bigquery` |
| `--project` / `-p` | Progetto: `finops`, `deutsche-bank` |
| `--priority` / `-P` | `low` \| `medium` (default) \| `high` |
| `--due` / `-d` | Scadenza: `YYYY-MM-DD` |
| `--status` / `-s` | `todo` \| `wip` \| `done` \| `blocked` |

```bash
noted list                          # ultime 20 note
noted list --today                  # solo oggi
noted list --tag airflow            # filtra per tag (case-insensitive)
noted list --project finops         # filtra per progetto
noted list --date 2025-01-15        # data specifica

noted search "deploy"               # ricerca full-text (case-insensitive)

noted edit 42 "nuovo testo"
noted edit 42 --status done
noted edit 42 --due 2025-01-20
noted edit 42 --clear-due           # rimuove la scadenza

noted delete 42
```

### Recap AI

```bash
noted recap                         # recap di oggi (non salvato)
noted recap --save                  # genera e salva nel DB
noted recap --date 2025-01-15       # recap di un giorno specifico
noted recap --weekly                # recap settimanale dai recap salvati
noted delete-recap 7                # elimina un recap per ID
```

### Modello AI

```bash
noted model                         # mostra il modello attivo
noted set-model haiku               # più veloce ed economico
noted set-model sonnet              # bilanciato (default)
noted set-model opus                # più potente
```

### Servizio

```bash
noted install                       # installa avvio automatico + noted.local
noted install --port 8080           # usa una porta diversa
noted install --no-hosts            # non modifica /etc/hosts
noted uninstall                     # rimuove il servizio
noted uninstall --keep-hosts        # rimuove il servizio ma lascia /etc/hosts
noted restart                       # riavvia il servizio (dopo modifiche al codice)
noted upgrade                       # git pull + pip install + restart automatico
noted upgrade --no-restart          # aggiorna il codice senza riavviare subito
```

### Recap automatico via cron (opzionale)

```bash
noted install-cron                  # recap ogni giorno lun-ven alle 17:30
noted install-cron --time 18:00     # orario personalizzato
```

---

## Dashboard web

Apri il browser su **http://noted.local:7979** (o `http://127.0.0.1:7979` se non hai configurato `/etc/hosts`).

Dalla dashboard puoi:
- Aggiungere, modificare ed eliminare note inline
- Impostare priorità, stato e scadenza su ogni nota
- Visualizzare le **Scadenze** aperte in una tab dedicata
- Generare il recap AI e salvarlo con un click
- Scegliere il modello AI (Haiku / Sonnet / Opus) dalla sidebar
- Alternare tra tema chiaro e scuro

---

## Struttura del progetto

```
noted/
├── cli/
│   ├── main.py          # Typer CLI
│   └── installer.py     # logica install/uninstall (Mac/Linux/Windows)
├── db/
│   ├── models.py        # SQLModel — Note, Recap
│   ├── engine.py        # connessione DB
│   ├── crud.py          # operazioni CRUD
│   ├── config.py        # configurazione (modello, porta)
│   └── paths.py         # percorsi dati cross-platform (platformdirs)
├── ai/
│   └── recap.py         # chiamate Anthropic API con streaming
├── web/
│   ├── app.py           # FastAPI + route API
│   └── templates/
│       └── index.html   # dashboard Jinja2
└── pyproject.toml
```
