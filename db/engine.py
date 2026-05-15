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
        ]
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                # Column already exists — ignore
                pass


def init_db():
    SQLModel.metadata.create_all(engine)
    _migrate()


def get_session() -> Session:
    return Session(engine)
