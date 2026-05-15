from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field, JSON, Column
import json


PRIORITIES = ("low", "medium", "high")
STATUSES = ("todo", "wip", "done", "blocked")

class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    tags: str = Field(default="")
    project: Optional[str] = None
    priority: str = Field(default="medium")
    due_date: Optional[date] = None
    status: Optional[str] = None   # todo | wip | done | blocked
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class Recap(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recap_date: date = Field(default_factory=date.today)
    summary: str                           # testo generato da Claude
    notes_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
