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
    project: Optional[str] = None
    priority: str = Field(default="medium")
    due_date: Optional[date] = None
    status: Optional[str] = Field(default=None, index=True)
    assignee: Optional[str] = None
    context: str = Field(default="default", index=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now)
    milestone_id: Optional[int] = Field(default=None, foreign_key="milestone.id")

    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class Recap(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recap_date: date = Field(default_factory=date.today)
    summary: str
    notes_count: int = 0
    context: str = Field(default="default")
    created_at: datetime = Field(default_factory=datetime.now)


class GanttProject(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    color: str = Field(default="#818cf8")
    context: str = Field(default="default")
    is_background: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)


class Milestone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="ganttproject.id")
    name: str
    start_date: date
    end_date: date
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
