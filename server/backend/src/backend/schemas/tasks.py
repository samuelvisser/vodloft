from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TaskRead(BaseModel):
    id: str
    name: str
    status: str
    progress: int
    message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    result: Any = None


def task_read(snapshot) -> TaskRead:
    return TaskRead(
        id=snapshot.id,
        name=snapshot.name,
        status=str(snapshot.status),
        progress=snapshot.progress,
        message=snapshot.message,
        created_at=snapshot.created_at,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        error=snapshot.error,
        result=snapshot.result,
    )
