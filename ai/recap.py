import os
from datetime import date
from typing import Optional, Iterator
from anthropic import Anthropic
from db.models import Note

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _model() -> str:
    from db.config import get_model
    return get_model()

DAILY_PROMPT = """Sei un assistente che aiuta un data engineer senior a fare il recap delle proprie note di lavoro.

Date delle note: {date}

Note della giornata:
{notes}

Ogni nota può avere un tag [status:X] esplicito con questi significati:
- [status:done]    → attività completata → va in ✅ Completato
- [status:wip]     → lavoro in corso     → va in 🔄 In corso
- [status:todo]    → da fare             → va in 📌 Next steps
- [status:blocked] → bloccata            → va in ⚠️ Blockers

Se una nota non ha [status:X], classifica in base al contenuto e al contesto.
Puoi anche avere tag [priority:high/low] e [due:YYYY-MM-DD] — usali per evidenziare urgenze.

Genera un recap strutturato in italiano con queste sezioni:
1. **✅ Completato** - cosa è stato fatto
2. **🔄 In corso** - attività ancora aperte
3. **⚠️ Blockers / Domande aperte** - problemi o decisioni pendenti
4. **📌 Next steps** - prossime azioni chiare

Regole:
- Sii conciso e diretto. Usa bullet point.
- Non inventare nulla che non sia nelle note.
- Se una sezione è vuota, omettila.
- Evidenzia con ⚠️ le note con scadenza imminente o priorità alta."""

WEEKLY_PROMPT = """Sei un assistente che aiuta un data engineer senior.

Ecco i recap degli ultimi giorni:
{recaps}

Genera un recap settimanale sintetico in italiano con:
1. **🎯 Obiettivi raggiunti questa settimana**
2. **🔄 Lavori ancora in corso**
3. **⚠️ Problemi aperti da settimana scorsa**
4. **📅 Priorità per la prossima settimana**

Massimo 15 bullet point totali."""


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


def stream_recap(notes: list[Note], target_date: Optional[date] = None) -> Iterator[str]:
    """Genera il recap in streaming, yielda chunk di testo."""
    if not notes:
        yield "Nessuna nota trovata per oggi."
        return

    target_date = target_date or date.today()
    prompt = DAILY_PROMPT.format(date=target_date.strftime('%d/%m/%Y'), notes=_format_notes(notes))

    with client.messages.stream(
        model=_model(),
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def generate_recap(notes: list[Note], target_date: Optional[date] = None) -> str:
    return "".join(stream_recap(notes, target_date))


def stream_weekly_recap(recaps_text: str) -> Iterator[str]:
    """Genera il recap settimanale in streaming."""
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
