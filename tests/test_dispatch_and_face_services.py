from __future__ import annotations

import pickle

import numpy as np
import pytest

import modules.dispatch.services.auth_service as auth_service
import modules.dispatch.services.sms_service as sms_service
import modules.face.services.library_service as library_service


def test_dispatch_auth_mock_mode_persists_token(monkeypatch):
    sessions: dict[str, dict] = {}

    monkeypatch.setattr(auth_service, "DISPATCH_MOCK_MODE", True)
    monkeypatch.setattr(auth_service, "save_dispatch_auth_session", lambda payload: sessions.__setitem__(payload["owner_key"], dict(payload)))
    monkeypatch.setattr(auth_service, "get_dispatch_auth_session", lambda owner_key: sessions.get(owner_key))

    status = auth_service.authenticate_dispatch_platform("owner-1", "127.0.0.1", "alice", "secret")

    assert status["authenticated"] is True
    assert status["is_mock"] is True
    token, token_status = auth_service.get_valid_dispatch_token("owner-1")
    assert token.startswith("mock-")
    assert token_status["authenticated"] is True


def test_dispatch_auth_rejects_empty_credentials():
    with pytest.raises(ValueError):
        auth_service.authenticate_dispatch_platform("owner-1", "127.0.0.1", "", "")


def test_sms_preview_and_send_mock_mode(monkeypatch):
    queue_item = {
        "id": "queue-1",
        "person_name": "Alice",
        "person_id_no": "person-001",
        "person_phone": "555-0100",
        "illegal_type": "专项场景",
        "source_name": "来源任务",
        "sssj_mc": "Region A",
        "ssfj_mc": "Region A-1",
        "zbpcs_mc": "Unit A-1-1",
        "ywfzrlxdh": "12345",
        "dzmc": "示例地址",
        "xfdw": "Demo Unit",
    }
    saved_queue_items: list[dict] = []
    saved_sms_records: list[dict] = []

    monkeypatch.setattr(sms_service, "DISPATCH_MOCK_MODE", True)
    monkeypatch.setattr(sms_service, "get_dispatch_queue_detail", lambda owner_key, owner_ip, queue_id: queue_item)
    monkeypatch.setattr(sms_service, "upsert_dispatch_queue_item", lambda item: saved_queue_items.append(dict(item)))
    monkeypatch.setattr(sms_service, "save_dispatch_sms_record", lambda payload: saved_sms_records.append(dict(payload)))

    preview = sms_service.preview_sms(queue_item, template="请联系{xm} {zjhm} {deadline}", mobile="")
    assert preview["mobile"] == "555-0100"
    assert "Alice" in preview["content"]

    result = sms_service.send_sms_notifications(
        "owner-1",
        "127.0.0.1",
        ["queue-1"],
        template="请联系{xm}",
        mobile="",
    )

    assert result["mock_mode"] is True
    assert result["items"][0]["status"] == "success"
    assert saved_queue_items[-1]["sms_status"] == "success"
    assert saved_sms_records[-1]["status"] == "success"


def test_face_library_status_and_list_persons(tmp_path, monkeypatch):
    photo_dir = tmp_path / "photos"
    feature_dir = tmp_path / "features"
    photo_dir.mkdir()
    feature_dir.mkdir()
    db_cache_file = tmp_path / "person_db.pkl"
    meta_file = tmp_path / "meta.json"

    embedding = np.ones(512, dtype=np.float32)
    person = library_service.PersonRecord(
        zjlx="01",
        zjhm="person-001",
        xm="Alice",
        photo_path=str(photo_dir / "alice.jpg"),
        embedding=embedding,
    )

    (photo_dir / "alice.jpg").write_bytes(b"photo")
    np.save(feature_dir / "alice.npy", embedding)
    with db_cache_file.open("wb") as fh:
        pickle.dump([person], fh)
    meta_file.write_text("{\"last_sync_ts\": 123, \"last_rebuild_ts\": 456, \"last_sync_rows\": 1}", encoding="utf-8")

    monkeypatch.setattr(library_service, "PHOTO_DIR", str(photo_dir))
    monkeypatch.setattr(library_service, "FEATURE_DIR", str(feature_dir))
    monkeypatch.setattr(library_service, "DB_CACHE_FILE", str(db_cache_file))
    monkeypatch.setattr(library_service, "META_FILE", str(meta_file))
    monkeypatch.setattr(library_service, "face_models_ready", lambda: True)

    status = library_service.get_face_library_status()
    assert status["ready"] is True
    assert status["sql_enabled"] is False
    assert status["photo_count"] == 1
    assert status["feature_count"] == 1
    assert status["valid_person_count"] == 1

    result = library_service.list_persons(page=1, page_size=10, keyword="ali")
    assert result["total"] == 1
    assert result["items"][0]["status"] == "valid"
    assert result["items"][0]["has_photo"] is True

    with pytest.raises(RuntimeError, match="POSTGRES_ENABLED"):
        library_service.sync_face_library()
