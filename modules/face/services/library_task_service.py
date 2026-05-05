from __future__ import annotations

import time
from uuid import uuid4

from modules.face.services.library_service import (
    get_face_library_status,
    rebuild_face_library,
    sync_face_library,
)
from shared.db.sqlite import (
    get_active_face_library_job,
    get_face_library_job,
    list_face_library_jobs,
    save_face_library_job,
)
from shared.task_queue import submit_task


VALID_ACTIONS = {"rebuild", "sync"}
PROGRESS_KEYS = ("message", "stage", "processed", "total")


def _task_snapshot(task: dict | None) -> dict | None:
    if task is None:
        return None
    return dict(task)


def list_face_library_tasks() -> list[dict]:
    return [_task_snapshot(task) for task in list_face_library_jobs(limit=50)]


def get_face_library_task(task_id: str) -> dict | None:
    return _task_snapshot(get_face_library_job(task_id))


def get_running_face_library_task() -> dict | None:
    # Kept for route compatibility; queued tasks are active in Worker mode.
    return _task_snapshot(get_active_face_library_job())


def _update_task(task: dict, **values) -> None:
    task.update(values)
    save_face_library_job(task)


def _run_face_library_task(task: dict) -> None:
    action = str(task.get("action") or "").strip()
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported face library action: {action}")

    def progress_cb(update: dict) -> None:
        payload = {key: update[key] for key in PROGRESS_KEYS if key in update}
        if payload:
            _update_task(task, **payload)

    try:
        now = int(time.time())
        _update_task(
            task,
            status="running",
            start_ts=task.get("start_ts") or now,
            message=task.get("message") or "running",
            stage=task.get("stage") or "running",
        )

        if action == "sync":
            result = sync_face_library(progress_cb=progress_cb)
        else:
            result = rebuild_face_library(progress_cb=progress_cb)

        _update_task(
            task,
            status="done",
            end_ts=int(time.time()),
            result=result,
            library=get_face_library_status(),
            message="completed",
        )
    except Exception as exc:
        _update_task(
            task,
            status="error",
            end_ts=int(time.time()),
            error=str(exc),
            message=str(exc),
            library=get_face_library_status(),
        )


def start_face_library_task(action: str) -> tuple[dict, bool]:
    action = str(action or "").strip()
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported face library action: {action}")

    active = get_running_face_library_task()
    if active is not None:
        return active, False

    now = int(time.time())
    task = {
        "id": uuid4().hex,
        "action": action,
        "status": "queued",
        "message": "queued",
        "stage": "queued",
        "processed": 0,
        "total": 0,
        "created_ts": now,
        "start_ts": now,
        "end_ts": None,
        "error": "",
        "result": {},
        "library": get_face_library_status(),
    }
    save_face_library_job(task)
    submit_task("face_library", {"job_id": task["id"]}, task_id=task["id"])
    return _task_snapshot(task), True
