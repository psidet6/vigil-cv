from __future__ import annotations


def test_start_train_job_enqueues_existing_job(monkeypatch, tmp_path):
    import modules.training.services.train_task_service as train_service

    saved_jobs = []
    submitted_tasks = []
    run_called = False

    def fake_run(_job):
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(
        train_service,
        "get_dataset",
        lambda dataset_id: {
            "id": dataset_id,
            "name": "demo dataset",
            "class_names": ["car"],
            "image_count": 2,
            "labeled_count": 1,
        },
    )
    monkeypatch.setattr(train_service, "resolve_model_path", lambda _model: str(tmp_path / "model.pt"))
    monkeypatch.setattr(train_service.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(train_service, "_resolve_yolo_executable", lambda: str(tmp_path / "yolo.exe"))
    monkeypatch.setattr(train_service, "_split_labeled_assets", lambda *_args, **_kwargs: ([], [], []))
    monkeypatch.setattr(train_service, "save_train_job", lambda job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(train_service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)) or kwargs["task_id"])
    monkeypatch.setattr(train_service, "_run_train_job", fake_run)

    job = train_service.start_train_job(
        "dataset-1",
        "yolo26n.pt",
        "quick",
        1,
        640,
        1,
        "owner-key",
        "127.0.0.1",
        confirmed_only=False,
    )

    assert job["status"] == "queued"
    assert saved_jobs and saved_jobs[-1]["id"] == job["id"]
    assert submitted_tasks == [
        (
            ("train", {"job_id": job["id"]}),
            {"owner_key": "owner-key", "owner_ip": "127.0.0.1", "task_id": job["id"]},
        )
    ]
    assert run_called is False


def test_start_auto_annotate_job_enqueues_existing_job(monkeypatch):
    import modules.training.services.auto_annotate_task_service as auto_service

    saved_jobs = []
    submitted_tasks = []
    run_called = False

    def fake_run(_job, _asset_ids):
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(auto_service, "get_dataset", lambda dataset_id: {"id": dataset_id, "name": "demo dataset"})
    monkeypatch.setattr(auto_service, "save_auto_annotate_job", lambda job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(auto_service, "submit_task", lambda *args, **kwargs: submitted_tasks.append((args, kwargs)) or kwargs["task_id"])
    monkeypatch.setattr(auto_service, "_run_auto_annotate_job", fake_run)

    job = auto_service.start_auto_annotate_job(
        "dataset-1",
        ["asset-1.jpg", "asset-2.jpg"],
        "yolov8s-worldv2.pt",
        0.25,
        640,
        "person",
        "",
        False,
        "owner-key",
        "127.0.0.1",
    )

    assert job["status"] == "queued"
    assert saved_jobs and saved_jobs[-1]["id"] == job["id"]
    assert submitted_tasks == [
        (
            ("auto_annotate", {"job_id": job["id"], "asset_ids": ["asset-1.jpg", "asset-2.jpg"]}),
            {"owner_key": "owner-key", "owner_ip": "127.0.0.1", "task_id": job["id"]},
        )
    ]
    assert run_called is False


def test_worker_train_handler_loads_existing_job(monkeypatch):
    import worker
    import modules.training.services.train_task_service as train_service

    job = {"id": "train-1", "status": "queued"}

    monkeypatch.setattr(train_service, "get_train_job_snapshot", lambda job_id: job if job_id == "train-1" else None)

    def fake_run_train_job(loaded_job):
        assert loaded_job is job
        loaded_job["status"] = "done"

    monkeypatch.setattr(train_service, "_run_train_job", fake_run_train_job)

    result = worker._handle_train({"job_id": "train-1"})

    assert result == {"job_id": "train-1", "status": "done"}


def test_worker_auto_annotate_handler_loads_existing_job(monkeypatch):
    import worker
    import modules.training.services.auto_annotate_task_service as auto_service

    job = {"id": "auto-1", "status": "queued"}

    monkeypatch.setattr(auto_service, "get_auto_annotate_job_snapshot", lambda job_id: job if job_id == "auto-1" else None)

    def fake_run_auto_annotate_job(loaded_job, asset_ids):
        assert loaded_job is job
        assert asset_ids == ["asset-1.jpg"]
        loaded_job["status"] = "done"

    monkeypatch.setattr(auto_service, "_run_auto_annotate_job", fake_run_auto_annotate_job)

    result = worker._handle_auto_annotate({"job_id": "auto-1", "asset_ids": ["asset-1.jpg"]})

    assert result == {"job_id": "auto-1", "status": "done"}
