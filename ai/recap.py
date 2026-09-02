import os
from datetime import date, timedelta
from typing import Optional, Iterator
from anthropic import Anthropic
from db.models import Note

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _model() -> str:
    from db.config import get_model
    return get_model()


def _format_notes(notes: list[Note]) -> str:
    return "\n".join(
        f"[{n.created_at.strftime('%H:%M')}]"
        f"{f' [status:{n.status}]' if n.status else ''}"
        f"{f' [priority:{n.priority}]' if n.priority != 'medium' else ''}"
        f"{f' [due:{n.due_date}]' if n.due_date else ''}"
        f"{f' [{n.project}]' if n.project else ''}"
        f"{f' #{n.tags}' if n.tags else ''}"
        f" {n.content}"
        for n in notes
    )


def _format_gantt(gantt: dict | None, today: date) -> str:
    """Serializza i dati Gantt in testo leggibile dal modello.
    Include solo gli Stream datati non ancora conclusi (end_date >= oggi - 7gg).
    """
    if not gantt or not gantt.get("projects"):
        return ""
    cutoff = (today - timedelta(days=7)).isoformat()
    lines = []
    for p in gantt["projects"]:
        active = [s for s in p["streams"] if s["end_date"] and s["end_date"] >= cutoff]
        if not active:
            continue
        for s in active:
            lines.append(f"- [{p['name']}] {s['name']}: {s['start_date']} → {s['end_date']}")
    if not lines:
        return ""
    return "\n## Stream Gantt attivi\n" + "\n".join(lines)


DAILY_PROMPT = """Sei un assistente che aiuta un professionista IT a fare il recap delle proprie note di lavoro.

Date delle note: {date}

Note della giornata:
{notes}{gantt}

Ogni nota può avere un tag [status:X] esplicito con questi significati:
- [status:done]    → attività completata → va in ✅ Completato
- [status:wip]     → lavoro in corso     → va in 🔄 In corso
- [status:todo]    → da fare             → va in 📌 Next steps
- [status:blocked] → bloccata            → va in ⚠️ Blockers

Se una nota non ha [status:X], classifica in base al contenuto e al contesto.
Puoi anche avere tag [priority:high/low] e [due:YYYY-MM-DD] — usali per evidenziare urgenze.
Se sono presenti milestone Gantt, usale come contesto per valutare avanzamento e rischi di ritardo.

Genera un recap strutturato in italiano con queste sezioni:
1. **✅ Completato** - cosa è stato fatto
2. **🔄 In corso** - attività ancora aperte
3. **⚠️ Blockers / Domande aperte** - problemi o decisioni pendenti
4. **📌 Next steps** - prossime azioni chiare

Regole:
- Sii conciso e diretto. Usa bullet point.
- Non inventare nulla che non sia nelle note.
- Se una sezione è vuota, omettila.
- Evidenzia con ⚠️ le note con scadenza imminente o priorità alta.
- Se una milestone è a rischio (attività bloccate o in ritardo sullo stesso progetto), segnalalo."""

WEEKLY_NOTES_PROMPT = """Sei un assistente che aiuta un professionista IT a fare il recap settimanale.

Ecco le note di lavoro degli ultimi 7 giorni, raggruppate per data:
{notes}{gantt}

Genera un recap settimanale strutturato in italiano con:
1. **🎯 Completato questa settimana**
2. **🔄 Ancora in corso**
3. **⚠️ Blockers e attese**
4. **📅 Priorità per la prossima settimana**

Sii conciso, usa bullet point. Non inventare nulla che non sia nelle note.
Se sono presenti milestone Gantt, valuta l'avanzamento rispetto alle scadenze e segnala eventuali rischi."""

WEEKLY_PROMPT = """Sei un assistente che aiuta un data engineer senior.

Ecco i recap degli ultimi giorni:
{recaps}

Genera un recap settimanale sintetico in italiano con:
1. **🎯 Obiettivi raggiunti questa settimana**
2. **🔄 Lavori ancora in corso**
3. **⚠️ Problemi aperti da settimana scorsa**
4. **📅 Priorità per la prossima settimana**

Massimo 15 bullet point totali."""


def stream_recap(notes: list[Note], target_date: Optional[date] = None,
                 gantt: dict | None = None) -> Iterator[str]:
    if not notes:
        yield "Nessuna nota trovata per oggi."
        return

    target_date = target_date or date.today()
    gantt_text = _format_gantt(gantt, target_date)
    prompt = DAILY_PROMPT.format(
        date=target_date.strftime('%d/%m/%Y'),
        notes=_format_notes(notes),
        gantt=gantt_text,
    )

    with client.messages.stream(
        model=_model(),
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def generate_recap(notes: list[Note], target_date: Optional[date] = None,
                   gantt: dict | None = None) -> str:
    return "".join(stream_recap(notes, target_date, gantt))


def stream_weekly_recap(recaps_text: str) -> Iterator[str]:
    prompt = WEEKLY_PROMPT.format(recaps=recaps_text)
    with client.messages.stream(
        model=_model(),
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def generate_weekly_recap(recaps_text: str) -> str:
    return "".join(stream_weekly_recap(recaps_text))


def generate_weekly_from_notes_sync(notes: list[Note], gantt: dict | None = None) -> str:
    return "".join(stream_weekly_from_notes(notes, gantt=gantt))


def stream_weekly_from_notes(notes: list[Note],
                              gantt: dict | None = None) -> Iterator[str]:
    from collections import defaultdict
    by_day: dict[str, list[Note]] = defaultdict(list)
    for n in notes:
        by_day[n.created_at.strftime('%d/%m/%Y')].append(n)

    notes_text = ""
    for day in sorted(by_day.keys()):
        notes_text += f"\n### {day}\n" + _format_notes(by_day[day]) + "\n"

    gantt_text = _format_gantt(gantt, date.today())
    prompt = WEEKLY_NOTES_PROMPT.format(notes=notes_text.strip(), gantt=gantt_text)

    with client.messages.stream(
        model=_model(),
        max_tokens=1400,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text
