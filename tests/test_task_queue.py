from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor


def _use_temp_queue_db(monkeypatch, tmp_path):
    from shared import task_queue

    monkeypatch.setattr(task_queue, "SQLITE_DB_PATH", str(tmp_path / "queue.sqlite"))
    with task_queue._connect() as conn:
        task_queue.init_task_queue_table(conn)
        conn.commit()
    return task_queue


def test_claim_task_marks_pending_task_running(monkeypatch, tmp_path):
    task_queue = _use_temp_queue_db(monkeypatch, tmp_path)

    task_queue.submit_task(
        "train",
        {"job_id": "job-1"},
        owner_key="owner-1",
        owner_ip="127.0.0.1",
        task_id="task-1",
    )

    claimed = task_queue.claim_task("train")

    assert claimed == {
        "id": "task-1",
        "task_type": "train",
        "payload": {"job_id": "job-1"},
        "owner_key": "owner-1",
        "owner_ip": "127.0.0.1",
        "created_ts": claimed["created_ts"],
    }
    assert task_queue.get_task("task-1")["status"] == "running"
    assert task_queue.claim_task("train") is None


def test_claim_task_filters_type_and_uses_oldest_pending(monkeypatch, tmp_path):
    task_queue = _use_temp_queue_db(monkeypatch, tmp_path)

    task_queue.submit_task("auto_annotate", {"job_id": "auto-1"}, task_id="auto-1")
    task_queue.submit_task("train", {"job_id": "newer"}, task_id="train-newer")
    task_queue.submit_task("train", {"job_id": "older"}, task_id="train-older")

    with task_queue._connect() as conn:
        conn.execute("UPDATE task_queue SET created_ts=? WHERE id=?", (20, "train-newer"))
        conn.execute("UPDATE task_queue SET created_ts=? WHERE id=?", (10, "train-older"))
        conn.commit()

    claimed = task_queue.claim_task("train")

    assert claimed["id"] == "train-older"
    assert claimed["payload"] == {"job_id": "older"}
    assert task_queue.get_task("auto-1")["status"] == "pending"


def test_concurrent_claims_only_receive_one_copy(monkeypatch, tmp_path):
    task_queue = _use_temp_queue_db(monkeypatch, tmp_path)
    task_queue.submit_task("train", {"job_id": "job-1"}, task_id="task-1")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: task_queue.claim_task("train"), range(8)))

    claimed = [result for result in results if result is not None]

    assert [result["id"] for result in claimed] == ["task-1"]
    assert task_queue.get_task("task-1")["status"] == "running"


def test_app_sqlite_connection_uses_wal_and_busy_timeout(monkeypatch, tmp_path):
    from shared.db import sqlite

    monkeypatch.setattr(sqlite, "SQLITE_DB_PATH", str(tmp_path / "app.sqlite3"))

    with sqlite._connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 30000
    assert synchronous == 1
