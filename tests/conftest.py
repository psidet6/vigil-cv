from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO_ROOT / "model"
TEST_ROOT = Path(tempfile.mkdtemp(prefix="vigil_cv_pytest_"))


def _write_placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"placeholder")


def _prepare_environment() -> None:
    for directory in (
        TEST_ROOT / "output",
        TEST_ROOT / "output" / "_results",
        TEST_ROOT / "datasets",
        TEST_ROOT / "train_runs",
        TEST_ROOT / "upload_tmp",
        TEST_ROOT / "face_data",
        TEST_ROOT / "face_data" / "photos",
        TEST_ROOT / "face_data" / "features",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    for filename in (
        "special_event_detector.pt",
        "yolov8s-worldv2.pt",
        "yolo26n.pt",
        "yolo26s.pt",
        "mobileclip_blt.ts",
        "mobileclip2_b.ts",
        "ViT-B-32.pt",
        "det_10g.onnx",
        "w600k_r50.onnx",
    ):
        _write_placeholder(MODEL_DIR / filename)

    face_sql_query_path = TEST_ROOT / "face_library.sql"
    _write_placeholder(face_sql_query_path)

    os.environ.update(
        {
            "FLASK_SECRET_KEY": "test-secret-key",
            "YOLO_TELEMETRY": "false",
            "DISPATCH_MOCK_MODE": "true",
            "POSTGRES_ENABLED": "false",
            "POSTGRES_HOST": "",
            "POSTGRES_DB": "",
            "POSTGRES_USER": "",
            "POSTGRES_PASSWORD": "",
            "OUTPUT_DIR": str(TEST_ROOT / "output"),
            "RESULTS_DIR": str(TEST_ROOT / "output" / "_results"),
            "DATASETS_DIR": str(TEST_ROOT / "datasets"),
            "TRAIN_RUNS_DIR": str(TEST_ROOT / "train_runs"),
            "UPLOAD_TEMP_DIR": str(TEST_ROOT / "upload_tmp"),
            "FACE_DATA_DIR": str(TEST_ROOT / "face_data"),
            "SQLITE_DB_PATH": str(TEST_ROOT / "jobs.sqlite3"),
            "POSTGRES_FACE_QUERY_PATH": str(face_sql_query_path),
            "MODEL_PATH": str(MODEL_DIR / "special_event_detector.pt"),
            "MODEL_PATH_GENERAL": str(MODEL_DIR / "yolov8s-worldv2.pt"),
            "MOBILECLIP_TS_PATH": str(MODEL_DIR / "mobileclip_blt.ts"),
            "MOBILECLIP2_TS_PATH": str(MODEL_DIR / "mobileclip2_b.ts"),
            "CLIP_VIT_B32_PATH": str(MODEL_DIR / "ViT-B-32.pt"),
            "FACE_MODEL_DET": str(MODEL_DIR / "det_10g.onnx"),
            "FACE_MODEL_REC": str(MODEL_DIR / "w600k_r50.onnx"),
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "5001",
        }
    )


def pytest_configure(config):
    _prepare_environment()


def pytest_unconfigure(config):
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def app_module():
    import app as app_module

    return app_module


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()
