import json
import os
import sqlite3
from typing import Any

from shared.config.config import SQLITE_DB_PATH


def _connect() -> sqlite3.Connection:
    parent = os.path.dirname(SQLITE_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_json(value: str, default: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _row_to_auth_session(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _row_to_queue_item(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["is_mock"] = bool(item.get("is_mock"))
    item["draft_payload"] = _parse_json(item.get("draft_payload_json") or "", {})
    item["identity_payload"] = _parse_json(item.get("identity_payload_json") or "", {})
    item["dispatch_response"] = _parse_json(item.get("dispatch_response_json") or "", {})
    return item


def _row_to_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["request_payload"] = _parse_json(item.get("request_payload_json") or "", {})
    item["response_payload"] = _parse_json(item.get("response_payload_json") or "", {})
    return item


def get_dispatch_auth_session(owner_key: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM dispatch_auth_sessions WHERE owner_key = ? LIMIT 1",
            (owner_key,),
        ).fetchone()
    return _row_to_auth_session(row)


def save_dispatch_auth_session(session_item: dict[str, Any]) -> None:
    payload = {
        "owner_key": session_item.get("owner_key", ""),
        "owner_ip": session_item.get("owner_ip", ""),
        "username": session_item.get("username", ""),
        "access_token": session_item.get("access_token", ""),
        "refresh_token": session_item.get("refresh_token", ""),
        "token_type": session_item.get("token_type", "Bearer"),
        "expires_in": int(session_item.get("expires_in") or 0),
        "expires_at": session_item.get("expires_at"),
        "authenticated_ts": session_item.get("authenticated_ts"),
        "updated_ts": int(session_item.get("updated_ts") or 0),
        "status": session_item.get("status", "pending"),
        "is_mock": 1 if session_item.get("is_mock") else 0,
        "last_error": session_item.get("last_error", ""),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO dispatch_auth_sessions (
                owner_key, owner_ip, username, access_token, refresh_token, token_type,
                expires_in, expires_at, authenticated_ts, updated_ts, status, is_mock, last_error
            )
            VALUES (
                :owner_key, :owner_ip, :username, :access_token, :refresh_token, :token_type,
                :expires_in, :expires_at, :authenticated_ts, :updated_ts, :status, :is_mock, :last_error
            )
            ON CONFLICT(owner_key) DO UPDATE SET
                owner_ip = excluded.owner_ip,
                username = excluded.username,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                token_type = excluded.token_type,
                expires_in = excluded.expires_in,
                expires_at = excluded.expires_at,
                authenticated_ts = excluded.authenticated_ts,
                updated_ts = excluded.updated_ts,
                status = excluded.status,
                is_mock = excluded.is_mock,
                last_error = excluded.last_error
            """,
            payload,
        )
        conn.commit()


def list_dispatch_queue(owner_key: str, owner_ip: str, limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 500))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM dispatch_queue
            WHERE owner_key = ?
               OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
            ORDER BY updated_ts DESC, created_ts DESC, id DESC
            LIMIT ?
            """,
            (owner_key, owner_ip, safe_limit),
        ).fetchall()
    return [_row_to_queue_item(row) for row in rows if row is not None]


def get_dispatch_queue_item(queue_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM dispatch_queue WHERE id = ? LIMIT 1",
            (queue_id,),
        ).fetchone()
    return _row_to_queue_item(row)


def upsert_dispatch_queue_item(item: dict[str, Any]) -> None:
    payload = {
        "id": item.get("id", ""),
        "owner_key": item.get("owner_key", ""),
        "owner_ip": item.get("owner_ip", ""),
        "source_job_id": item.get("source_job_id", ""),
        "source_asset_id": item.get("source_asset_id", ""),
        "source_job_type": item.get("source_job_type", ""),
        "source_name": item.get("source_name", ""),
        "source_type": item.get("source_type", ""),
        "asset_name": item.get("asset_name", ""),
        "face_index": int(item.get("face_index") or 0),
        "person_name": item.get("person_name", ""),
        "person_id_no": item.get("person_id_no", ""),
        "person_phone": item.get("person_phone", ""),
        "similarity_score": float(item.get("similarity_score") or 0),
        "illegal_type": item.get("illegal_type", ""),
        "sssj_dm": item.get("sssj_dm", ""),
        "sssj_mc": item.get("sssj_mc", ""),
        "ssfj_dm": item.get("ssfj_dm", ""),
        "ssfj_mc": item.get("ssfj_mc", ""),
        "zbpcs_dm": item.get("zbpcs_dm", ""),
        "zbpcs_mc": item.get("zbpcs_mc", ""),
        "dzmc": item.get("dzmc", ""),
        "rwdyid": item.get("rwdyid", ""),
        "sjcsly": item.get("sjcsly", ""),
        "dispatch_status": item.get("dispatch_status", "pending"),
        "sms_status": item.get("sms_status", "pending"),
        "last_error": item.get("last_error", ""),
        "draft_payload_json": json.dumps(item.get("draft_payload") or {}, ensure_ascii=False),
        "identity_payload_json": json.dumps(item.get("identity_payload") or {}, ensure_ascii=False),
        "dispatch_response_json": json.dumps(item.get("dispatch_response") or {}, ensure_ascii=False),
        "sms_preview": item.get("sms_preview", ""),
        "created_ts": int(item.get("created_ts") or 0),
        "updated_ts": int(item.get("updated_ts") or 0),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO dispatch_queue (
                id, owner_key, owner_ip, source_job_id, source_asset_id, source_job_type, source_name, source_type,
                asset_name, face_index, person_name, person_id_no, person_phone, similarity_score, illegal_type,
                sssj_dm, sssj_mc, ssfj_dm, ssfj_mc, zbpcs_dm, zbpcs_mc, dzmc,
                rwdyid, sjcsly, dispatch_status, sms_status, last_error,
                draft_payload_json, identity_payload_json, dispatch_response_json, sms_preview,
                created_ts, updated_ts
            )
            VALUES (
                :id, :owner_key, :owner_ip, :source_job_id, :source_asset_id, :source_job_type, :source_name, :source_type,
                :asset_name, :face_index, :person_name, :person_id_no, :person_phone, :similarity_score, :illegal_type,
                :sssj_dm, :sssj_mc, :ssfj_dm, :ssfj_mc, :zbpcs_dm, :zbpcs_mc, :dzmc,
                :rwdyid, :sjcsly, :dispatch_status, :sms_status, :last_error,
                :draft_payload_json, :identity_payload_json, :dispatch_response_json, :sms_preview,
                :created_ts, :updated_ts
            )
            ON CONFLICT(id) DO UPDATE SET
                owner_key = excluded.owner_key,
                owner_ip = excluded.owner_ip,
                source_job_id = excluded.source_job_id,
                source_asset_id = excluded.source_asset_id,
                source_job_type = excluded.source_job_type,
                source_name = excluded.source_name,
                source_type = excluded.source_type,
                asset_name = excluded.asset_name,
                face_index = excluded.face_index,
                person_name = excluded.person_name,
                person_id_no = excluded.person_id_no,
                person_phone = excluded.person_phone,
                similarity_score = excluded.similarity_score,
                illegal_type = excluded.illegal_type,
                sssj_dm = excluded.sssj_dm,
                sssj_mc = excluded.sssj_mc,
                ssfj_dm = excluded.ssfj_dm,
                ssfj_mc = excluded.ssfj_mc,
                zbpcs_dm = excluded.zbpcs_dm,
                zbpcs_mc = excluded.zbpcs_mc,
                dzmc = excluded.dzmc,
                rwdyid = excluded.rwdyid,
                sjcsly = excluded.sjcsly,
                dispatch_status = excluded.dispatch_status,
                sms_status = excluded.sms_status,
                last_error = excluded.last_error,
                draft_payload_json = excluded.draft_payload_json,
                identity_payload_json = excluded.identity_payload_json,
                dispatch_response_json = excluded.dispatch_response_json,
                sms_preview = excluded.sms_preview,
                created_ts = excluded.created_ts,
                updated_ts = excluded.updated_ts
            """,
            payload,
        )
        conn.commit()


def save_dispatch_record(record: dict[str, Any]) -> None:
    payload = {
        "id": record.get("id", ""),
        "queue_id": record.get("queue_id", ""),
        "owner_key": record.get("owner_key", ""),
        "owner_ip": record.get("owner_ip", ""),
        "status": record.get("status", "pending"),
        "request_payload_json": json.dumps(record.get("request_payload") or {}, ensure_ascii=False),
        "response_payload_json": json.dumps(record.get("response_payload") or {}, ensure_ascii=False),
        "error_message": record.get("error_message", ""),
        "created_ts": int(record.get("created_ts") or 0),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO dispatch_records (
                id, queue_id, owner_key, owner_ip, status,
                request_payload_json, response_payload_json, error_message, created_ts
            )
            VALUES (
                :id, :queue_id, :owner_key, :owner_ip, :status,
                :request_payload_json, :response_payload_json, :error_message, :created_ts
            )
            ON CONFLICT(id) DO UPDATE SET
                queue_id = excluded.queue_id,
                owner_key = excluded.owner_key,
                owner_ip = excluded.owner_ip,
                status = excluded.status,
                request_payload_json = excluded.request_payload_json,
                response_payload_json = excluded.response_payload_json,
                error_message = excluded.error_message,
                created_ts = excluded.created_ts
            """,
            payload,
        )
        conn.commit()


def list_dispatch_records(owner_key: str, owner_ip: str, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM dispatch_records
            WHERE owner_key = ?
               OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (owner_key, owner_ip, safe_limit),
        ).fetchall()
    return [_row_to_record(row) for row in rows if row is not None]


def save_dispatch_sms_record(record: dict[str, Any]) -> None:
    payload = {
        "id": record.get("id", ""),
        "queue_id": record.get("queue_id", ""),
        "owner_key": record.get("owner_key", ""),
        "owner_ip": record.get("owner_ip", ""),
        "mobile": record.get("mobile", ""),
        "content": record.get("content", ""),
        "status": record.get("status", "pending"),
        "request_payload_json": json.dumps(record.get("request_payload") or {}, ensure_ascii=False),
        "response_payload_json": json.dumps(record.get("response_payload") or {}, ensure_ascii=False),
        "error_message": record.get("error_message", ""),
        "created_ts": int(record.get("created_ts") or 0),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO dispatch_sms_records (
                id, queue_id, owner_key, owner_ip, mobile, content, status,
                request_payload_json, response_payload_json, error_message, created_ts
            )
            VALUES (
                :id, :queue_id, :owner_key, :owner_ip, :mobile, :content, :status,
                :request_payload_json, :response_payload_json, :error_message, :created_ts
            )
            ON CONFLICT(id) DO UPDATE SET
                queue_id = excluded.queue_id,
                owner_key = excluded.owner_key,
                owner_ip = excluded.owner_ip,
                mobile = excluded.mobile,
                content = excluded.content,
                status = excluded.status,
                request_payload_json = excluded.request_payload_json,
                response_payload_json = excluded.response_payload_json,
                error_message = excluded.error_message,
                created_ts = excluded.created_ts
            """,
            payload,
        )
        conn.commit()


def list_dispatch_sms_records(owner_key: str, owner_ip: str, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM dispatch_sms_records
            WHERE owner_key = ?
               OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (owner_key, owner_ip, safe_limit),
        ).fetchall()
    return [_row_to_record(row) for row in rows if row is not None]
