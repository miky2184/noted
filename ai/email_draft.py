import json
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _model() -> str:
    from db.config import get_model
    return get_model()


EMAIL_PROMPT = """Sei un assistente che aiuta un professionista IT a scrivere email di lavoro in italiano, partendo da una nota/attività scritta velocemente durante la giornata.

Nota:
{content}

Scrivi una bozza di email pronta per l'invio: oggetto sintetico e corpo con saluto iniziale, contenuto chiaro e diretto, chiusura professionale. Non inventare nomi di destinatari se non sono già indicati nella nota — in quel caso usa un saluto generico ("Ciao," / "Buongiorno,").

Rispondi SOLO con un oggetto JSON valido, nessun altro testo, in questo formato esatto:
{{"subject": "...", "body": "..."}}"""


REFINE_PROMPT = """Hai già scritto questa bozza di email per un professionista IT, a partire dalla nota originale sottostante.

Nota originale:
{content}

Bozza attuale:
Oggetto: {subject}
Corpo:
{body}

L'utente chiede questa modifica: {instruction}

Riscrivi la bozza applicando la richiesta, mantenendo tono professionale e la lingua italiana (a meno che la richiesta non dica altrimenti).

Rispondi SOLO con un oggetto JSON valido, nessun altro testo, in questo formato esatto:
{{"subject": "...", "body": "..."}}"""


def _strip_code_fence(raw: str) -> str:
    """I modelli a volte avvolgono il JSON in un blocco di codice markdown
    nonostante le istruzioni — lo togliamo prima di parsare."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def _stream_json(prompt: str, max_tokens: int) -> dict:
    with client.messages.stream(
        model=_model(),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        raw = "".join(stream.text_stream)
    data = json.loads(_strip_code_fence(raw))
    if not isinstance(data, dict):
        raise ValueError("La risposta AI non è un oggetto JSON")
    return {
        "subject": str(data.get("subject", "")).strip(),
        "body": str(data.get("body", "")).strip(),
    }


def generate_email_draft(content: str) -> dict:
    return _stream_json(EMAIL_PROMPT.format(content=content), max_tokens=700)


def refine_email_draft(content: str, subject: str, body: str, instruction: str) -> dict:
    prompt = REFINE_PROMPT.format(content=content, subject=subject, body=body, instruction=instruction)
    return _stream_json(prompt, max_tokens=700)
