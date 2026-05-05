from __future__ import annotations

import json


def _use_temp_queue_db(monkeypatch, tmp_path):
    from shared import task_queue

    monkeypatch.setattr(task_queue, "SQLITE_DB_PATH", str(tmp_path / "queue.sqlite"))
    with task_queue._connect() as conn:
        task_queue.init_task_queue_table(conn)
        conn.commit()
    return task_queue


def _insert_task(
    task_queue,
    *,
    task_id: str,
    task_type: str,
    status: str,
    payload: dict | None = None,
    created_ts: int = 1,
    claimed_ts: int | None = None,
    finished_ts: int | None = None,
    retries: int = 0,
    error: str = "",
):
    with task_queue._connect() as conn:
        conn.execute(
            """
            INSERT INTO task_queue (
                id, task_type, status, payload, error, owner_key, owner_ip,
                created_ts, claimed_ts, finished_ts, retries
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task_type,
                status,
                json.dumps(payload or {}, ensure_ascii=False),
                error,
                "owner-key-123456",
                "127.0.0.1",
                created_ts,
                claimed_ts,
                finished_ts,
                retries,
            ),
        )
        conn.commit()


def test_task_queue_snapshot_summarizes_and_redacts(monkeypatch, tmp_path):
    from shared import task_queue_diagnostics as diagnostics

    task_queue = _use_temp_queue_db(monkeypatch, tmp_path)
    _insert_task(task_queue, task_id="pending-1", task_type="upload", status="pending", payload={"job_id": "job-p"}, created_ts=100)
    _insert_task(task_queue, task_id="running-1", task_type="upload", status="running", payload={"job_id": "job-r"}, created_ts=200, claimed_ts=300)
    _insert_task(task_queue, task_id="failed-1", task_type="train", status="failed", payload={"job_id": "job-f"}, created_ts=400, claimed_ts=500, finished_ts=600, retries=2, error="boom")

    snapshot = diagnostics.get_task_queue_snapshot(now_ts=1000, stale_after_seconds=100, limit=10)

    assert snapshot["totals"]["total"] == 3
    assert snapshot["totals"]["pending"] == 1
    assert snapshot["totals"]["running"] == 1
    assert snapshot["totals"]["failed"] == 1
    assert snapshot["totals"]["stale_running"] == 1
    assert {item["status"]: item["count"] for item in snapshot["by_status"]} == {
        "failed": 1,
        "pending": 1,
        "running": 1,
    }

    running = next(item for item in snapshot["tasks"] if item["task_id"] == "running-1")
    assert running["job_id"] == "job-r"
    assert running["owner_key"] == "owne...3456"
    assert running["owner_ip"] == "12***.1"
    assert running["stale"] is True
    assert "payload" not in running
    assert "result" not in running


def test_task_queue_snapshot_filters_and_clamps_limit(monkeypatch, tmp_path):
    from shared import task_queue_diagnostics as diagnostics

    task_queue = _use_temp_queue_db(monkeypatch, tmp_path)
    _insert_task(task_queue, task_id="upload-1", task_type="upload", status="pending", payload={"job_id": "job-1"}, created_ts=10)
    _insert_task(task_queue, task_id="train-1", task_type="train", status="pending", payload={"job_id": "job-2"}, created_ts=20)

    snapshot = diagnostics.get_task_queue_snapshot(task_type="upload", status="pending", limit=999, now_ts=100)

    assert snapshot["filters"] == {"task_type": "upload", "status": "pending", "limit": diagnostics.MAX_TASK_LIMIT}
    assert [item["task_id"] for item in snapshot["tasks"]] == ["upload-1"]
