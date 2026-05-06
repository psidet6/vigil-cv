import hashlib
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from shared.config.config import (
    DISPATCH_DEFAULT_CONTENT,
    DISPATCH_DEFAULT_NOTE,
    DISPATCH_DEFAULT_TITLE,
    DISPATCH_FKSX,
    DISPATCH_GJDQ,
    DISPATCH_QSSX,
    DISPATCH_RWYID,
    DISPATCH_SJCSLY,
    DISPATCH_YWFZR,
    DISPATCH_YWFZRLXDH,
    DISPATCH_ZJLX,
    logger,
)
from modules.dispatch.repository.face_sql import fetch_dispatch_person_context
from modules.dispatch.services.store_service import (
    get_dispatch_queue_item,
    list_dispatch_queue,
    upsert_dispatch_queue_item,
)


def _now_ts() -> int:
    return int(time.time())


def _queue_id(owner_key: str, job_id: str, asset_id: str, face_index: int, person_id_no: str) -> str:
    raw = "|".join([owner_key or "", job_id or "", asset_id or "", str(face_index), person_id_no or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _guess_illegal_type(job: dict | None) -> str:
    if not job:
        return "事件待确认"
    model_key = str(job.get("model_key") or "").strip().lower()
    source_name = str(job.get("source_name") or "").strip()
    if model_key == "special":
        return "专项事件"
    if source_name:
        return source_name
    return "事件待确认"


def _region_context_from_db(person_id_no: str) -> dict[str, str]:
    try:
        payload = fetch_dispatch_person_context(person_id_no)
    except Exception as exc:
        logger.warning("failed to fetch dispatch region context for %s: %s", person_id_no, exc)
        return {}
    return payload or {}


def _build_source_summary(job: dict | None, asset_name: str, similarity_score: float) -> str:
    parts = []
    if job:
        if job.get("source_type"):
            parts.append(f"来源类型：{job.get('source_type')}")
        if job.get("source_name"):
            parts.append(f"来源任务：{job.get('source_name')}")
    if asset_name:
        parts.append(f"结果图：{asset_name}")
    if similarity_score:
        parts.append(f"相似度：{similarity_score:.4f}")
    return " / ".join(parts)


def _default_title(illegal_type: str) -> str:
    if illegal_type and illegal_type != "事件待确认":
        return f"{illegal_type}相关复核任务"
    return DISPATCH_DEFAULT_TITLE


def _default_content(illegal_type: str) -> str:
    if illegal_type and illegal_type != "事件待确认":
        return f"请复核该对象近期涉及的“{illegal_type}”，并反馈处理情况。"
    return DISPATCH_DEFAULT_CONTENT


def _normalize_region_code(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) >= 12:
        return raw
    return raw + "0" * (12 - len(raw))


DISPATCH_MINIMAL_PAYLOAD_FIELDS = (
    "rwdyid",
    "zlbt",
    "zlnr",
    "kssj",
    "jzsj",
    "qssx",
    "fksx",
    "hcdxid",
    "hcdxmc",
    "ywfzr",
    "ywfzrlxdh",
    "sssjDm",
    "sssjMc",
    "wxtid",
    "sjcsly",
    "zjhm",
    "zjlx",
    "lxdh",
    "xm",
    "dzmc",
    "xfdw",
)


def filter_dispatch_payload(payload: dict[str, Any], payload_mode: str = "minimal") -> dict[str, Any]:
    if str(payload_mode or "minimal").strip().lower() == "full":
        return dict(payload)
    return {key: payload.get(key, "") for key in DISPATCH_MINIMAL_PAYLOAD_FIELDS}


def build_dispatch_payload(
    queue_item: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    payload_mode: str = "minimal",
) -> dict[str, Any]:
    overrides = overrides or {}
    now = datetime.now()
    start_dt = overrides.get("kssj") or now.strftime("%Y-%m-%d %H:%M:%S")
    end_dt = overrides.get("jzsj") or (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    person_name = str(overrides.get("xm") or queue_item.get("person_name") or "").strip()
    person_id_no = str(overrides.get("zjhm") or queue_item.get("person_id_no") or "").strip()
    person_phone = str(overrides.get("lxdh") or queue_item.get("person_phone") or "").strip()
    sssj_dm = str(overrides.get("sssjDm") or queue_item.get("sssj_dm") or "").strip()
    payload = {
        # rwdyid is a fixed platform parameter; prefer the current configured value
        # so older queued items do not keep sending a stale historical value.
        "rwdyid": str(overrides.get("rwdyid") or DISPATCH_RWYID).strip(),
        "zlbt": str(overrides.get("zlbt") or _default_title(queue_item.get("illegal_type", ""))).strip(),
        "zlnr": str(overrides.get("zlnr") or _default_content(queue_item.get("illegal_type", ""))).strip(),
        "kssj": start_dt,
        "jzsj": end_dt,
        "qssx": str(overrides.get("qssx") or DISPATCH_QSSX).strip(),
        "fksx": str(overrides.get("fksx") or DISPATCH_FKSX).strip(),
        "bsz": person_id_no,
        "hcdxid": person_id_no,
        "hcdxmc": person_name,
        "hcdxdh": person_phone,
        "zlbz": str(overrides.get("zlbz") or DISPATCH_DEFAULT_NOTE).strip(),
        "ywfzr": str(overrides.get("ywfzr") or DISPATCH_YWFZR).strip(),
        "ywfzrlxdh": str(overrides.get("ywfzrlxdh") or DISPATCH_YWFZRLXDH).strip(),
        "sssjDm": sssj_dm,
        "sssjMc": str(overrides.get("sssjMc") or queue_item.get("sssj_mc") or "").strip(),
        "ssfjDm": str(overrides.get("ssfjDm") or queue_item.get("ssfj_dm") or "").strip(),
        "ssfjMc": str(overrides.get("ssfjMc") or queue_item.get("ssfj_mc") or "").strip(),
        "zbpcsdm": str(overrides.get("zbpcsdm") or queue_item.get("zbpcs_dm") or "").strip(),
        "zbpcsmc": str(overrides.get("zbpcsmc") or queue_item.get("zbpcs_mc") or "").strip(),
        "wxtid": str(overrides.get("wxtid") or uuid4().hex).strip(),
        "sjcsly": str(overrides.get("sjcsly") or queue_item.get("sjcsly") or DISPATCH_SJCSLY).strip(),
        "gjdq": str(overrides.get("gjdq") or DISPATCH_GJDQ).strip(),
        "zjlx": str(overrides.get("zjlx") or DISPATCH_ZJLX).strip(),
        "zjhm": person_id_no,
        "lxdh": person_phone,
        "xm": person_name,
        "pch": str(overrides.get("pch") or ("pch_" + now.strftime("%Y%m%d%H%M%S"))).strip(),
        "dzdm": str(overrides.get("dzdm") or "").strip(),
        "dzmc": str(overrides.get("dzmc") or queue_item.get("dzmc") or "").strip(),
        "xfdw": str(overrides.get("xfdw") or queue_item.get("xfdw") or sssj_dm).strip(),
    }
    return filter_dispatch_payload(payload, payload_mode=payload_mode)


def render_sms_template(queue_item: dict[str, Any], template: str, overrides: dict[str, Any] | None = None) -> str:
    overrides = overrides or {}
    text = str(template or "").strip()
    if not text:
        return ""
    payload = build_dispatch_payload(queue_item, overrides=overrides)
    values = {
        "xm": payload.get("xm", ""),
        "zjhm": payload.get("zjhm", ""),
        "lxdh": payload.get("lxdh", ""),
        "illegal_type": queue_item.get("illegal_type", ""),
        "deadline": payload.get("jzsj", ""),
        "zbpcsmc": payload.get("zbpcsmc", ""),
        "ywfzrlxdh": payload.get("ywfzrlxdh", ""),
        "source_name": queue_item.get("source_name", ""),
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value or ""))
    return text


def ingest_identity_results(
    owner_key: str,
    owner_ip: str,
    job: dict[str, Any] | None,
    identified_items: list[dict[str, Any]],
) -> dict[str, Any]:
    now = _now_ts()
    created = 0
    updated = 0
    items = []
    illegal_type = _guess_illegal_type(job)

    for item in identified_items or []:
        asset_id = str(item.get("asset_id") or "").strip()
        asset_name = str(item.get("asset_name") or "").strip()
        faces = item.get("faces") or []
        for face_index, face in enumerate(faces):
            matches = face.get("top_matches") or []
            if not matches:
                continue
            top_match = matches[0]
            person_id_no = str(top_match.get("id_number") or "").strip()
            if not person_id_no:
                continue
            region_context = _region_context_from_db(person_id_no)
            similarity_score = float(top_match.get("score") or 0)
            queue_id = _queue_id(owner_key, str((job or {}).get("id") or ""), asset_id, face_index, person_id_no)
            existing = get_dispatch_queue_item(queue_id)
            person_name = (
                str(region_context.get("xm") or "").strip()
                or str(top_match.get("name") or "").strip()
            )
            person_phone = str(region_context.get("lxdh") or "").strip()
            queue_item = {
                "id": queue_id,
                "owner_key": owner_key,
                "owner_ip": owner_ip,
                "source_job_id": str((job or {}).get("id") or "").strip(),
                "source_asset_id": asset_id,
                "source_job_type": str((job or {}).get("job_type") or "").strip(),
                "source_name": str((job or {}).get("source_name") or "").strip(),
                "source_type": str((job or {}).get("source_type") or "").strip(),
                "asset_name": asset_name,
                "face_index": face_index,
                "person_name": person_name,
                "person_id_no": person_id_no,
                "person_phone": person_phone,
                "similarity_score": similarity_score,
                "illegal_type": illegal_type,
                "sssj_dm": _normalize_region_code(region_context.get("ds", "")),
                "sssj_mc": str(region_context.get("dsmc") or "").strip(),
                "ssfj_dm": _normalize_region_code(region_context.get("ssxq", "")),
                "ssfj_mc": str(region_context.get("ssxqmc") or "").strip(),
                "zbpcs_dm": str(region_context.get("pcs") or "").strip(),
                "zbpcs_mc": str(region_context.get("pcsmc") or "").strip(),
                "dzmc": str(region_context.get("dz") or "").strip(),
                "rwdyid": DISPATCH_RWYID,
                "sjcsly": DISPATCH_SJCSLY,
                "dispatch_status": "pending",
                "sms_status": "pending" if person_phone else "need_phone",
                "last_error": "",
                "draft_payload": {},
                "identity_payload": {
                    "item": item,
                    "top_match": top_match,
                    "source_summary": _build_source_summary(job, asset_name, similarity_score),
                },
                "dispatch_response": existing.get("dispatch_response") if existing else {},
                "sms_preview": "",
                "created_ts": int(existing.get("created_ts") or now) if existing else now,
                "updated_ts": now,
            }
            queue_item["draft_payload"] = build_dispatch_payload(queue_item, payload_mode="minimal")
            upsert_dispatch_queue_item(queue_item)
            if existing:
                updated += 1
            else:
                created += 1
            items.append(queue_item)

    return {"created": created, "updated": updated, "items": items}


def list_dispatch_queue_items(owner_key: str, owner_ip: str, limit: int = 100) -> list[dict[str, Any]]:
    items = list_dispatch_queue(owner_key, owner_ip, limit=limit)
    for item in items:
        if not item.get("draft_payload"):
            item["draft_payload"] = build_dispatch_payload(item, payload_mode="minimal")
    return items


def get_dispatch_queue_detail(owner_key: str, owner_ip: str, queue_id: str) -> dict[str, Any]:
    item = get_dispatch_queue_item(queue_id)
    if not item:
        raise LookupError("queue item not found")
    stored_owner_key = str(item.get("owner_key") or "").strip()
    stored_owner_ip = str(item.get("owner_ip") or "").strip()
    if stored_owner_key:
        if stored_owner_key != owner_key:
            raise LookupError("queue item not found")
    elif stored_owner_ip and stored_owner_ip != owner_ip:
        raise LookupError("queue item not found")
    if not item.get("draft_payload"):
        item["draft_payload"] = build_dispatch_payload(item, payload_mode="minimal")
    return item


def refresh_dispatch_region_context(
    owner_key: str,
    owner_ip: str,
    queue_ids: list[str],
) -> dict[str, Any]:
    refreshed_items = []
    updated = 0
    skipped = 0
    now = _now_ts()

    for queue_id in queue_ids or []:
        item = get_dispatch_queue_detail(owner_key, owner_ip, queue_id)
        person_id_no = str(item.get("person_id_no") or "").strip()
        if not person_id_no:
            skipped += 1
            refreshed_items.append(item)
            continue

        region_context = _region_context_from_db(person_id_no)
        if not region_context:
            skipped += 1
            refreshed_items.append(item)
            continue

        updated_item = dict(item)
        updated_item["person_name"] = str(region_context.get("xm") or updated_item.get("person_name") or "").strip()
        updated_item["person_phone"] = str(region_context.get("lxdh") or updated_item.get("person_phone") or "").strip()
        updated_item["sssj_dm"] = _normalize_region_code(region_context.get("ds", ""))
        updated_item["sssj_mc"] = str(region_context.get("dsmc") or "").strip()
        updated_item["ssfj_dm"] = _normalize_region_code(region_context.get("ssxq", ""))
        updated_item["ssfj_mc"] = str(region_context.get("ssxqmc") or "").strip()
        updated_item["zbpcs_dm"] = str(region_context.get("pcs") or "").strip()
        updated_item["zbpcs_mc"] = str(region_context.get("pcsmc") or "").strip()
        updated_item["dzmc"] = str(region_context.get("dz") or "").strip()
        updated_item["rwdyid"] = DISPATCH_RWYID
        updated_item["updated_ts"] = now

        previous_payload = item.get("draft_payload") or {}
        payload_overrides = {
            "zlbt": previous_payload.get("zlbt", ""),
            "zlnr": previous_payload.get("zlnr", ""),
            "kssj": previous_payload.get("kssj", ""),
            "jzsj": previous_payload.get("jzsj", ""),
            "qssx": previous_payload.get("qssx", ""),
            "fksx": previous_payload.get("fksx", ""),
            "zlbz": previous_payload.get("zlbz", ""),
            "ywfzr": previous_payload.get("ywfzr", ""),
            "ywfzrlxdh": previous_payload.get("ywfzrlxdh", ""),
            "wxtid": previous_payload.get("wxtid", ""),
            "sjcsly": previous_payload.get("sjcsly", ""),
            "gjdq": previous_payload.get("gjdq", ""),
            "zjlx": previous_payload.get("zjlx", ""),
            "pch": previous_payload.get("pch", ""),
            "xfdw": previous_payload.get("xfdw", ""),
        }
        updated_item["draft_payload"] = build_dispatch_payload(
            updated_item,
            overrides=payload_overrides,
            payload_mode="minimal",
        )
        upsert_dispatch_queue_item(updated_item)
        refreshed_items.append(updated_item)
        updated += 1

    return {"updated": updated, "skipped": skipped, "items": refreshed_items}
