from ai import llm


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


def _run(prompt: str) -> dict:
    data = llm.generate_json(prompt, num_predict=700)
    return {
        "subject": str(data.get("subject", "")).strip(),
        "body": str(data.get("body", "")).strip(),
    }


def generate_email_draft(content: str) -> dict:
    return _run(EMAIL_PROMPT.format(content=content))


def refine_email_draft(content: str, subject: str, body: str, instruction: str) -> dict:
    prompt = REFINE_PROMPT.format(content=content, subject=subject, body=body, instruction=instruction)
    return _run(prompt)
