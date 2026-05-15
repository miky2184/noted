from sqlmodel import SQLModel, create_engine, Session
import os

def _default_db_url() -> str:
    from db.paths import db_path
    return f"sqlite:///{db_path()}"

DATABASE_URL = os.getenv("DATABASE_URL") or _default_db_url()

engine = create_engine(DATABASE_URL, echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
