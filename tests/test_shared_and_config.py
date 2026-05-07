from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from modules.detection.upload_routes import _parse_params
from shared.config import config as cfg
from shared.ownership.ownership import job_matches_owner
from shared.utils.helpers import (
    default_time_range,
    ensure_hours_list,
    filename_from_url,
    format_timestamp,
    infer_ext_from_bytes,
    parse_and_normalize_dt,
    sanitize_zip_name,
    to_datetime_local_str,
)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (2, 2), color=(255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_shared_helpers_handle_common_inputs():
    assert sanitize_zip_name(" a/b:c? ") == "a_b_c_"
    assert filename_from_url("https://example.com/path/to/result.jpg?token=1") == "result.jpg"
    assert infer_ext_from_bytes(_png_bytes()) == ".png"
    assert infer_ext_from_bytes(b"broken-bytes") == ".jpg"
    assert ensure_hours_list(["0", "7", "24", "-1", "foo", 23]) == ["00", "07", "23"]
    assert parse_and_normalize_dt("2026-03-31 12:34") == "2026-03-31 12:34:00"

    start, end = default_time_range()
    datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
    assert to_datetime_local_str(datetime(2026, 3, 31, 8, 9, 10)) == "2026-03-31T08:09:10"
    assert format_timestamp(0) == ""
    datetime.strptime(format_timestamp(1), "%Y/%m/%d %H:%M:%S")


def test_config_model_helpers_use_repo_models():
    assert Path(cfg.resolve_model_path("general")).name == "yolov8s-worldv2.pt"
    assert Path(cfg.resolve_model_path("helmet")).name == "helmet-detector.pt"
    assert cfg.model_supports_text_prompt("general") is True
    assert cfg.model_supports_text_prompt("helmet") is False
    assert cfg.get_upload_model_default() == "yolov8s-worldv2.pt"

    registry = cfg.list_upload_model_paths()
    assert "yolov8s-worldv2.pt" in registry
    assert "helmet-detector.pt" in registry

    options = cfg.get_upload_model_options()
    general_option = next(item for item in options if item["value"] == "yolov8s-worldv2.pt")
    assert general_option["ui_mode"] == "prompt"
    assert general_option["default_classes"] == cfg.PROMPT_MODEL_DEFAULT_CLASSES

    train_options = {item["value"] for item in cfg.get_train_base_model_options()}
    assert {"yolo26n.pt", "yolo26s.pt"}.issubset(train_options)


def test_owner_matching_prefers_owner_key_over_ip():
    record = {"owner_key": "owner-1", "owner_ip": "10.0.0.1"}
    assert job_matches_owner(record, "owner-1", "10.0.0.2") is True
    assert job_matches_owner(record, "owner-2", "10.0.0.1") is False
    assert job_matches_owner({"owner_ip": "10.0.0.2"}, "", "10.0.0.2") is True


def test_upload_param_parsing_uses_prompt_defaults():
    conf, batch_size, imgsz, classes_raw, model_key, frame_interval = _parse_params({"model_key": "yolov8s-worldv2.pt"})

    assert model_key == "yolov8s-worldv2.pt"
    assert conf == cfg.PROMPT_MODEL_DEFAULT_CONF
    assert batch_size == cfg.BATCH_SIZE
    assert imgsz == cfg.IMGSZ
    assert classes_raw == cfg.PROMPT_MODEL_DEFAULT_CLASSES
    assert frame_interval == cfg.VIDEO_FRAME_INTERVAL


def test_upload_param_parsing_clamps_numeric_values():
    conf, batch_size, imgsz, classes_raw, model_key, frame_interval = _parse_params(
        {
            "model_key": "helmet-detector.pt",
            "conf": "2",
            "batch_size": "0",
            "imgsz": "100",
            "frame_interval": "99",
            "classes": "car, truck",
        }
    )

    assert model_key == "helmet-detector.pt"
    assert conf == 1.0
    assert batch_size == 1
    assert imgsz == 320
    assert classes_raw == "car, truck"
    assert frame_interval == 60


def test_postgres_query_builder_uses_postgresql_placeholders(monkeypatch):
    from shared.db import postgres

    monkeypatch.setattr(postgres, "POSTGRES_SOURCE_IMAGE_TABLE", "sample_schema.source_image_table")
    monkeypatch.setattr(postgres, "POSTGRES_IMAGE_URL_COLUMN", "image_url")
    monkeypatch.setattr(postgres, "POSTGRES_IMAGE_TIME_COLUMN", "capture_time")
    monkeypatch.setattr(postgres, "POSTGRES_IMAGE_HOUR_COLUMN", "capture_hour")

    sql, params = postgres.build_query_and_params(
        "2026-04-18 00:00:00",
        "2026-04-18 23:59:59",
        ["7"],
        "general",
    )

    assert ":kssj" not in sql
    assert "%s" in sql
    assert "ANY(%s)" in sql
    assert params == ["2026-04-18 00:00:00", "2026-04-18 23:59:59", ["07"]]

    monkeypatch.setattr(postgres, "POSTGRES_SOURCE_IMAGE_TABLE", "bad;drop")
    with pytest.raises(ValueError):
        postgres.build_query_and_params("", "", [], "general")
