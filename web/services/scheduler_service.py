import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from db import crud
from db.engine import get_session
from web.services.recap_service import generate_scheduled_recap


logging.basicConfig(
    filename=Path("~/.noted/scheduler.log").expanduser(),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger("noted.scheduler")


def _do_scheduled_recap():
    """Generate today's recap for every context that has notes and no recap yet."""
    from db.config import get_schedule, set_scheduler_status
    schedule = get_schedule()
    recap_type = schedule.get("type", "daily") if schedule else "daily"
    _log.info("Scheduler avviato (type=%s)", recap_type)

    with get_session() as session:
        contexts = crud.get_contexts(session)

    for ctx_obj in contexts:
        ctx = ctx_obj.name
        try:
            saved, notes_count = generate_scheduled_recap(ctx, recap_type)
            if saved:
                _log.info("ctx=%s: recap salvato (%d note)", ctx, notes_count)
            else:
                _log.info("ctx=%s: nessun recap da generare, skip", ctx)
        except Exception as exc:
            _log.error("ctx=%s: errore — %s", ctx, exc)
            set_scheduler_status(ok=False, error=str(exc))
            return

    set_scheduler_status(ok=True)


async def _scheduler_loop():
    from db.config import get_schedule
    schedule = get_schedule()
    if schedule:
        now = datetime.now()
        h, m = map(int, schedule["time"].split(":"))
        if now.weekday() in schedule["days"] and (now.hour > h or (now.hour == h and now.minute >= m)):
            await asyncio.get_event_loop().run_in_executor(None, _do_scheduled_recap)

    while True:
        await asyncio.sleep(60 - datetime.now().second)
        schedule = get_schedule()
        if not schedule:
            continue
        now = datetime.now()
        h, m = map(int, schedule["time"].split(":"))
        if now.weekday() in schedule["days"] and now.hour == h and now.minute == m:
            await asyncio.get_event_loop().run_in_executor(None, _do_scheduled_recap)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
