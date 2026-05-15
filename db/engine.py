from sqlmodel import SQLModel, create_engine, Session
import os

def _default_db_url() -> str:
    from db.paths import db_path
    return f"sqlite:///{db_path()}"

DATABASE_URL = os.getenv("DATABASE_URL") or _default_db_url()

engine = create_engine(DATABASE_URL, echo=False)


def _migrate():
    """Safely add new columns to existing SQLite tables without dropping data."""
    from sqlalchemy import text
    with engine.connect() as conn:
        migrations = [
            "ALTER TABLE note ADD COLUMN assignee VARCHAR",
            "ALTER TABLE note ADD COLUMN context VARCHAR DEFAULT 'default'",
            "ALTER TABLE recap ADD COLUMN context VARCHAR DEFAULT 'default'",
            "ALTER TABLE ganttproject ADD COLUMN context VARCHAR DEFAULT 'default'",
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
