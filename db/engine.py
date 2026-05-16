from pathlib import Path
import os

from sqlalchemy import event
from sqlmodel import Session, create_engine


def _default_db_url() -> str:
    from db.paths import db_path
    return f"sqlite:///{db_path()}"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_db_url()

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")       # write-ahead log: no lock contention
    cur.execute("PRAGMA synchronous=NORMAL")     # flush at checkpoint, not every write
    cur.execute("PRAGMA cache_size=-8000")       # 8 MB page cache
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.close()


def _run_migrations() -> None:
    """Apply Alembic migrations to the configured database."""
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:
        raise RuntimeError(
            "Alembic non installato. Esegui: pip install -e ."
        ) from exc

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    cfg.attributes["connection"] = engine
    command.upgrade(cfg, "head")


def _seed_default_context():
    from sqlmodel import Session, select
    from db.models import Context

    with Session(engine) as session:
        if not session.exec(select(Context)).first():
            session.add(Context(name="default"))
            session.commit()


def init_db():
    _run_migrations()
    _seed_default_context()


def get_session() -> Session:
    return Session(engine)
