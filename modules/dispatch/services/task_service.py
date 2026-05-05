import time
from uuid import uuid4

import requests

from shared.config.config import DISPATCH_MOCK_MODE, DISPATCH_TASK_URL, logger
from modules.dispatch.services.auth_service import get_valid_dispatch_token
from modules.dispatch.services.queue_service import build_dispatch_payload, get_dispatch_queue_detail
from modules.dispatch.services.store_service import (
    save_dispatch_record,
    upsert_dispatch_queue_item,
)


def _coerce_payload_items(queue_ids: list[str], payload_items) -> list[dict] | None:
    if payload_items is None:
        return None
    if isinstance(payload_items, dict):
        payload_list = [payload_items]
    elif isinstance(payload_items, list):
        payload_list = payload_items
    else:
        raise ValueError("payload_items must be a JSON object or array")
    if not all(isinstance(item, dict) for item in payload_list):
        raise ValueError("payload_items must contain JSON objects only")
    if queue_ids and len(payload_list) != len(queue_ids):
        raise ValueError("payload_items length must match queue_ids length")
    return [dict(item) for item in payload_list]


def preview_dispatch_payloads(
    owner_key: str,
    owner_ip: str,
    queue_ids: list[str],
    overrides: dict | None = None,
    payload_items=None,
    payload_mode: str = "minimal",
) -> list[dict]:
    custom_payloads = _coerce_payload_items(queue_ids, payload_items)
    if custom_payloads is not None:
        return custom_payloads
    payloads = []
    for queue_id in queue_ids:
        item = get_dispatch_queue_detail(owner_key, owner_ip, queue_id)
        payloads.append(build_dispatch_payload(item, overrides=overrides, payload_mode=payload_mode))
    return payloads


def dispatch_queue_items(
    owner_key: str,
    owner_ip: str,
    queue_ids: list[str],
    overrides: dict | None = None,
    payload_items=None,
    payload_mode: str = "minimal",
) -> dict:
    overrides = overrides or {}
    custom_payloads = _coerce_payload_items(queue_ids, payload_items)
    payload_items = []
    queue_items = []
    for index, queue_id in enumerate(queue_ids):
        item = get_dispatch_queue_detail(owner_key, owner_ip, queue_id)
        payload = custom_payloads[index] if custom_payloads is not None else build_dispatch_payload(
            item,
            overrides=overrides,
            payload_mode=payload_mode,
        )
        payload_items.append(payload)
        queue_items.append(item)

    token, auth_status = get_valid_dispatch_token(owner_key)
    request_payload = payload_items
    now = int(time.time())

    if DISPATCH_MOCK_MODE:
        response_payload = {
            "code": "200",
            "success": True,
            "message": "mock dispatch success",
            "timestamp": now,
            "data": [
                {"wxtid": payload.get("wxtid"), "systemid": "mock-" + uuid4().hex[:12]}
                for payload in payload_items
            ],
        }
    else:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"{auth_status.get('token_type', 'Bearer')} {token}",
        }
        response = requests.post(
            DISPATCH_TASK_URL,
            headers=headers,
            json=payload_items,
            timeout=20,
        )
        try:
            response_payload = response.json()
        except Exception:
            response_payload = {"raw": response.text}
        if response.status_code >= 400:
            raise RuntimeError(str(response_payload.get("message") or response.text or "dispatch request failed"))

    success = bool(response_payload.get("success", True))
    for item, payload in zip(queue_items, payload_items):
        updated_item = dict(item)
        updated_item["draft_payload"] = payload
        updated_item["dispatch_response"] = response_payload
        updated_item["updated_ts"] = now
        updated_item["dispatch_status"] = "success" if success else "failed"
        updated_item["last_error"] = "" if success else str(response_payload.get("errorMessage") or response_payload.get("message") or "")
        upsert_dispatch_queue_item(updated_item)
        save_dispatch_record(
            {
                "id": uuid4().hex,
                "queue_id": item.get("id"),
                "owner_key": owner_key,
                "owner_ip": owner_ip,
                "status": updated_item["dispatch_status"],
                "request_payload": payload,
                "response_payload": response_payload,
                "error_message": updated_item["last_error"],
                "created_ts": now,
            }
        )

    return {
        "success": success,
        "count": len(queue_items),
        "response": response_payload,
        "mock_mode": DISPATCH_MOCK_MODE,
    }
