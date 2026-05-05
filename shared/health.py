from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from typing import Any

from shared.config.config import (
    CLIP_VIT_B32_PATH,
    FACE_MODEL_DET,
    FACE_MODEL_REC,
    MOBILECLIP_TS_PATH,
    MOBILECLIP2_TS_PATH,
    MODEL_REGISTRY,
    OUTPUT_DIR,
    SQLITE_DB_PATH,
)


HEALTH_STALE_TASK_SECONDS = max(60, int(os.getenv("HEALTH_STALE_TASK_SECONDS", "21600") or 21600))
HEALTH_SAMPLE_LIMIT = 5


def _connect_sqlite() -> sqlite3.Connection:
    parent = os.path.dirname(SQLITE_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _check_sqlite() -> dict[str, Any]:
    check: dict[str, Any] = {
        "ok": True,
        "path": SQLITE_DB_PATH,
        "read_ok": False,
        "write_ok": False,
    }
    try:
        with _connect_sqlite() as conn:
            conn.execute("SELECT 1").fetchone()
            check["read_ok"] = True
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            check["write_ok"] = True
    except Exception as exc:
        check["ok"] = False
        check["error"] = str(exc)
    return check


def _check_output_dir() -> dict[str, Any]:
    check: dict[str, Any] = {
        "ok": True,
        "path": OUTPUT_DIR,
        "exists": False,
        "writable": False,
    }
    probe_path = ""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        check["exists"] = os.path.isdir(OUTPUT_DIR)
        fd, probe_path = tempfile.mkstemp(prefix=".healthz_", suffix=".tmp", dir=OUTPUT_DIR)
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"ok")
        check["writable"] = True
    except Exception as exc:
        check["ok"] = False
        check["error"] = str(exc)
    finally:
        if probe_path and os.path.isfile(probe_path):
            try:
                os.remove(probe_path)
            except OSError:
                pass
    return check


def _model_entries() -> list[tuple[str, str]]:
    entries = [(f"model.{key}", path) for key, path in sorted(MODEL_REGISTRY.items())]
    entries.extend(
        [
            ("model.mobileclip", MOBILECLIP_TS_PATH),
            ("model.mobileclip2", MOBILECLIP2_TS_PATH),
            ("model.clip_vit_b32", CLIP_VIT_B32_PATH),
            ("model.face_det", FACE_MODEL_DET),
            ("model.face_rec", FACE_MODEL_REC),
        ]
    )
    return entries


def _check_models() -> dict[str, Any]:
    missing: list[dict[str, str]] = []
    checked: list[dict[str, str]] = []
    for label, path in _model_entries():
        normalized = os.path.abspath(str(path or ""))
        checked.append({"key": label, "path": normalized})
        if not normalized or not os.path.isfile(normalized):
            missing.append({"key": label, "path": normalized})
    return {
        "ok": not missing,
        "checked_count": len(checked),
        "missing_count": len(missing),
        "missing": missing,
    }


def _check_task_queue(now_ts: int | None = None) -> dict[str, Any]:
    now_ts = int(now_ts or time.time())
    cutoff = now_ts - HEALTH_STALE_TASK_SECONDS
    check: dict[str, Any] = {
        "ok": True,
        "stale_after_seconds": HEALTH_STALE_TASK_SECONDS,
        "running_count": 0,
        "stale_running_count": 0,
        "sample_task_ids": [],
    }
    try:
        with _connect_sqlite() as conn:
            running_row = conn.execute(
                "SELECT COUNT(*) AS total FROM task_queue WHERE status='running'"
            ).fetchone()
            stale_row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM task_queue
                WHERE status='running'
                  AND (claimed_ts IS NULL OR claimed_ts < ?)
                """,
                (cutoff,),
            ).fetchone()
            sample_rows = conn.execute(
                """
                SELECT id
                FROM task_queue
                WHERE status='running'
                  AND (claimed_ts IS NULL OR claimed_ts < ?)
                ORDER BY COALESCE(claimed_ts, 0) ASC, id ASC
                LIMIT ?
                """,
                (cutoff, HEALTH_SAMPLE_LIMIT),
            ).fetchall()

        check["running_count"] = int(running_row["total"] if running_row is not None else 0)
        check["stale_running_count"] = int(stale_row["total"] if stale_row is not None else 0)
        check["sample_task_ids"] = [row["id"] for row in sample_rows]
        check["ok"] = check["stale_running_count"] == 0
    except Exception as exc:
        check["ok"] = False
        check["error"] = str(exc)
    return check


def get_health_report(now_ts: int | None = None) -> dict[str, Any]:
    now_ts = int(now_ts or time.time())
    checks = {
        "sqlite": _check_sqlite(),
        "output_dir": _check_output_dir(),
        "models": _check_models(),
        "task_queue": _check_task_queue(now_ts),
    }
    return {
        "ok": all(check.get("ok") for check in checks.values()),
        "timestamp": now_ts,
        "checks": checks,
    }
