from __future__ import annotations

import sqlite3


def _prepare_task_queue_db(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE task_queue (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                result TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                owner_key TEXT NOT NULL DEFAULT '',
                owner_ip TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL DEFAULT 0,
                claimed_ts INTEGER,
                finished_ts INTEGER,
                retries INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def test_health_report_is_ok_when_dependencies_exist(monkeypatch, tmp_path):
    import shared.health as health

    db_path = tmp_path / "jobs.sqlite3"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    _prepare_task_queue_db(db_path)

    model_paths = {}
    for name in ("general.pt", "special.pt", "mobileclip.ts", "mobileclip2.ts", "clip.pt", "det.onnx", "rec.onnx"):
        path = tmp_path / name
        path.write_bytes(b"placeholder")
        model_paths[name] = str(path)

    monkeypatch.setattr(health, "SQLITE_DB_PATH", str(db_path))
    monkeypatch.setattr(health, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(
        health,
        "MODEL_REGISTRY",
        {"special": model_paths["special.pt"], "general": model_paths["general.pt"]},
    )
    monkeypatch.setattr(health, "MOBILECLIP_TS_PATH", model_paths["mobileclip.ts"])
    monkeypatch.setattr(health, "MOBILECLIP2_TS_PATH", model_paths["mobileclip2.ts"])
    monkeypatch.setattr(health, "CLIP_VIT_B32_PATH", model_paths["clip.pt"])
    monkeypatch.setattr(health, "FACE_MODEL_DET", model_paths["det.onnx"])
    monkeypatch.setattr(health, "FACE_MODEL_REC", model_paths["rec.onnx"])
    monkeypatch.setattr(health, "HEALTH_STALE_TASK_SECONDS", 3600)

    report = health.get_health_report(now_ts=1000)

    assert report["ok"] is True
    assert report["checks"]["sqlite"]["read_ok"] is True
    assert report["checks"]["sqlite"]["write_ok"] is True
    assert report["checks"]["output_dir"]["writable"] is True
    assert report["checks"]["models"]["missing_count"] == 0
    assert report["checks"]["task_queue"]["stale_running_count"] == 0


def test_health_report_flags_missing_models_and_stale_tasks(monkeypatch, tmp_path):
    import shared.health as health

    db_path = tmp_path / "jobs.sqlite3"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    _prepare_task_queue_db(db_path)

    existing_model = tmp_path / "general.pt"
    existing_model.write_bytes(b"placeholder")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO task_queue (id, task_type, status, created_ts, claimed_ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("stale-task", "upload", "running", 1, 10),
        )
        conn.commit()

    monkeypatch.setattr(health, "SQLITE_DB_PATH", str(db_path))
    monkeypatch.setattr(health, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(
        health,
        "MODEL_REGISTRY",
        {"special": str(tmp_path / "missing-special.pt"), "general": str(existing_model)},
    )
    monkeypatch.setattr(health, "MOBILECLIP_TS_PATH", str(tmp_path / "missing-mobileclip.ts"))
    monkeypatch.setattr(health, "MOBILECLIP2_TS_PATH", str(tmp_path / "missing-mobileclip2.ts"))
    monkeypatch.setattr(health, "CLIP_VIT_B32_PATH", str(tmp_path / "missing-clip.pt"))
    monkeypatch.setattr(health, "FACE_MODEL_DET", str(tmp_path / "missing-det.onnx"))
    monkeypatch.setattr(health, "FACE_MODEL_REC", str(tmp_path / "missing-rec.onnx"))
    monkeypatch.setattr(health, "HEALTH_STALE_TASK_SECONDS", 300)

    report = health.get_health_report(now_ts=1000)

    assert report["ok"] is False
    assert report["checks"]["models"]["missing_count"] == 6
    assert report["checks"]["task_queue"]["stale_running_count"] == 1
    assert report["checks"]["task_queue"]["sample_task_ids"] == ["stale-task"]
