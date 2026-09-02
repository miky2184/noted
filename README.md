<p align="center">
  <img src="web/static/logo.png" width="96" alt="noted logo">
</p>

# noted

Note di lavoro giornaliere con recap AI, board kanban, Gantt e gestione contesti. Dashboard web locale, avvio automatico al boot.

---

## Requisiti

- Python 3.11+
- Una API key Anthropic (per i recap AI) → [console.anthropic.com](https://console.anthropic.com)
- **Opzionale:** [Ollama](https://ollama.com) per l'elaborazione AI locale delle note (auto-tagging, riscrittura)

---

## Installazione

### 1. Clona il progetto

```bash
git clone <repo-url> noted
cd noted
```

### 2. Installa il comando `noted` globalmente (consigliato)

Usa **pipx** per rendere `noted` disponibile da qualsiasi directory senza attivare il venv:

```bash
# Installa pipx (una tantum)
brew install pipx
pipx ensurepath
source ~/.zshrc      # oppure apri un nuovo terminale

# Installa noted in modalità editable — le modifiche al codice sono subito attive
pipx install -e ~/Documents/Workspace/noted --python python3

# Dipendenze opzionali
pipx inject noted rumps pynput   # menu bar app (macOS)
pipx inject noted pytest         # test
```

Dopo questa operazione `noted` funziona da qualsiasi directory:

```bash
noted web
noted tray-install
noted add "nota veloce"
```

#### Alternativa: venv manuale

Se preferisci non usare pipx:

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
pip install -e '.[tray]'       # opzionale: menu bar app
pip install -e '.[dev]'        # opzionale: test
```

Con il venv manuale il comando `noted` è disponibile solo dopo `source .venv/bin/activate`.

### 3. Configura la API key

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

> Senza API key i recap AI non funzionano, ma tutto il resto (note, board, Gantt, scadenze) sì.

### 4. (Opzionale) Installa Ollama per l'AI locale

Ollama permette di elaborare le note con un LLM locale senza inviare dati al cloud.

```bash
# macOS
brew install ollama

# oppure scarica l'installer da https://ollama.com/download
```

Scarica un modello e avvia il server:

```bash
# scarica un modello (una tantum):
ollama pull llama3.2          # ~2 GB — buon bilanciamento qualità/velocità
ollama pull llama3.2:1b       # ~800 MB — più leggero
ollama pull qwen2.5:3b        # ~2 GB — ottimo per output JSON strutturato

# avvio manuale (foreground):
ollama serve

# oppure come servizio in background (avvio automatico al login):
brew services start ollama    # macOS con Homebrew
brew services stop ollama     # ferma
brew services restart ollama  # riavvia
```

> Una volta avviato, il bottone 🦙 nel form di aggiunta nota diventa disponibile. URL e modello sono configurabili dalla sidebar → sezione **🦙 Ollama**.

### 5. Installa come servizio (avvio automatico al boot)

```bash
noted install
```

Registra noted come **LaunchAgent** (macOS), **servizio systemd** (Linux) o **Task Scheduler** (Windows), aggiunge `noted.local` a `/etc/hosts` e lo avvia automaticamente ad ogni login.

Dashboard:
- senza HTTPS locale: **http://noted.local:7979**
- dopo `noted setup-https`: **https://noted.local:7979**

```bash
noted uninstall         # rimuove il servizio (i dati restano intatti)
```

### 6. Avvio manuale

```bash
noted web               # http://127.0.0.1:7979
noted web --port 8080
```

---

## Token di accesso

`noted` è pensato per un solo utente ma può essere raggiunto da altri dispositivi
sulla stessa rete (es. il telefono, per l'input vocale). Per questo ogni chiamata
API richiede un token condiviso nell'header `X-Noted-Token` — senza non è
possibile leggere, modificare o esportare/ripristinare i dati tramite l'API.

Il token viene generato automaticamente al primo avvio e resta invariato tra i
riavvii (sovrascrivibile con la variabile d'ambiente `NOTED_API_TOKEN`).

```bash
noted token                # mostra il token attuale
noted token --regenerate   # ne genera uno nuovo (invalida i dispositivi già configurati)
```

Al primo accesso da un browser, `noted` chiede il token una sola volta e lo
salva in `localStorage`: le richieste successive lo includono automaticamente.
Per collegare un nuovo dispositivo, copia il token da **Impostazioni → 🔑 Accesso**
su un dispositivo già configurato (o da `noted token`) e incollalo quando richiesto.

> La pagina iniziale (`/`) resta raggiungibile senza token — solo le chiamate
> API sono protette. Se esponi noted oltre alla tua LAN personale, valuta
> comunque un livello di protezione aggiuntivo (VPN, reverse proxy con auth).

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

Lo schema del database è gestito con **Alembic**. All'avvio `noted` applica
automaticamente le migrazioni mancanti fino a `head`; per ispezionare o applicare
manualmente le migrazioni:

```bash
alembic current
alembic upgrade head
```

---

## Dashboard web

Apri **http://noted.local:7979** oppure **http://127.0.0.1:7979**.

Se hai eseguito `noted setup-https`, usa invece **https://noted.local:7979**.

### Struttura backend

La dashboard FastAPI è composta in `web/app.py`, mentre gli endpoint sono separati
per dominio in `web/routers/`:

- `contexts.py`, `notes.py`, `docs.py`, `gantt.py`, `recaps.py`, `backup.py`, `settings.py`, `voice.py`

La logica riusabile vive in `web/services/`, per esempio scheduler e gestione documenti.

### Contesti

Ogni contesto è un database logico separato — note, recap e Gantt non si mescolano mai tra contesti diversi. Il selettore `📁 CONTEXT ▾` in alto a sinistra permette di:

- **Switchare** tra contesti con un click (es. `WORK`, `HOME`, `GYM`)
- **Creare** un nuovo contesto dal campo in fondo al menu
- **Rinominare** con l'icona ✎ (il rename si propaga su tutti i dati associati)
- **Impostare un preferito** con la ★ — l'app lo carica automaticamente all'apertura
- **Eliminare** con ✕ (richiede conferma, cancella tutti i dati del contesto)

### Tab Oggi

- Aggiunta rapida con `Enter` (a capo con `Shift+Enter`)
- Campi: `#tag`, cliente, progetto, `@persona`, data inizio, scadenza, stato, priorità
- **Tag**: separati da `,` `|` `;` — normalizzati automaticamente in camelCase (`flusso acquiring` → `flussoAcquiring`)
- **Cliente** e **Progetto**: sempre in UPPERCASE. Il cliente è il collegamento con il Gantt (vedi sotto) — scrivendo una nota con cliente+progetto, il progetto compare automaticamente nel Gantt sotto quel cliente, senza nessun passaggio manuale
- Modifica inline di contenuto, tag, cliente, progetto, assegnatario, data inizio e scadenza direttamente sulla nota
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

Timeline visiva per pianificare progetti, organizzata sulla gerarchia **Cliente → Progetto → Stream → Fase → Nota**:

- **Clienti e Progetti si popolano da soli**: non si creano a mano nel Gantt. Scrivi una nota con i campi `cliente` + `progetto` (es. cliente `CREDEM`, progetto `FINOPS`) e — se il progetto non esiste ancora — viene creato automaticamente e collegato a quel cliente. I progetti si organizzano visivamente sotto l'header del cliente nella sidebar (progetti senza cliente restano in fondo, in "Senza cliente")
- **Progetti** con colore assegnato automaticamente (deducibile anche a mano dalla sidebar) — nella sidebar ogni progetto è **collassato di default** (solo pallino, nome, %): un click lo espande per gestire fasi/stream, un solo progetto aperto alla volta
- **Assenze** — sezione dedicata (collassabile) per registrare ferie/malattie tue o di collaboratori: nome persona + periodo, nessuna data obbligatoria oltre a quella; ogni persona ha una banda colorata distinta sulla timeline (indipendente da clienti/progetti), utile per vedere a colpo d'occhio chi non sarà disponibile rispetto alle scadenze
- **Stream** — un filone di lavoro dentro un progetto (es. "Collection"), puro contenitore organizzativo di Fasi
- **Fasi** (`Milestone`) — possono stare direttamente sul progetto o dentro uno Stream; le date sono **opzionali**: una fase è creabile subito senza date come contenitore di note, e comparirà come barra sulla timeline solo quando entrambe le date sono impostate. Ogni fase raccoglie N note (badge `🏁 fase#N` sulla card, click per collegare/scollegare) e ne calcola la % di completamento (note `done` / note totali). Progress aggregato: Fase → Stream → Progetto, visibile sia in sidebar sia sulla riga del progetto nel chart
- **Collegamento rapido**: nel form di creazione nota, il campo "fase" propone tutte le fasi esistenti con etichetta completa (`Progetto > [Stream >] Fase`) — niente bisogno di collegarla dopo
- **Note con scadenza** (senza fase) appaiono come ◆ sulla riga del progetto; tooltip con contenuto, data, assegnatario; click → vai alla nota
- **Progetti sfondo** (flag "Usa come sfondo") — visualizzati come bande colorate a tutta altezza (es. ferie, sprint, freeze); non hanno mai una sezione Stream, e la fase auto-creata alla scadenza non viene generata
- **Avvisi at-risk** 🔴 su fasi con `end_date ≤ oggi+7gg` e note in stato `blocked`, `waiting` o `backlog`
- **Zoom**: Giorno · Settimana · Mese · Auto (adattivo all'arco temporale)
- Linea verticale "oggi" sempre visibile

Eliminare un Cliente, un Progetto, uno Stream o una Fase non cancella mai le note collegate: vengono solo scollegate (il riferimento torna a "nessuno").

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

Prima di ripristinare un database SQLite, noted valida il file caricato, crea una copia
automatica del database corrente con suffisso `.pre_restore_YYYYMMDDHHMMSS`, poi esegue
lo swap del file e applica le migrazioni mancanti.

⚠️ L'import JSON cancella e reinserisce i dati esistenti — viene richiesta conferma esplicita prima di procedere.

### Menu bar app (macOS)

`noted tray` aggiunge una icona 📝 nella menu bar e una hotkey globale **⌃⌥N** (Ctrl+Option+N) per inserire note anche quando sei su un'altra app.

#### Installazione

```bash
pip install -e '.[tray]'         # rumps + pynput + PyObjC/Cocoa (una tantum)

# avvio manuale (foreground, utile per debug)
noted tray                       # contesto: default
noted tray --ctx work

# avvio automatico al login (LaunchAgent)
noted tray-install               # installa e avvia
noted tray-install --ctx work    # con contesto specifico
noted tray-uninstall             # rimuove
noted restart                    # riavvia sia il server che il tray
```

Al primo avvio macOS chiederà di concedere i permessi **Accessibilità** (necessari per la hotkey globale). Vai in **Impostazioni di Sistema → Privacy e Sicurezza → Accessibilità** e aggiungi il tuo Terminale o app Python.

**Funzionamento:**

- Click sull'icona 📝 → menu con "Aggiungi nota…" e "Apri dashboard"
- **⌃⌥N** (Ctrl+Option+N) da qualsiasi app → finestra di inserimento nota
- La nota viene salvata direttamente via API REST su noted in esecuzione (`noted web` deve essere attivo)
- Notifica di conferma al salvataggio

> Per avviare il tray automaticamente al login, puoi aggiungerlo agli **Elementi login** in Impostazioni di Sistema, oppure creare un LaunchAgent separato.

---

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
| `--cliente` | Cliente (salvato in UPPERCASE) — se combinato con `--project` crea/collega automaticamente il progetto nel Gantt |
| `--project` / `-p` | Progetto (salvato in UPPERCASE) |
| `--priority` / `-P` | `low` \| `medium` (default) \| `high` |
| `--start` | Data inizio: `YYYY-MM-DD` |
| `--due` / `-d` | Scadenza: `YYYY-MM-DD` |
| `--status` / `-s` | `backlog` \| `todo` \| `discuss` \| `wip` \| `waiting` \| `blocked` \| `done` |
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
noted search "fattura acme" --ctx work

noted edit 42 "nuovo testo"
noted edit 42 --status done
noted edit 42 --due 2026-01-20
noted edit 42 --clear-due

noted delete 42
```

La ricerca usa SQLite FTS5 quando disponibile: cerca per termini indicizzati in contenuto, tag,
progetto e assegnatario, ordina per pertinenza e supporta prefissi di parola.

Esempio pratico:

```bash
noted add "review contratto Acme per fatturazione finale" --project ACME --ctx work
noted search "fattura acme" --ctx work
```

Prima, con `LIKE '%fattura acme%'`, questa nota poteva non uscire perché la frase esatta
non appare nel testo. Ora viene trovata perché `fattura` corrisponde al prefisso di
`fatturazione` e `acme` viene cercato anche nel progetto.

### Recap AI

```bash
noted recap                         # recap di oggi (contesto default)
noted recap --ctx work              # recap del contesto "work"
noted recap --date 2026-01-15       # recap di un giorno specifico
noted recap --weekly                # recap settimanale
noted recap --save                  # genera e salva nel DB
noted delete-recap 7
```

## Test

```bash
pytest
```

I test usano database SQLite e cartelle documenti temporanee, quindi non toccano i dati locali.
Coprono API principali, ricerca full-text, isolamento contesti, documenti, backup/restore e recap AI con mock.

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
noted tray                          # menu bar app macOS con ⌃⌥N (richiede: pip install 'noted[tray]')
noted tray --ctx work
```

---

## Struttura del progetto

```
noted/
├── cli/
│   ├── main.py          # Typer CLI
│   └── installer.py     # install/uninstall (Mac/Linux/Windows)
├── db/
│   ├── models.py        # SQLModel — Note, Recap, Client, GanttProject, Stream, Milestone, Absence, Context
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
