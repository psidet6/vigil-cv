from flask import Blueprint, jsonify, request

from shared.config.config import (
    DISPATCH_AUTH_URL,
    DISPATCH_CLIENT_ID,
    DISPATCH_MOCK_MODE,
    DISPATCH_QUEUE_LIMIT,
    DISPATCH_SMS_DEFAULT_MOBILE,
    DISPATCH_SMS_DEFAULT_TEMPLATE,
    DISPATCH_TASK_URL,
    DISPATCH_YWFZR,
    DISPATCH_YWFZRLXDH,
    logger,
)
from modules.dispatch.services.auth_service import (
    authenticate_dispatch_platform,
    get_dispatch_auth_status,
)
from modules.dispatch.services.queue_service import (
    build_dispatch_payload,
    filter_dispatch_payload,
    get_dispatch_queue_detail,
    list_dispatch_queue_items,
    refresh_dispatch_region_context,
)
from modules.dispatch.services.sms_service import preview_sms, send_sms_notifications
from modules.dispatch.services.store_service import (
    list_dispatch_records,
    list_dispatch_sms_records,
)
from modules.dispatch.services.task_service import (
    dispatch_queue_items,
    preview_dispatch_payloads,
)
from shared.ownership.ownership import get_request_owner


dispatch_bp = Blueprint("dispatch", __name__, url_prefix="/dispatch")


def _serialize_queue_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "source_job_id": item.get("source_job_id", ""),
        "source_asset_id": item.get("source_asset_id", ""),
        "source_job_type": item.get("source_job_type", ""),
        "source_name": item.get("source_name", ""),
        "source_type": item.get("source_type", ""),
        "asset_name": item.get("asset_name", ""),
        "face_index": item.get("face_index", 0),
        "person_name": item.get("person_name", ""),
        "person_id_no": item.get("person_id_no", ""),
        "person_phone": item.get("person_phone", ""),
        "similarity_score": item.get("similarity_score", 0),
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
        "draft_payload": item.get("draft_payload") or build_dispatch_payload(item, payload_mode="minimal"),
        "recommended_payload": filter_dispatch_payload(
            item.get("draft_payload") or build_dispatch_payload(item, payload_mode="full"),
            payload_mode="minimal",
        ),
        "identity_payload": item.get("identity_payload") or {},
        "sms_preview": item.get("sms_preview", ""),
        "created_ts": item.get("created_ts"),
        "updated_ts": item.get("updated_ts"),
    }


def _recent_activity(owner_key: str, owner_ip: str) -> dict:
    return {
        "dispatch_records": list_dispatch_records(owner_key, owner_ip, limit=20),
        "sms_records": list_dispatch_sms_records(owner_key, owner_ip, limit=20),
    }


@dispatch_bp.get("/auth/status")
def dispatch_auth_status():
    owner_key, _owner_ip = get_request_owner(request)
    return jsonify(
        {
            "ok": True,
            "auth": get_dispatch_auth_status(owner_key),
            "config": {
                "auth_url": DISPATCH_AUTH_URL,
                "task_url": DISPATCH_TASK_URL,
                "client_id": DISPATCH_CLIENT_ID,
                "mock_mode": DISPATCH_MOCK_MODE,
            },
        }
    )


@dispatch_bp.post("/auth/login")
def dispatch_auth_login():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or request.form or {}
    username = (payload.get("username", "") or "").strip()
    password = (payload.get("password", "") or "").strip()
    try:
        auth = authenticate_dispatch_platform(owner_key, owner_ip, username, password)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "auth": auth})


@dispatch_bp.get("/queue")
def dispatch_queue_list():
    owner_key, owner_ip = get_request_owner(request)
    items = list_dispatch_queue_items(owner_key, owner_ip, limit=DISPATCH_QUEUE_LIMIT)
    return jsonify(
        {
            "ok": True,
            "auth": get_dispatch_auth_status(owner_key),
            "items": [_serialize_queue_item(item) for item in items],
            "history": _recent_activity(owner_key, owner_ip),
            "defaults": {
                "sms_mobile": DISPATCH_SMS_DEFAULT_MOBILE,
                "sms_template": DISPATCH_SMS_DEFAULT_TEMPLATE,
                "ywfzr": DISPATCH_YWFZR,
                "ywfzrlxdh": DISPATCH_YWFZRLXDH,
            },
        }
    )


@dispatch_bp.get("/queue/<queue_id>")
def dispatch_queue_detail(queue_id: str):
    owner_key, owner_ip = get_request_owner(request)
    try:
        item = get_dispatch_queue_detail(owner_key, owner_ip, queue_id)
    except LookupError:
        return jsonify({"ok": False, "error": "queue item not found"}), 404
    sms_data = preview_sms(item, template=DISPATCH_SMS_DEFAULT_TEMPLATE, mobile=DISPATCH_SMS_DEFAULT_MOBILE)
    return jsonify(
        {
            "ok": True,
            "item": _serialize_queue_item(item),
            "sms_preview": sms_data,
        }
    )


@dispatch_bp.post("/queue/refresh-region")
def dispatch_queue_refresh_region():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    queue_ids = payload.get("queue_ids") or []
    if not isinstance(queue_ids, list) or not queue_ids:
        return jsonify({"ok": False, "error": "queue_ids is required"}), 400
    try:
        result = refresh_dispatch_region_context(owner_key, owner_ip, queue_ids)
    except LookupError:
        return jsonify({"ok": False, "error": "queue item not found"}), 404
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to refresh dispatch region context: %s", exc)
        return jsonify({"ok": False, "error": "refresh region failed"}), 500
    return jsonify(
        {
            "ok": True,
            "message": f"已刷新 {result.get('updated', 0)} 条，跳过 {result.get('skipped', 0)} 条。",
            "updated": result.get("updated", 0),
            "skipped": result.get("skipped", 0),
            "items": [_serialize_queue_item(item) for item in result.get("items") or []],
        }
    )


@dispatch_bp.post("/preview")
def dispatch_preview():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    queue_ids = payload.get("queue_ids") or []
    overrides = payload.get("overrides") or {}
    payload_items = payload.get("payload_items")
    payload_mode = payload.get("payload_mode") or "minimal"
    if not isinstance(queue_ids, list) or not queue_ids:
        return jsonify({"ok": False, "error": "queue_ids is required"}), 400
    try:
        items = preview_dispatch_payloads(
            owner_key,
            owner_ip,
            queue_ids,
            overrides=overrides,
            payload_items=payload_items,
            payload_mode=payload_mode,
        )
    except LookupError:
        return jsonify({"ok": False, "error": "queue item not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to preview dispatch payloads: %s", exc)
        return jsonify({"ok": False, "error": "preview failed"}), 500
    return jsonify({"ok": True, "items": items})


@dispatch_bp.post("/send")
def dispatch_send():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    queue_ids = payload.get("queue_ids") or []
    overrides = payload.get("overrides") or {}
    payload_items = payload.get("payload_items")
    payload_mode = payload.get("payload_mode") or "minimal"
    if not isinstance(queue_ids, list) or not queue_ids:
        return jsonify({"ok": False, "error": "queue_ids is required"}), 400
    try:
        result = dispatch_queue_items(
            owner_key,
            owner_ip,
            queue_ids,
            overrides=overrides,
            payload_items=payload_items,
            payload_mode=payload_mode,
        )
    except LookupError:
        return jsonify({"ok": False, "error": "queue item not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to dispatch queue items: %s", exc)
        return jsonify({"ok": False, "error": "dispatch failed"}), 500
    return jsonify({"ok": True, **result})


@dispatch_bp.post("/sms/preview")
def dispatch_sms_preview():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    queue_id = (payload.get("queue_id", "") or "").strip()
    template = payload.get("template", "") or DISPATCH_SMS_DEFAULT_TEMPLATE
    mobile = payload.get("mobile", "") or DISPATCH_SMS_DEFAULT_MOBILE
    overrides = payload.get("overrides") or {}
    if not queue_id:
        return jsonify({"ok": False, "error": "queue_id is required"}), 400
    try:
        item = get_dispatch_queue_detail(owner_key, owner_ip, queue_id)
    except LookupError:
        return jsonify({"ok": False, "error": "queue item not found"}), 404
    return jsonify({"ok": True, "preview": preview_sms(item, template=template, mobile=mobile, overrides=overrides)})


@dispatch_bp.post("/sms/send")
def dispatch_sms_send():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    queue_ids = payload.get("queue_ids") or []
    template = payload.get("template", "") or DISPATCH_SMS_DEFAULT_TEMPLATE
    mobile = payload.get("mobile", "") or DISPATCH_SMS_DEFAULT_MOBILE
    overrides = payload.get("overrides") or {}
    if not isinstance(queue_ids, list) or not queue_ids:
        return jsonify({"ok": False, "error": "queue_ids is required"}), 400
    try:
        result = send_sms_notifications(owner_key, owner_ip, queue_ids, template=template, mobile=mobile, overrides=overrides)
    except LookupError:
        return jsonify({"ok": False, "error": "queue item not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to send dispatch sms: %s", exc)
        return jsonify({"ok": False, "error": "sms send failed"}), 500
    return jsonify(result)
