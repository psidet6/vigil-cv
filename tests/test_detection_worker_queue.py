from __future__ import annotations


def test_start_detection_job_enqueues_existing_job(monkeypatch):
    import modules.detection.services.job_service as service

    saved_jobs = []
    submitted_tasks = []
    canceled_jobs = []

    monkeypatch.setattr(service, "list_saved_active_jobs", lambda *args, **kwargs: [{"id": "old-job"}])
    monkeypatch.setattr(service, "request_cancel", lambda job_id, owner_key="", owner_ip="": canceled_jobs.append((job_id, owner_key, owner_ip)) or True)
    monkeypatch.setattr(service, "save_job", lambda job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)) or kwargs["task_id"])

    job = service.start_detection_job(
        [("https://example.com/a.jpg", "2026-04-18 08:00:00")],
        0.25,
        8,
        640,
        "person",
        "general",
        "owner-key",
        "127.0.0.1",
    )

    assert canceled_jobs == [("old-job", "owner-key", "127.0.0.1")]
    assert job["status"] == "queued"
    assert saved_jobs and saved_jobs[-1]["id"] == job["id"]
    assert submitted_tasks == [
        (
            (
                "detection",
                {
                    "job_id": job["id"],
                    "url_and_times": [("https://example.com/a.jpg", "2026-04-18 08:00:00")],
                    "conf_thresh": 0.25,
                    "batch_size": 8,
                    "imgsz": 640,
                    "classes_raw": "person",
                    "model_key": "general",
                },
            ),
            {"owner_key": "owner-key", "owner_ip": "127.0.0.1", "task_id": job["id"]},
        )
    ]


def test_worker_detection_handler_loads_existing_job(monkeypatch):
    import worker
    import modules.detection.services.job_service as service

    job = {"id": "det-1", "status": "queued"}

    monkeypatch.setattr(service, "get_job_snapshot", lambda job_id: job if job_id == "det-1" else None)

    def fake_run_detection(loaded_job, url_and_times, conf_thresh, batch_size, imgsz, classes_raw, model_key):
        assert loaded_job is job
        assert url_and_times == [("https://example.com/a.jpg", "2026-04-18 08:00:00")]
        assert conf_thresh == 0.25
        assert batch_size == 8
        assert imgsz == 640
        assert classes_raw == "person"
        assert model_key == "general"
        loaded_job["status"] = "done"

    monkeypatch.setattr(service, "_run_job", fake_run_detection)

    result = worker._handle_detection(
        {
            "job_id": "det-1",
            "url_and_times": [["https://example.com/a.jpg", "2026-04-18 08:00:00"]],
            "conf_thresh": 0.25,
            "batch_size": 8,
            "imgsz": 640,
            "classes_raw": "person",
            "model_key": "general",
        }
    )

    assert result == {"job_id": "det-1", "status": "done"}


def test_sqlite_list_active_jobs_and_interrupt_filter(monkeypatch, tmp_path):
    from shared.db import sqlite

    monkeypatch.setattr(sqlite, "SQLITE_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    sqlite.init_db()

    sqlite.save_job(
        {
            "id": "database-running",
            "job_type": "database",
            "status": "running",
            "message": "",
            "total": 10,
            "processed": 1,
            "kept": 0,
            "notfound": 0,
            "failed": 0,
            "downloaded": 1,
            "start_ts": 10,
            "end_ts": None,
            "owner_key": "owner-key",
            "owner_ip": "127.0.0.1",
            "source_name": "database",
            "source_type": "database",
        }
    )
    sqlite.save_job(
        {
            "id": "database-queued",
            "job_type": "database",
            "status": "queued",
            "message": "queued",
            "total": 5,
            "processed": 0,
            "kept": 0,
            "notfound": 0,
            "failed": 0,
            "downloaded": 0,
            "start_ts": 11,
            "end_ts": None,
            "owner_key": "owner-key",
            "owner_ip": "127.0.0.1",
            "source_name": "database",
            "source_type": "database",
        }
    )
    sqlite.save_job(
        {
            "id": "upload-running",
            "job_type": "upload",
            "status": "running",
            "message": "",
            "total": 2,
            "processed": 1,
            "kept": 0,
            "notfound": 0,
            "failed": 0,
            "downloaded": 1,
            "start_ts": 12,
            "end_ts": None,
            "owner_key": "owner-key",
            "owner_ip": "127.0.0.1",
            "source_name": "upload.zip",
            "source_type": "zip",
        }
    )

    active = sqlite.list_active_jobs("owner-key", "127.0.0.1", job_type="database")
    assert [item["id"] for item in active] == ["database-queued", "database-running"]

    changed = sqlite.mark_running_jobs_interrupted(job_types=["upload"])
    assert changed == 1
    assert sqlite.get_job("upload-running")["status"] == "interrupted"
    assert sqlite.get_job("database-running")["status"] == "running"
