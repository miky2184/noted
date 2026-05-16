from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
import os

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


def _migrate():
    """Safely add new columns to existing SQLite tables without dropping data."""
    from sqlalchemy import text
    with engine.connect() as conn:
        migrations = [
            "ALTER TABLE note ADD COLUMN assignee VARCHAR",
            "ALTER TABLE note ADD COLUMN context VARCHAR DEFAULT 'default'",
            "ALTER TABLE recap ADD COLUMN context VARCHAR DEFAULT 'default'",
            "ALTER TABLE ganttproject ADD COLUMN context VARCHAR DEFAULT 'default'",
            "ALTER TABLE note ADD COLUMN sort_order INTEGER DEFAULT 0",
            "ALTER TABLE ganttproject ADD COLUMN is_background BOOLEAN DEFAULT 0",
            """CREATE TABLE IF NOT EXISTS notedependency (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL REFERENCES note(id),
                blocker_id INTEGER NOT NULL REFERENCES note(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(note_id, blocker_id)
            )""",
            """CREATE TABLE IF NOT EXISTS document (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER REFERENCES note(id) ON DELETE SET NULL,
                rel_path TEXT NOT NULL,
                orig_name TEXT NOT NULL,
                mime_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass


def _seed_default_context():
    from sqlmodel import Session, select
    from db.models import Context
    with Session(engine) as session:
        if not session.exec(select(Context)).first():
            session.add(Context(name="default"))
            session.commit()


def init_db():
    SQLModel.metadata.create_all(engine)
    _migrate()
    _seed_default_context()


def get_session() -> Session:
    return Session(engine)
