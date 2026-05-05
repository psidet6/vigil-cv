"""Helpers that need cross-module job lookup but belong to no single module.

Both ``face`` and ``training`` routes need to resolve a job from multiple
sources (in-memory running state → SQLite persisted state).  Putting this
logic here avoids circular imports between module packages.
"""

from __future__ import annotations

from typing import Any


def resolve_job(job_id: str) -> dict[str, Any] | None:
    """Look up a job by *job_id* across all job stores.

    Checks (in order): detection in-memory, upload in-memory, SQLite.
    Returns ``None`` when not found anywhere.
    """
    # Lazy imports to avoid import-time circular dependencies.
    from modules.detection.services.job_service import get_job_snapshot
    from modules.detection.services.upload_job_service import get_upload_job_snapshot
    from shared.db.sqlite import get_job as get_saved_job

    job = get_job_snapshot(job_id)
    if job is not None:
        return job
    upload_job = get_upload_job_snapshot(job_id)
    if upload_job is not None:
        return upload_job
    return get_saved_job(job_id)
