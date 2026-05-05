from __future__ import annotations

import zipfile


def test_start_zip_job_enqueues_existing_job(monkeypatch, tmp_path):
    import modules.detection.services.upload_job_service as service

    temp_dir = tmp_path / "upload-temp"
    temp_dir.mkdir()
    zip_path = temp_dir / "images.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a.jpg", b"demo")

    saved_jobs = []
    submitted_tasks = []

    monkeypatch.setattr(service, "save_job", lambda job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)) or kwargs["task_id"])

    job_id, err = service.start_zip_job(
        str(zip_path),
        "images.zip",
        0.25,
        8,
        640,
        "person",
        "general",
        "owner-key",
        "127.0.0.1",
        str(temp_dir),
    )

    assert err == ""
    assert job_id
    assert saved_jobs and saved_jobs[-1]["id"] == job_id
    assert saved_jobs[-1]["status"] == "queued"
    assert saved_jobs[-1]["source_path"] == str(zip_path)
    assert submitted_tasks == [
        (
            ("upload", {"job_id": job_id}),
            {"owner_key": "owner-key", "owner_ip": "127.0.0.1", "task_id": job_id},
        )
    ]


def test_start_video_job_enqueues_existing_job(monkeypatch, tmp_path):
    import modules.detection.services.upload_job_service as service

    class FakeCapture:
        def __init__(self, _path):
            self.closed = False

        def isOpened(self):
            return True

        def get(self, key):
            assert key == service.cv2.CAP_PROP_FRAME_COUNT
            return 30

        def release(self):
            self.closed = True

    temp_dir = tmp_path / "upload-video"
    temp_dir.mkdir()
    video_path = temp_dir / "sample.mp4"
    video_path.write_bytes(b"demo")

    saved_jobs = []
    submitted_tasks = []

    monkeypatch.setattr(service.cv2, "VideoCapture", FakeCapture)
    monkeypatch.setattr(service, "save_job", lambda job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)) or kwargs["task_id"])

    job_id, err = service.start_video_job(
        str(video_path),
        "sample.mp4",
        5,
        0.25,
        8,
        640,
        "person",
        "general",
        "owner-key",
        "127.0.0.1",
        str(temp_dir),
    )

    assert err == ""
    assert job_id
    assert saved_jobs and saved_jobs[-1]["id"] == job_id
    assert saved_jobs[-1]["status"] == "queued"
    assert saved_jobs[-1]["frame_interval"] == 5
    assert saved_jobs[-1]["total"] == 6
    assert submitted_tasks == [
        (
            ("upload", {"job_id": job_id}),
            {"owner_key": "owner-key", "owner_ip": "127.0.0.1", "task_id": job_id},
        )
    ]


def test_worker_upload_handler_loads_existing_job(monkeypatch):
    import worker
    import modules.detection.services.upload_job_service as service

    job = {
        "id": "upload-1",
        "job_type": "upload",
        "status": "queued",
        "source_path": "/tmp/input.zip",
        "source_type": "zip",
        "conf_thresh": 0.25,
        "batch_size": 8,
        "imgsz": 640,
        "classes_raw": "person",
        "model_key": "general",
        "temp_dir": "/tmp/upload-temp",
        "frame_interval": None,
    }

    monkeypatch.setattr(service, "get_upload_job_snapshot", lambda job_id: job if job_id == "upload-1" else None)

    def fake_run_upload_job(loaded_job, source_path, source_type, conf_thresh, batch_size, imgsz, classes_raw, model_key, temp_dir, frame_interval):
        assert loaded_job is job
        assert source_path == "/tmp/input.zip"
        assert source_type == "zip"
        assert conf_thresh == 0.25
        assert batch_size == 8
        assert imgsz == 640
        assert classes_raw == "person"
        assert model_key == "general"
        assert temp_dir == "/tmp/upload-temp"
        assert frame_interval is None
        loaded_job["status"] = "done"

    monkeypatch.setattr(service, "_run_upload_job", fake_run_upload_job)

    result = worker._handle_upload({"job_id": "upload-1"})

    assert result == {"job_id": "upload-1", "status": "done"}
