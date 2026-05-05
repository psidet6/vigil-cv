import time
from uuid import uuid4

from shared.config.config import (
    DISPATCH_MOCK_MODE,
    DISPATCH_SMS_DEFAULT_MOBILE,
    DISPATCH_SMS_DEFAULT_TEMPLATE,
    DISPATCH_SMS_PASSWORD,
    DISPATCH_SMS_USERID,
    DISPATCH_SMS_USERPORT,
)
from shared.db.postgres import insert_sms_queue_record
from modules.dispatch.services.queue_service import (
    get_dispatch_queue_detail,
    render_sms_template,
)
from modules.dispatch.services.store_service import (
    save_dispatch_sms_record,
    upsert_dispatch_queue_item,
)


def preview_sms(queue_item: dict, template: str = "", mobile: str = "", overrides: dict | None = None) -> dict:
    content = render_sms_template(queue_item, template or DISPATCH_SMS_DEFAULT_TEMPLATE, overrides=overrides)
    return {
        "mobile": str(mobile or queue_item.get("person_phone") or DISPATCH_SMS_DEFAULT_MOBILE).strip(),
        "content": content,
        "userport": DISPATCH_SMS_USERPORT,
        "userid": DISPATCH_SMS_USERID,
    }


def send_sms_notifications(
    owner_key: str,
    owner_ip: str,
    queue_ids: list[str],
    template: str = "",
    mobile: str = "",
    overrides: dict | None = None,
) -> dict:
    now = int(time.time())
    results = []
    for queue_id in queue_ids:
        item = get_dispatch_queue_detail(owner_key, owner_ip, queue_id)
        sms_preview = preview_sms(item, template=template, mobile=mobile, overrides=overrides)
        if not sms_preview["mobile"]:
            raise ValueError("sms mobile is required")

        request_payload = {
            "mobile": sms_preview["mobile"],
            "content": sms_preview["content"],
            "status": "0",
            "eid": item.get("id"),
            "userid": DISPATCH_SMS_USERID,
            "password": DISPATCH_SMS_PASSWORD,
            "userport": DISPATCH_SMS_USERPORT,
        }

        if DISPATCH_MOCK_MODE:
            response_payload = {"success": True, "message": "mock sms queued"}
            status = "success"
            error_message = ""
        else:
            try:
                insert_sms_queue_record(request_payload)
                response_payload = {"success": True, "message": "sms queued"}
                status = "success"
                error_message = ""
            except Exception as exc:
                response_payload = {"success": False, "message": str(exc)}
                status = "failed"
                error_message = str(exc)

        updated_item = dict(item)
        updated_item["sms_preview"] = sms_preview["content"]
        updated_item["sms_status"] = status
        updated_item["last_error"] = error_message if error_message else ""
        updated_item["updated_ts"] = now
        upsert_dispatch_queue_item(updated_item)

        save_dispatch_sms_record(
            {
                "id": uuid4().hex,
                "queue_id": item.get("id"),
                "owner_key": owner_key,
                "owner_ip": owner_ip,
                "mobile": sms_preview["mobile"],
                "content": sms_preview["content"],
                "status": status,
                "request_payload": request_payload,
                "response_payload": response_payload,
                "error_message": error_message,
                "created_ts": now,
            }
        )
        results.append(
            {
                "queue_id": item.get("id"),
                "status": status,
                "mobile": sms_preview["mobile"],
                "content": sms_preview["content"],
                "error_message": error_message,
            }
        )

    return {"ok": True, "items": results, "mock_mode": DISPATCH_MOCK_MODE}
