from collections.abc import Iterator
from datetime import date
import os

from db import crud
from db.engine import get_session


class RecapError(Exception):
    status_code = 500


class MissingApiKeyError(RecapError):
    status_code = 400


class NoNotesError(RecapError):
    status_code = 404


def ensure_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise MissingApiKeyError("ANTHROPIC_API_KEY non impostata")


def stream_daily_recap(ctx: str) -> Iterator[str]:
    ensure_api_key()

    with get_session() as session:
        notes = crud.get_notes_for_recap(session, day=date.today(), ctx=ctx)
        gantt = crud.get_gantt_data(session, ctx=ctx)

    if not notes:
        raise NoNotesError("Nessuna nota per oggi")

    from ai.recap import stream_recap

    def generate() -> Iterator[str]:
        chunks: list[str] = []
        for chunk in stream_recap(notes, date.today(), gantt=gantt):
            chunks.append(chunk)
            yield chunk

        with get_session() as session:
            crud.save_recap(
                session,
                summary="".join(chunks),
                notes_count=len(notes),
                recap_date=date.today(),
                ctx=ctx,
            )

    return generate()


def stream_weekly_recap(ctx: str) -> Iterator[str]:
    ensure_api_key()

    with get_session() as session:
        notes = crud.get_notes_last_n_days(session, days=7, ctx=ctx)
        gantt = crud.get_gantt_data(session, ctx=ctx)

    if not notes:
        raise NoNotesError("Nessuna nota negli ultimi 7 giorni")

    from ai.recap import stream_weekly_from_notes

    def generate() -> Iterator[str]:
        chunks: list[str] = []
        for chunk in stream_weekly_from_notes(notes, gantt=gantt):
            chunks.append(chunk)
            yield chunk

        with get_session() as session:
            crud.save_recap(
                session,
                summary="".join(chunks),
                notes_count=len(notes),
                recap_date=date.today(),
                ctx=ctx,
            )

    return generate()


def generate_scheduled_recap(ctx: str, recap_type: str) -> tuple[bool, int]:
    with get_session() as session:
        if crud.get_recap(session, day=date.today(), ctx=ctx):
            return False, 0
        gantt = crud.get_gantt_data(session, ctx=ctx)
        if recap_type == "weekly":
            notes = crud.get_notes_last_n_days(session, days=7, ctx=ctx)
        else:
            notes = crud.get_notes_for_recap(session, day=date.today(), ctx=ctx)
        if not notes:
            return False, 0

    if recap_type == "weekly":
        from ai.recap import generate_weekly_from_notes_sync

        summary = generate_weekly_from_notes_sync(notes, gantt=gantt)
    else:
        from ai.recap import generate_recap

        summary = generate_recap(notes, date.today(), gantt=gantt)

    with get_session() as session:
        crud.save_recap(
            session,
            summary=summary,
            notes_count=len(notes),
            recap_date=date.today(),
            ctx=ctx,
        )
    return True, len(notes)
