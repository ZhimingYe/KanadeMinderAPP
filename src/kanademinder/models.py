"""Task dataclass and related enums."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class Task:
    name: str
    type: TaskType = TaskType.MAJOR
    parent_id: int | None = None
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    priority: int = 3
    status: TaskStatus = TaskStatus.PENDING
    notes: str | None = None
    recurrence: str | None = None
    recurrence_end: date | None = None
    id: int | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not isinstance(self.type, TaskType):
            self.type = TaskType(self.type)
        if not isinstance(self.status, TaskStatus):
            self.status = TaskStatus(self.status)
        if not (1 <= self.priority <= 5):
            raise ValueError(f"priority must be 1–5, got {self.priority}")

        # Coerce deadline: string or date → datetime
        if isinstance(self.deadline, str) and self.deadline:
            dl = self.deadline.strip()
            # Try datetime formats first, then date-only (→ midnight)
            parsed: datetime | None = None
            for fmt in (
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
            ):
                try:
                    parsed = datetime.strptime(dl, fmt)
                    break
                except ValueError:
                    continue
            self.deadline = parsed  # None if unparseable
        elif isinstance(self.deadline, date) and not isinstance(self.deadline, datetime):
            self.deadline = datetime(self.deadline.year, self.deadline.month, self.deadline.day)

        # Coerce recurrence_end: string → date
        if isinstance(self.recurrence_end, str) and self.recurrence_end:
            try:
                self.recurrence_end = date.fromisoformat(self.recurrence_end)
            except ValueError:
                self.recurrence_end = None

        if isinstance(self.created_at, str) and self.created_at:
            self.created_at = datetime.fromisoformat(self.created_at)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Task":
        """Construct a Task from a sqlite3.Row."""
        d = dict(row)
        recurrence_end: date | None = None
        if d.get("recurrence_end"):
            try:
                recurrence_end = date.fromisoformat(d["recurrence_end"])
            except (ValueError, TypeError):
                pass
        return cls(
            id=d["id"],
            name=d["name"],
            type=TaskType(d["type"]),
            parent_id=d.get("parent_id"),
            deadline=datetime.fromisoformat(d["deadline"]) if d.get("deadline") else None,
            estimated_minutes=d.get("estimated_minutes"),
            priority=d["priority"],
            status=TaskStatus(d["status"]),
            notes=d.get("notes"),
            recurrence=d.get("recurrence"),
            recurrence_end=recurrence_end,
            created_at=datetime.fromisoformat(d["created_at"]),
        )

    def to_insert_dict(self) -> dict[str, Any]:
        """Return a dict suitable for INSERT (excludes id, uses ISO strings for dates)."""
        return {
            "name": self.name,
            "type": self.type.value,
            "parent_id": self.parent_id,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "estimated_minutes": self.estimated_minutes,
            "priority": self.priority,
            "status": self.status.value,
            "notes": self.notes,
            "recurrence": self.recurrence,
            "recurrence_end": self.recurrence_end.isoformat() if self.recurrence_end else None,
            "created_at": self.created_at.isoformat(),
        }
