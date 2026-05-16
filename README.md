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

### Tab Oggi — Input vocale

Accanto all'area testo è presente il bottone 🎙 per registrare una nota a voce:

1. Click → richiesta permesso microfono → registrazione avvia
2. Click **⏹ Ferma** → ascolto del registrato con player audio
3. Click **✦ Trascrivi** → trascrizione locale via [Whisper](https://github.com/openai/whisper) (nessun dato inviato al cloud)
4. Testo modificabile → **Usa come nota** → popola l'input e puoi completare con tag/progetto prima di inviare

> La trascrizione usa il modello `base` di Whisper in italiano. Al primo avvio scarica il modello (~140 MB).

### Tab Board

Kanban a 7 colonne: **Inbox** · **Backlog** · **Todo** · **WIP** · **Waiting** · **Blocked** · **Done**

- **Inbox** raccoglie le note senza stato degli ultimi 7 giorni (non si perdono tra i giorni)
- Click sullo stato per avanzarlo nel ciclo
- Filtri per progetto e assegnatario
- **Drag & drop** tra colonne e all'interno della stessa colonna (ordine persistito via `sort_order`)

### Tab Scadenze

Note con `due_date` impostata raggruppate in: ⚠️ Scadute · 🔴 Oggi · 🟡 Prossimi 7 giorni · 📆 Dopo

### Tab Gantt

Timeline visiva per pianificare progetti:

- **Progetti** con colore personalizzabile (10 palette predefinite)
- **Milestone** con date di inizio/fine — barre colorate sulla timeline; all'aggiunta viene creata automaticamente una nota con `tag=milestone`, `status=todo`, `due=end_date`
- **Note con scadenza** appaiono come ◆ sulla riga del progetto; tooltip con contenuto, data, assegnatario; click → vai alla nota
- **Progetti sfondo** (flag "Usa come sfondo") — visualizzati come bande colorate a tutta altezza (es. ferie, sprint, freeze)
- **Avvisi at-risk** 🔴 su milestone con `end_date ≤ oggi+7gg` e note in stato `blocked`, `waiting` o `backlog`
- **Zoom**: Giorno · Settimana · Mese · Auto (adattivo all'arco temporale)
- Linea verticale "oggi" sempre visibile

### Recap AI

- **🤖 Daily** — recap strutturato delle note di oggi; include le milestone Gantt attive per contestualizzare avanzamento e rischi di ritardo
- **📅 Weekly** — resume delle note degli ultimi 7 giorni con le milestone in corso
- Salvataggio automatico al termine di ogni generazione
- Lista "Ultimi recap" nella sidebar aggiornata dinamicamente dopo ogni generazione
- Click su un recap → caricato nella box senza ricaricare la pagina; orario visibile per distinguere più recap dello stesso giorno
- Selezione modello AI: ⚡ Haiku 4.5 · ✦ Sonnet 4.6 · ◆ Opus 4.7
- **⏰ Recap automatico** — schedulazione giornaliera o settimanale con orario e giorni della settimana configurabili dalla UI

### Gestione documenti

Ogni nota può avere uno o più file allegati. I file non vengono salvati nel database: vengono organizzati automaticamente sul filesystem in una cartella dedicata. Nel DB viene conservato solo il puntatore al percorso.

**Struttura cartelle:**

```
~/Documents/noted/           ← cartella root (configurabile)
  work/                      ← contesto
    ACME/                    ← progetto
      20260516_contratto.pdf
      20260518_specifica.docx
    _inbox/                  ← note senza progetto
      20260516_screenshot.png
  home/
    _inbox/
      20260516_ricetta.pdf
```

**Come allegare un file:**

- Dalla **tab Oggi**: pulsante 📎 nel form di aggiunta nota — seleziona uno o più file prima di inviare; vengono caricati automaticamente dopo la creazione della nota
- Su **note esistenti**: pulsante 📎 dashed che appare all'hover sulla card della nota

**Chip documento sulla card:**

- Click sul chip → apre il file nell'app di default (Anteprima, Word, ecc.)
- I chip mostrano icona tipo file + nome + dimensione
- Se il documento è già stato analizzato dall'AI, compare un indicatore 🔍 — il testo dell'analisi è visibile nel tooltip del chip

**Analisi AI documenti:**

Nella sidebar → pulsante **🔍 Analisi AI documenti**:

- Seleziona fino a 5 documenti dalla libreria del contesto attivo
- Scegli la **profondità di analisi**: Bassa (meno token) · Media · Alta (analisi approfondita)
- Aggiunge istruzioni personalizzate opzionali (es. "focalizzati sui rischi")
- L'AI restituisce: riepilogo, punti chiave, elementi suggeriti (note/todo e milestone)
- Gli elementi suggeriti si possono selezionare e creare direttamente in-app con un click
- Se viene analizzato un **singolo documento**, il riepilogo viene salvato automaticamente sul documento e mostrato come tooltip 🔍 sulla card della nota

**Nascondi task completati:**

Nel tab Oggi, pulsante **👁 done** nell'header della sezione note:
- Nasconde tutte le note con `status=done`
- Mostra un chip in fondo alla lista con il conteggio delle note nascoste (click per riaprirle)
- Lo stato viene ricordato in localStorage tra le sessioni

**Impostazioni cartella documenti:**

Nella sidebar (☰) → sezione **📁 Documenti**:
- Campo per configurare la cartella root (default: `~/Documents/noted`)
- Pulsante **📂 Apri cartella in Finder** per accedere direttamente ai file

### Backup e Ripristino

Il bottone `⬇` in alto a destra apre un menu con le opzioni di export e import.

**Esporta**

| Formato | Contenuto |
|---------|-----------|
| `SQLite (.db)` | Copia binaria del database completo — tutti i contesti, ripristinabile direttamente |
| `JSON (.json)` | Export leggibile di tutti i dati (note, recap, Gantt, contesti) — utile per migrazioni o analisi esterne |

I file vengono nominati `noted_backup_YYYY-MM-DD.db / .json`.

**Importa**

| Formato | Comportamento |
|---------|---------------|
| `SQLite (.db)` | Sostituisce il database corrente con il file caricato |
| `JSON (.json)` | Cancella tutti i dati esistenti e reinserisce quelli dal file |

⚠️ L'import è irreversibile — viene richiesta conferma esplicita prima di procedere. Si consiglia di eseguire un export prima di importare.

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
noted add "task su progetto secondario" --ctx home
```

| Opzione | Descrizione |
|---------|-------------|
| `--tag` / `-t` | Tag separati da virgola: `airflow,bigquery` |
| `--project` / `-p` | Progetto (salvato in UPPERCASE) |
| `--priority` / `-P` | `low` \| `medium` (default) \| `high` |
| `--due` / `-d` | Scadenza: `YYYY-MM-DD` |
| `--status` / `-s` | `backlog` \| `todo` \| `wip` \| `waiting` \| `blocked` \| `done` |
| `--assignee` / `-a` | Assegnatario |
| `--ctx` / `-c` | Contesto (default: `default`) |

```bash
noted list                          # ultime 20 note
noted list --tag airflow            # filtra per tag
noted list --project finops         # filtra per progetto
noted list --date 2026-01-15        # data specifica
noted list --status wip             # filtra per stato
noted list --assignee marco         # filtra per assegnatario
noted list --ctx work               # filtra per contesto

noted search "deploy"               # ricerca full-text

noted edit 42 "nuovo testo"
noted edit 42 --status done
noted edit 42 --due 2026-01-20
noted edit 42 --clear-due

noted delete 42
```

### Recap AI

```bash
noted recap                         # recap di oggi (contesto default)
noted recap --ctx work              # recap del contesto "work"
noted recap --date 2026-01-15       # recap di un giorno specifico
noted recap --weekly                # recap settimanale
noted recap --save                  # genera e salva nel DB
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
