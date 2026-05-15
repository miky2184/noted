from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field, JSON, Column
import json


PRIORITIES = ("low", "medium", "high")
STATUSES = ("backlog", "todo", "wip", "waiting", "blocked", "done")

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
    status: Optional[str] = None   # backlog | todo | wip | waiting | blocked | done
    assignee: Optional[str] = None
    context: str = Field(default="default")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

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
    created_at: datetime = Field(default_factory=datetime.now)


class Milestone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="ganttproject.id")
    name: str
    start_date: date
    end_date: date
    created_at: datetime = Field(default_factory=datetime.now)
