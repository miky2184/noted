from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field, JSON, Column
import json


PRIORITIES = ("low", "medium", "high")
STATUSES = ("backlog", "todo", "discuss", "wip", "waiting", "blocked", "done")

class Context(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    created_at: datetime = Field(default_factory=datetime.now)


class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    tags: str = Field(default="")
    cliente: Optional[str] = Field(default=None, index=True)
    project: Optional[str] = None
    priority: str = Field(default="medium")
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[str] = Field(default=None, index=True)
    assignee: Optional[str] = None
    context: str = Field(default="default", index=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now)
    # Nome legacy: la tabella/concetto "Milestone" è stata rinominata "Stream" (v. Stream),
    # ma questa colonna mantiene il nome fisico originale per evitare di toccare la tabella
    # note via Alembic batch mode, che ricrea la tabella e con essa i trigger FTS5.
    milestone_id: Optional[int] = Field(default=None, foreign_key="stream.id")
    # Bozza email generata dall'AI a partire da questa nota — salvata così un
    # secondo clic sul pulsante ✉️ mostra la bozza esistente invece di
    # richiamare l'AI da capo (che resta usata solo per generarla la prima
    # volta o per applicare una richiesta di modifica).
    email_subject: Optional[str] = None
    email_body: Optional[str] = None

    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class Recap(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recap_date: date = Field(default_factory=date.today)
    summary: str
    notes_count: int = 0
    context: str = Field(default="default")
    created_at: datetime = Field(default_factory=datetime.now)


class Client(SQLModel, table=True):
    """Cliente di consulenza — raggruppa uno o più GanttProject."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    context: str = Field(default="default", index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class Absence(SQLModel, table=True):
    """Assenza (ferie, malattia, ...) di una persona — banda sulla timeline,
    indipendente da Cliente/Progetto."""
    id: Optional[int] = Field(default=None, primary_key=True)
    person: str
    start_date: date
    end_date: date
    color: Optional[str] = None
    context: str = Field(default="default", index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class GanttProject(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    color: str = Field(default="#818cf8")
    context: str = Field(default="default")
    is_background: bool = Field(default=False)
    archived: bool = Field(default=False)
    client_id: Optional[int] = Field(default=None, foreign_key="client.id", index=True)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_at: datetime = Field(default_factory=datetime.now)


class Stream(SQLModel, table=True):
    """Uno "Stream" di lavoro dentro un GanttProject: nome + date opzionali (appare come
    barra sulla timeline solo se entrambe le date sono valorizzate). Raggruppa N Note e ne
    calcola il progress. Diretto figlio del progetto — nessuna nidificazione ulteriore."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="ganttproject.id")
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    note_id: Optional[int] = Field(default=None, foreign_key="note.id")
    created_at: datetime = Field(default_factory=datetime.now)


class NoteDependency(SQLModel, table=True):
    """note_id dipende da (è bloccata da) blocker_id."""
    id: Optional[int] = Field(default=None, primary_key=True)
    note_id: int = Field(foreign_key="note.id")
    blocker_id: int = Field(foreign_key="note.id")
    created_at: datetime = Field(default_factory=datetime.now)


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    note_id: Optional[int] = Field(default=None, foreign_key="note.id")
    rel_path: str                      # relativo a doc_root configurato
    orig_name: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    analysis: Optional[str] = None    # summary AI salvato dopo analisi
    created_at: datetime = Field(default_factory=datetime.now)
