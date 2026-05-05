"""Standalone task worker process.

Polls the ``task_queue`` table and executes queued heavy workloads outside the
Flask web process. Training, auto-annotate, and face-library routes enqueue
tasks today, and both PostgreSQL-backed / upload detection are now executed here as well.

Start manually::

    python worker.py                 # consume all task types
    python worker.py --type detection
    python worker.py --type upload
    python worker.py --type train    # consume only training tasks
    python worker.py --type auto_annotate
    python worker.py --type face_library

The worker runs **one task at a time** (CPU-bound workloads). For
concurrency, start multiple worker instances with different ``--type``
filters.
"""

from __future__ import annotations

import argparse
from typing import Callable
import signal
import sys
import time

# Ensure project root is on sys.path so shared/modules imports work.
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.config.config import logger
from shared.db.sqlite import init_db
from shared.task_queue import (
    claim_task,
    cleanup_old_tasks,
    complete_task,
    fail_task,
    reset_stale_running,
)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown = False


def _sig_handler(_signum, _frame):
    global _shutdown
    _shutdown = True
    logger.info("worker: shutdown signal received, finishing current task")


signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)


# ---------------------------------------------------------------------------
# Task dispatchers - import lazily to avoid loading heavy libs at startup
# ---------------------------------------------------------------------------


def _handle_train(payload: dict) -> dict:
    """Run a YOLO training task."""
    from modules.training.services.train_task_service import (
        get_train_job_snapshot,
        _run_train_job,
    )

    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("missing train job_id")
    job = get_train_job_snapshot(job_id)
    if job is None:
        raise LookupError(f"train job not found: {job_id}")
    _run_train_job(job)
    return {"job_id": job.get("id"), "status": job.get("status")}


def _handle_detection(payload: dict) -> dict:
    """Run a PostgreSQL-backed detection task."""
    from modules.detection.services.job_service import (
        _run_job,
        get_job_snapshot,
    )

    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("missing detection job_id")

    job = get_job_snapshot(job_id)
    if job is None:
        raise LookupError(f"detection job not found: {job_id}")

    raw_items = payload.get("url_and_times") or []
    url_and_times: list[tuple[str, str]] = []
    for item in raw_items:
        if isinstance(item, (list, tuple)) and item:
            url = str(item[0] or "").strip()
            ts = str(item[1] or "").strip() if len(item) > 1 else ""
        else:
            url = str(item or "").strip()
            ts = ""
        if url:
            url_and_times.append((url, ts))
    if not url_and_times:
        raise ValueError("missing detection url_and_times")

    _run_job(
        job,
        url_and_times,
        float(payload.get("conf_thresh") or job.get("conf_thresh") or 0.0),
        int(payload.get("batch_size") or job.get("batch_size") or 1),
        int(payload.get("imgsz") or job.get("imgsz") or 640),
        str(payload.get("classes_raw") or job.get("classes_raw") or ""),
        str(payload.get("model_key") or job.get("model_key") or ""),
    )
    updated_job = get_job_snapshot(job_id) or job
    return {"job_id": updated_job.get("id"), "status": updated_job.get("status")}


def _handle_upload(payload: dict) -> dict:
    """Run a ZIP or video upload detection task."""
    from modules.detection.services.upload_job_service import (
        _run_upload_job,
        get_upload_job_snapshot,
    )

    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("missing upload job_id")

    job = get_upload_job_snapshot(job_id)
    if job is None:
        raise LookupError(f"upload job not found: {job_id}")

    source_path = str(job.get("source_path") or "").strip()
    if not source_path:
        raise ValueError("missing upload source_path")

    source_type = str(job.get("source_type") or "").strip()
    if source_type not in {"zip", "video"}:
        raise ValueError(f"unsupported upload source_type: {source_type}")

    _run_upload_job(
        job,
        source_path,
        source_type,
        float(job.get("conf_thresh") or 0.0),
        int(job.get("batch_size") or 1),
        int(job.get("imgsz") or 640),
        str(job.get("classes_raw") or ""),
        str(job.get("model_key") or ""),
        str(job.get("temp_dir") or ""),
        int(job.get("frame_interval") or 0) if job.get("frame_interval") is not None else None,
    )
    updated_job = get_upload_job_snapshot(job_id) or job
    return {"job_id": updated_job.get("id"), "status": updated_job.get("status")}


def _handle_auto_annotate(payload: dict) -> dict:
    """Run an auto-annotate task."""
    from modules.training.services.auto_annotate_task_service import (
        get_auto_annotate_job_snapshot,
        _run_auto_annotate_job,
    )

    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("missing auto annotate job_id")
    job = get_auto_annotate_job_snapshot(job_id)
    if job is None:
        raise LookupError(f"auto annotate job not found: {job_id}")
    asset_ids = payload.get("asset_ids", [])
    _run_auto_annotate_job(job, asset_ids)
    return {"job_id": job.get("id"), "status": job.get("status")}


def _handle_face_library(payload: dict) -> dict:
    """Run a face library rebuild or sync."""
    from modules.face.services.library_task_service import (
        get_face_library_task,
        _run_face_library_task,
    )

    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("missing face library job_id")
    job = get_face_library_task(job_id)
    if job is None:
        raise LookupError(f"face library job not found: {job_id}")
    _run_face_library_task(job)
    return {"job_id": job.get("id"), "status": job.get("status")}


HANDLERS: dict[str, Callable] = {
    "detection": _handle_detection,
    "upload": _handle_upload,
    "train": _handle_train,
    "auto_annotate": _handle_auto_annotate,
    "face_library": _handle_face_library,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_worker(task_type: str | None = None, poll_interval: float = 2.0) -> None:
    """Poll the task queue and execute tasks until shutdown."""
    init_db()
    reset_stale_running()
    logger.info(
        "worker started  type_filter=%s  poll_interval=%.1fs",
        task_type or "(all)",
        poll_interval,
    )

    last_cleanup = time.time()

    while not _shutdown:
        task = claim_task(task_type)
        if task is None:
            # No work - idle sleep then housekeeping.
            time.sleep(poll_interval)
            now = time.time()
            if now - last_cleanup > 3600:
                reset_stale_running()
                cleanup_old_tasks(30)
                last_cleanup = now
            continue

        tid = task["id"]
        ttype = task["task_type"]
        logger.info("worker: claimed task %s  type=%s", tid, ttype)

        handler = HANDLERS.get(ttype)
        if handler is None:
            fail_task(tid, error=f"unknown task type: {ttype}")
            logger.error("worker: no handler for task type %r", ttype)
            continue

        try:
            result = handler(task["payload"])
            complete_task(tid, result=result)
        except Exception as exc:
            logger.exception("worker: task %s failed", tid)
            fail_task(tid, error=str(exc)[:1000])

    logger.info("worker: exited cleanly")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Vigil CV task worker")
    parser.add_argument(
        "--type",
        dest="task_type",
        default=None,
        choices=list(HANDLERS.keys()),
        help="Only consume tasks of this type (default: all)",
    )
    parser.add_argument(
        "--interval",
        dest="poll_interval",
        type=float,
        default=2.0,
        help="Seconds between queue polls when idle (default: 2)",
    )
    args = parser.parse_args()
    run_worker(task_type=args.task_type, poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
