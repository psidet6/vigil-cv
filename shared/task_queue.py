"""SQLite-backed durable task queue.

This module replaces in-process ``threading.Thread`` dispatching for heavy
workloads such as training, inference, and face library rebuilds. Tasks survive
Web-process restarts and can be consumed by a dedicated ``worker.py`` process.

The queue is stored in the same SQLite database used by the rest of the app
(``SQLITE_DB_PATH``).

Producer example::

    from shared.task_queue import submit_task

    task_id = submit_task("train", payload={"dataset_id": "...", ...})

Consumer example::

    from shared.task_queue import claim_task, complete_task, fail_task

    row = claim_task("train")
    if row:
        try:
            do_work(row["payload"])
            complete_task(row["id"], result={...})
        except Exception as e:
            fail_task(row["id"], error=str(e))
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any
from uuid import uuid4

from shared.config.config import SQLITE_DB_PATH, logger


# ---------------------------------------------------------------------------
# Connection helper (same pattern as sqlite.py)
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    parent = os.path.dirname(SQLITE_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Schema bootstrap - called from init_db()
# ---------------------------------------------------------------------------

def init_task_queue_table(conn: sqlite3.Connection) -> None:
    """Create the ``task_queue`` table if it does not exist.

    Called once from :func:`shared.db.sqlite.init_db`.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_queue (
            id          TEXT PRIMARY KEY,
            task_type   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            payload     TEXT NOT NULL DEFAULT '{}',
            result      TEXT NOT NULL DEFAULT '{}',
            error       TEXT NOT NULL DEFAULT '',
            owner_key   TEXT NOT NULL DEFAULT '',
            owner_ip    TEXT NOT NULL DEFAULT '',
            created_ts  INTEGER NOT NULL DEFAULT 0,
            claimed_ts  INTEGER,
            finished_ts INTEGER,
            retries     INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_queue_status_type ON task_queue(status, task_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_queue_created ON task_queue(created_ts DESC)"
    )


# ---------------------------------------------------------------------------
# Producer API
# ---------------------------------------------------------------------------

def submit_task(
    task_type: str,
    payload: dict[str, Any] | None = None,
    *,
    owner_key: str = "",
    owner_ip: str = "",
    task_id: str | None = None,
) -> str:
    """Enqueue a new task and return its task id."""
    task_id = task_id or uuid4().hex
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO task_queue (id, task_type, status, payload, owner_key, owner_ip, created_ts)
            VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                task_id,
                task_type,
                json.dumps(payload or {}, ensure_ascii=False),
                owner_key,
                owner_ip,
                now,
            ),
        )
        conn.commit()
    logger.info("task submitted: %s type=%s", task_id, task_type)
    return task_id


# ---------------------------------------------------------------------------
# Consumer API
# ---------------------------------------------------------------------------

def claim_task(task_type: str | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest pending task.

    When *task_type* is provided, only tasks of that type are considered. The
    ``BEGIN IMMEDIATE`` transaction prevents multiple worker processes from
    selecting the same pending row before it is marked as running.
    """
    now = int(time.time())
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if task_type:
                row = conn.execute(
                    """
                    SELECT * FROM task_queue
                    WHERE status='pending' AND task_type=?
                    ORDER BY created_ts ASC, id ASC
                    LIMIT 1
                    """,
                    (task_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM task_queue
                    WHERE status='pending'
                    ORDER BY created_ts ASC, id ASC
                    LIMIT 1
                    """,
                ).fetchone()

            if row is None:
                conn.commit()
                return None

            cur = conn.execute(
                "UPDATE task_queue SET status='running', claimed_ts=? WHERE id=? AND status='pending'",
                (now, row["id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = {}

    return {
        "id": row["id"],
        "task_type": row["task_type"],
        "payload": payload,
        "owner_key": row["owner_key"],
        "owner_ip": row["owner_ip"],
        "created_ts": row["created_ts"],
    }


def complete_task(task_id: str, result: dict[str, Any] | None = None) -> None:
    """Mark *task_id* as completed with an optional result payload."""
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            "UPDATE task_queue SET status='completed', result=?, finished_ts=? WHERE id=?",
            (json.dumps(result or {}, ensure_ascii=False), now, task_id),
        )
        conn.commit()
    logger.info("task completed: %s", task_id)


def fail_task(task_id: str, error: str = "") -> None:
    """Mark *task_id* as failed with an error message."""
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            "UPDATE task_queue SET status='failed', error=?, finished_ts=? WHERE id=?",
            (error, now, task_id),
        )
        conn.commit()
    logger.warning("task failed: %s  error=%s", task_id, error[:200])


def get_task(task_id: str) -> dict[str, Any] | None:
    """Return the current state of *task_id*, or ``None``."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=?", (task_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for key in ("payload", "result"):
        try:
            d[key] = json.loads(d.get(key) or "{}")
        except Exception:
            d[key] = {}
    return d


def list_tasks(
    task_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List tasks filtered by *task_type* and/or *status*."""
    clauses: list[str] = []
    params: list[Any] = []
    if task_type:
        clauses.append("task_type=?")
        params.append(task_type)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM task_queue WHERE {where} ORDER BY created_ts DESC LIMIT ?",
            params,
        ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        for key in ("payload", "result"):
            try:
                d[key] = json.loads(d.get(key) or "{}")
            except Exception:
                d[key] = {}
        results.append(d)
    return results


def reset_stale_running(max_age_seconds: int = 3600) -> int:
    """Reset stale running tasks back to pending and return the changed count."""
    cutoff = int(time.time()) - max_age_seconds
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE task_queue SET status='pending', retries=retries+1 WHERE status='running' AND claimed_ts < ?",
            (cutoff,),
        )
        conn.commit()
    count = cur.rowcount
    if count:
        logger.info("reset %d stale running tasks (cutoff=%d)", count, cutoff)
    return count


def cleanup_old_tasks(days: int = 30) -> int:
    """Delete completed/failed tasks older than *days*."""
    cutoff = int(time.time()) - days * 86400
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM task_queue WHERE status IN ('completed', 'failed') AND finished_ts < ?",
            (cutoff,),
        )
        conn.commit()
    return cur.rowcount
