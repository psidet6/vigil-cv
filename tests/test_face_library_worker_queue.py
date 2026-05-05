from __future__ import annotations


def test_start_face_library_task_enqueues_existing_job(monkeypatch):
    import modules.face.services.library_task_service as service

    saved_jobs = []
    submitted_tasks = []
    run_called = False

    def fake_run(_task):
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(service, "get_active_face_library_job", lambda: None)
    monkeypatch.setattr(service, "get_face_library_status", lambda: {"ready": True})
    monkeypatch.setattr(service, "save_face_library_job", lambda job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)) or kwargs["task_id"])
    monkeypatch.setattr(service, "_run_face_library_task", fake_run)

    task, started = service.start_face_library_task("sync")

    assert started is True
    assert task["status"] == "queued"
    assert task["action"] == "sync"
    assert saved_jobs and saved_jobs[-1]["id"] == task["id"]
    assert submitted_tasks == [(("face_library", {"job_id": task["id"]}), {"task_id": task["id"]})]
    assert run_called is False


def test_start_face_library_task_reuses_active_job(monkeypatch):
    import modules.face.services.library_task_service as service

    active = {"id": "face-1", "action": "rebuild", "status": "queued"}
    submitted_tasks = []

    monkeypatch.setattr(service, "get_active_face_library_job", lambda: active)
    monkeypatch.setattr(service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)))

    task, started = service.start_face_library_task("rebuild")

    assert started is False
    assert task == active
    assert submitted_tasks == []


def test_worker_face_library_handler_loads_existing_job(monkeypatch):
    import worker
    import modules.face.services.library_task_service as service

    job = {"id": "face-1", "action": "rebuild", "status": "queued"}

    monkeypatch.setattr(service, "get_face_library_task", lambda job_id: job if job_id == "face-1" else None)

    def fake_run_face_library_task(loaded_job):
        assert loaded_job is job
        loaded_job["status"] = "done"

    monkeypatch.setattr(service, "_run_face_library_task", fake_run_face_library_task)

    result = worker._handle_face_library({"job_id": "face-1"})

    assert result == {"job_id": "face-1", "status": "done"}


def test_face_library_job_round_trips_through_sqlite(monkeypatch, tmp_path):
    from shared.db import sqlite

    monkeypatch.setattr(sqlite, "SQLITE_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    sqlite.init_db()

    job = {
        "id": "face-1",
        "action": "sync",
        "status": "queued",
        "message": "queued",
        "stage": "queued",
        "processed": 1,
        "total": 2,
        "created_ts": 10,
        "start_ts": 10,
        "end_ts": None,
        "error": "",
        "result": {"synced": 1},
        "library": {"ready": True},
    }

    sqlite.save_face_library_job(job)

    saved = sqlite.get_face_library_job("face-1")
    assert saved["id"] == "face-1"
    assert saved["result"] == {"synced": 1}
    assert saved["library"] == {"ready": True}
    assert sqlite.get_active_face_library_job()["id"] == "face-1"
    assert sqlite.list_face_library_jobs()[0]["id"] == "face-1"

    job["status"] = "done"
    job["end_ts"] = 20
    sqlite.save_face_library_job(job)

    assert sqlite.get_active_face_library_job() is None
