from __future__ import annotations

import json
import time
from typing import Any

from shared import task_queue
from shared.health import HEALTH_STALE_TASK_SECONDS


DEFAULT_TASK_LIMIT = 60
MAX_TASK_LIMIT = 200
ERROR_PREVIEW_CHARS = 200


def normalize_task_limit(value: str | int | None) -> int:
    try:
        limit = int(value or DEFAULT_TASK_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_TASK_LIMIT
    return max(1, min(limit, MAX_TASK_LIMIT))


def _clean_filter(value: str | None) -> str:
    return str(value or "").strip()


def _mask_owner(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    if len(text) <= 10:
        return f"{text[:2]}***{text[-2:]}"
    return f"{text[:4]}...{text[-4:]}"


def _parse_payload(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _duration_between(start_ts: Any, end_ts: Any) -> int | None:
    try:
        start = int(start_ts or 0)
        end = int(end_ts or 0)
    except (TypeError, ValueError):
        return None
    if not start or not end:
        return None
    return max(0, end - start)


def _duration_since(now_ts: int, start_ts: Any) -> int | None:
    try:
        start = int(start_ts or 0)
    except (TypeError, ValueError):
        return None
    if not start:
        return None
    return max(0, now_ts - start)


def _serialize_task(row: Any, now_ts: int, stale_after_seconds: int) -> dict[str, Any]:
    payload = _parse_payload(row["payload"])
    status = str(row["status"] or "")
    claimed_ts = row["claimed_ts"]
    finished_ts = row["finished_ts"]
    created_ts = row["created_ts"]
    is_running = status == "running"
    is_stale = is_running and (not claimed_ts or int(claimed_ts) < now_ts - stale_after_seconds)

    wait_seconds = (
        _duration_between(created_ts, claimed_ts)
        if claimed_ts
        else _duration_since(now_ts, created_ts)
    )
    run_seconds = (
        _duration_since(now_ts, claimed_ts)
        if is_running
        else _duration_between(claimed_ts, finished_ts)
    )
    total_seconds = (
        _duration_between(created_ts, finished_ts)
        if finished_ts
        else _duration_since(now_ts, created_ts)
    )

    return {
        "task_id": row["id"],
        "task_type": row["task_type"],
        "status": status,
        "job_id": str(payload.get("job_id") or ""),
        "owner_key": _mask_owner(row["owner_key"]),
        "owner_ip": _mask_owner(row["owner_ip"]),
        "created_ts": created_ts,
        "claimed_ts": claimed_ts,
        "finished_ts": finished_ts,
        "wait_seconds": wait_seconds,
        "run_seconds": run_seconds,
        "total_seconds": total_seconds,
        "retries": int(row["retries"] or 0),
        "stale": is_stale,
        "error": str(row["error"] or "")[:ERROR_PREVIEW_CHARS],
    }


def get_task_queue_snapshot(
    *,
    task_type: str | None = None,
    status: str | None = None,
    limit: str | int | None = None,
    now_ts: int | None = None,
    stale_after_seconds: int = HEALTH_STALE_TASK_SECONDS,
) -> dict[str, Any]:
    now_ts = int(now_ts or time.time())
    safe_limit = normalize_task_limit(limit)
    safe_task_type = _clean_filter(task_type)
    safe_status = _clean_filter(status)
    cutoff = now_ts - stale_after_seconds

    clauses: list[str] = []
    params: list[Any] = []
    if safe_task_type:
        clauses.append("task_type=?")
        params.append(safe_task_type)
    if safe_status:
        clauses.append("status=?")
        params.append(safe_status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with task_queue._connect() as conn:
        total_row = conn.execute("SELECT COUNT(*) AS total FROM task_queue").fetchone()
        status_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM task_queue
            GROUP BY status
            ORDER BY status ASC
            """
        ).fetchall()
        type_status_rows = conn.execute(
            """
            SELECT task_type, status, COUNT(*) AS count
            FROM task_queue
            GROUP BY task_type, status
            ORDER BY task_type ASC, status ASC
            """
        ).fetchall()
        stale_row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM task_queue
            WHERE status='running'
              AND (claimed_ts IS NULL OR claimed_ts < ?)
            """,
            (cutoff,),
        ).fetchone()
        task_rows = conn.execute(
            f"""
            SELECT *
            FROM task_queue
            {where_sql}
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            [*params, safe_limit],
        ).fetchall()

    status_counts = {row["status"]: int(row["count"] or 0) for row in status_rows}
    return {
        "generated_ts": now_ts,
        "filters": {
            "task_type": safe_task_type,
            "status": safe_status,
            "limit": safe_limit,
        },
        "stale_after_seconds": stale_after_seconds,
        "totals": {
            "total": int(total_row["total"] if total_row is not None else 0),
            "pending": status_counts.get("pending", 0),
            "running": status_counts.get("running", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "stale_running": int(stale_row["total"] if stale_row is not None else 0),
        },
        "by_status": [
            {"status": row["status"], "count": int(row["count"] or 0)}
            for row in status_rows
        ],
        "by_type_status": [
            {
                "task_type": row["task_type"],
                "status": row["status"],
                "count": int(row["count"] or 0),
            }
            for row in type_status_rows
        ],
        "tasks": [_serialize_task(row, now_ts, stale_after_seconds) for row in task_rows],
    }
