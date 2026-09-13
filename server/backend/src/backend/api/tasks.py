from fastapi import APIRouter, HTTPException

from controller.workers import cancel_task, get_task, list_tasks

from backend.schemas import TaskRead
from backend.schemas.tasks import task_read

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def tasks():
    return [task_read(item) for item in list_tasks()]


@router.get("/{task_id}", response_model=TaskRead)
def task(task_id: str):
    snapshot = get_task(task_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_read(snapshot)


@router.post("/{task_id}/cancel", status_code=204)
def cancel(task_id: str):
    if not cancel_task(task_id):
        raise HTTPException(status_code=409, detail="Task cannot be cancelled")
