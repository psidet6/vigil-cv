import json
import os
import time

from shared.config.config import (
    DEPLOYMENT_SLOTS_PATH,
    MODEL_DIR,
    MODEL_REGISTRY,
    get_deployment_slot_model_name,
    get_upload_model_default,
    list_upload_model_paths,
    resolve_model_path,
)


DEPLOYMENT_SLOT_LABELS = {
    "upload_default": "本地上传默认模型",
    "general": "数据库巡检通用模型",
    "helmet": "工地安全帽检测模型",
}

FOUNDATION_MODEL_NAMES = {"yolo26n.pt", "yolo26s.pt"}
PRODUCTION_MODEL_NAMES = {"helmet-detector.pt", "yolov8s-worldv2.pt"}

MODEL_LIFECYCLE_LABELS = {
    "active": "启用中",
    "archived": "已归档",
    "disabled": "已停用",
}

MODEL_USAGE_LABELS = {
    "training_base": "训练底模",
    "auto_label": "预标注",
    "upload_inference": "本地上传识别",
    "general_inference": "通用巡检",
    "specialized_inference": "专项巡检",
    "demo": "演示展示",
}

MODEL_CATEGORY_LABELS = {
    "foundation": "训练底模",
    "production": "在用模型",
    "published": "新发布模型",
    "custom": "自定义模型",
}


def _read_json_file(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _write_json_file(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _load_slot_registry() -> dict:
    payload = _read_json_file(DEPLOYMENT_SLOTS_PATH)
    if not isinstance(payload.get("slots"), dict):
        payload["slots"] = {}
    payload.setdefault("updated_ts", None)
    return payload


def _save_slot_registry(payload: dict) -> None:
    payload = dict(payload or {})
    payload["updated_ts"] = int(time.time())
    if not isinstance(payload.get("slots"), dict):
        payload["slots"] = {}
    _write_json_file(DEPLOYMENT_SLOTS_PATH, payload)


def _model_meta_path(model_name: str) -> str:
    stem, _ext = os.path.splitext(os.path.join(MODEL_DIR, model_name))
    return stem + ".meta.json"


def _load_model_metadata(model_name: str) -> dict:
    return _read_json_file(_model_meta_path(model_name))


def _model_category(model_name: str, metadata: dict) -> str:
    lower = model_name.lower()
    if metadata.get("source_job_id"):
        return "published"
    if lower in FOUNDATION_MODEL_NAMES:
        return "foundation"
    if lower in PRODUCTION_MODEL_NAMES:
        return "production"
    return "custom"


def _default_lifecycle_for_category(_category: str) -> str:
    return "active"


def _default_usages_for_model(model_name: str, category: str) -> list[str]:
    lower = (model_name or "").lower()
    usages = []
    if category == "foundation":
        usages.extend(["training_base", "auto_label"])
    if lower == "yolov8s-worldv2.pt":
        usages.extend(["auto_label", "general_inference"])
    if lower == "helmet-detector.pt":
        usages.append("specialized_inference")
    seen = set()
    result = []
    for item in usages:
        if item in MODEL_USAGE_LABELS and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _normalize_lifecycle(value: str, category: str) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in MODEL_LIFECYCLE_LABELS:
        return candidate
    return _default_lifecycle_for_category(category)


def _normalize_usages(usages, model_name: str, category: str) -> list[str]:
    if usages is None:
        return _default_usages_for_model(model_name, category)
    if isinstance(usages, str):
        raw_items = [part.strip().lower() for part in usages.split(",")]
    elif isinstance(usages, (list, tuple, set)):
        raw_items = [str(part or "").strip().lower() for part in usages]
    else:
        raw_items = []
    seen = set()
    result = []
    for item in raw_items:
        if not item or item not in MODEL_USAGE_LABELS or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _decorate_model_metadata(model_name: str, metadata: dict, category: str) -> dict:
    decorated = dict(metadata or {})
    decorated["display_name"] = str(decorated.get("display_name") or model_name).strip() or model_name
    decorated["lifecycle"] = _normalize_lifecycle(decorated.get("lifecycle"), category)
    decorated["usages"] = _normalize_usages(decorated.get("usages"), model_name, category)
    decorated["note"] = str(decorated.get("note") or "").strip()
    return decorated


def _current_model_name_for_slot(slot_key: str) -> str:
    if slot_key == "upload_default":
        return get_upload_model_default()
    if slot_key in MODEL_REGISTRY:
        return os.path.basename(resolve_model_path(slot_key))
    return ""


def _trim_history(history: list[dict], limit: int = 10) -> list[dict]:
    items = []
    seen = set()
    for entry in history:
        if not isinstance(entry, dict):
            continue
        model_name = os.path.basename(str(entry.get("model_name") or "").strip())
        if not model_name:
            continue
        key = (model_name.lower(), int(entry.get("changed_ts") or 0))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "model_name": model_name,
                "changed_ts": int(entry.get("changed_ts") or 0),
            }
        )
        if len(items) >= limit:
            break
    return items


def list_managed_models() -> list[dict]:
    registry = list_upload_model_paths()
    slot_assignments = {}
    for slot_key in DEPLOYMENT_SLOT_LABELS:
        current_name = _current_model_name_for_slot(slot_key)
        if current_name:
            slot_assignments.setdefault(current_name.lower(), []).append(slot_key)

    items = []
    for model_name in sorted(registry, key=str.lower):
        model_path = registry[model_name]
        raw_metadata = _load_model_metadata(model_name)
        category = _model_category(model_name, raw_metadata)
        metadata = _decorate_model_metadata(model_name, raw_metadata, category)
        stat = os.stat(model_path)
        summary = metadata.get("summary") or {}
        items.append(
            {
                "name": model_name,
                "display_name": metadata.get("display_name") or model_name,
                "path": model_path,
                "category": category,
                "category_label": MODEL_CATEGORY_LABELS.get(category, "自定义模型"),
                "lifecycle": metadata.get("lifecycle") or "active",
                "lifecycle_label": MODEL_LIFECYCLE_LABELS.get(metadata.get("lifecycle") or "active", "启用中"),
                "usages": metadata.get("usages") or [],
                "usage_labels": [
                    MODEL_USAGE_LABELS[item]
                    for item in (metadata.get("usages") or [])
                    if item in MODEL_USAGE_LABELS
                ],
                "note": metadata.get("note") or "",
                "size_bytes": stat.st_size,
                "modified_ts": int(stat.st_mtime),
                "source_job_id": metadata.get("source_job_id", ""),
                "dataset_id": metadata.get("dataset_id", ""),
                "dataset_name": metadata.get("dataset_name", ""),
                "base_model": metadata.get("base_model", ""),
                "confirmed_only": bool(metadata.get("confirmed_only")),
                "metrics": {
                    "precision": summary.get("metrics/precision(B)") or "",
                    "recall": summary.get("metrics/recall(B)") or "",
                    "mAP50": summary.get("metrics/mAP50(B)") or "",
                    "mAP50_95": summary.get("metrics/mAP50-95(B)") or "",
                },
                "metadata_path": _model_meta_path(model_name) if os.path.isfile(_model_meta_path(model_name)) else "",
                "slot_refs": slot_assignments.get(model_name.lower(), []),
                "slot_labels": [
                    DEPLOYMENT_SLOT_LABELS.get(slot_key, slot_key)
                    for slot_key in slot_assignments.get(model_name.lower(), [])
                ],
            }
        )
    return items


def get_model_slot_views() -> list[dict]:
    slot_registry = _load_slot_registry()
    views = []
    for slot_key, label in DEPLOYMENT_SLOT_LABELS.items():
        slot_state = (slot_registry.get("slots") or {}).get(slot_key) or {}
        current_name = _current_model_name_for_slot(slot_key)
        current_path = ""
        if current_name:
            current_path = os.path.join(MODEL_DIR, current_name)
            if not os.path.isfile(current_path):
                current_path = ""
        history = _trim_history(list(slot_state.get("history") or []))
        views.append(
            {
                "slot_key": slot_key,
                "label": label,
                "current_model": current_name,
                "current_path": os.path.abspath(current_path) if current_path else "",
                "changed_ts": int(slot_state.get("changed_ts") or 0) if slot_state.get("changed_ts") else None,
                "history": history,
                "has_override": bool(get_deployment_slot_model_name(slot_key)),
            }
        )
    return views


def set_model_slot(slot_key: str, model_name: str) -> dict:
    slot_key = str(slot_key or "").strip()
    if slot_key not in DEPLOYMENT_SLOT_LABELS:
        raise ValueError("unsupported slot")

    normalized_name = os.path.basename(str(model_name or "").strip())
    if not normalized_name:
        raise ValueError("model_name is required")

    available = list_upload_model_paths()
    if normalized_name not in available:
        raise FileNotFoundError("model not found")

    payload = _load_slot_registry()
    slots = payload.setdefault("slots", {})
    slot_state = slots.setdefault(slot_key, {})
    current_name = _current_model_name_for_slot(slot_key)
    now = int(time.time())

    if current_name.lower() == normalized_name.lower():
        slot_state["model_name"] = normalized_name
        slot_state["changed_ts"] = now
        slot_state["history"] = _trim_history(list(slot_state.get("history") or []))
        _save_slot_registry(payload)
        return next(item for item in get_model_slot_views() if item["slot_key"] == slot_key)

    history = list(slot_state.get("history") or [])
    if current_name:
        history.insert(0, {"model_name": current_name, "changed_ts": now})
    slot_state["history"] = _trim_history(history)
    slot_state["model_name"] = normalized_name
    slot_state["changed_ts"] = now
    _save_slot_registry(payload)
    return next(item for item in get_model_slot_views() if item["slot_key"] == slot_key)


def rollback_model_slot(slot_key: str) -> dict:
    slot_key = str(slot_key or "").strip()
    if slot_key not in DEPLOYMENT_SLOT_LABELS:
        raise ValueError("unsupported slot")

    payload = _load_slot_registry()
    slots = payload.setdefault("slots", {})
    slot_state = slots.setdefault(slot_key, {})
    history = list(slot_state.get("history") or [])
    available = list_upload_model_paths()

    target_name = ""
    remaining = []
    for entry in history:
        model_name = os.path.basename(str((entry or {}).get("model_name") or "").strip())
        if not model_name:
            continue
        if not target_name and model_name in available:
            target_name = model_name
            continue
        remaining.append({"model_name": model_name, "changed_ts": int((entry or {}).get("changed_ts") or 0)})

    if not target_name:
        raise ValueError("no rollback version available")

    current_name = _current_model_name_for_slot(slot_key)
    now = int(time.time())
    if current_name:
        remaining.insert(0, {"model_name": current_name, "changed_ts": now})

    slot_state["model_name"] = target_name
    slot_state["changed_ts"] = now
    slot_state["history"] = _trim_history(remaining)
    _save_slot_registry(payload)
    return next(item for item in get_model_slot_views() if item["slot_key"] == slot_key)


def get_model_registry_options() -> dict:
    return {
        "lifecycle_options": [{"value": key, "label": value} for key, value in MODEL_LIFECYCLE_LABELS.items()],
        "usage_options": [{"value": key, "label": value} for key, value in MODEL_USAGE_LABELS.items()],
    }


def update_model_metadata(model_name: str, *, display_name: str = "", lifecycle: str = "", usages=None, note: str = "") -> dict:
    normalized_name = os.path.basename(str(model_name or "").strip())
    if not normalized_name:
        raise ValueError("model_name is required")

    available = list_upload_model_paths()
    if normalized_name not in available:
        raise FileNotFoundError("model not found")

    current = _load_model_metadata(normalized_name)
    category = _model_category(normalized_name, current)
    payload = dict(current)
    payload["display_name"] = (display_name or normalized_name).strip() or normalized_name
    payload["lifecycle"] = _normalize_lifecycle(lifecycle, category)
    payload["usages"] = _normalize_usages(usages, normalized_name, category)
    payload["note"] = str(note or "").strip()
    _write_json_file(_model_meta_path(normalized_name), payload)

    for item in list_managed_models():
        if item.get("name") == normalized_name:
            return item
    raise LookupError("model not found")
