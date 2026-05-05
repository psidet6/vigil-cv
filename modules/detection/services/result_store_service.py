import io
import json
import os
import re
import time
from typing import Any

from PIL import Image

from shared.config.config import RESULTS_DIR

IDENTITY_REPORT_FILENAME = "identity_results.json"


def _safe_filename(name: str, fallback: str) -> str:
    base = os.path.basename((name or "").strip()) or fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned or fallback


def create_result_store(job_id: str, job_type: str, source_type: str, source_name: str) -> dict[str, Any]:
    result_dir = os.path.join(RESULTS_DIR, job_id)
    assets_dir = os.path.join(result_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    return {
        "job_id": job_id,
        "job_type": job_type,
        "source_type": source_type,
        "source_name": source_name,
        "result_dir": result_dir,
        "assets_dir": assets_dir,
        "manifest_path": os.path.join(result_dir, "manifest.json"),
        "items": [],
    }


def _unique_path(directory: str, filename: str) -> tuple[str, str]:
    root, ext = os.path.splitext(filename)
    candidate = filename
    index = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{root}_{index}{ext}"
        index += 1
    return os.path.join(directory, candidate), candidate


def add_result_bytes(
    store: dict[str, Any],
    asset_name: str,
    payload: bytes,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_name = _safe_filename(asset_name, "result.jpg")
    full_path, stored_name = _unique_path(store["assets_dir"], safe_name)
    with open(full_path, "wb") as fh:
        fh.write(payload)

    item = {
        "id": stored_name,
        "name": stored_name,
        "path": os.path.abspath(full_path),
        "size_bytes": len(payload),
    }
    if extra:
        item.update(extra)
    store["items"].append(item)
    return item


def add_result_image(
    store: dict[str, Any],
    asset_name: str,
    image: Image.Image,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_name = os.path.splitext(_safe_filename(asset_name, "result.jpg"))[0] + ".jpg"
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    return add_result_bytes(store, output_name, buf.getvalue(), extra=extra)


def finalize_result_store(store: dict[str, Any]) -> str:
    manifest = {
        "job_id": store["job_id"],
        "job_type": store["job_type"],
        "source_type": store["source_type"],
        "source_name": store["source_name"],
        "result_dir": os.path.abspath(store["result_dir"]),
        "assets_dir": os.path.abspath(store["assets_dir"]),
        "result_count": len(store["items"]),
        "items": store["items"],
    }
    with open(store["manifest_path"], "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return store["manifest_path"]


def load_result_manifest(manifest_path: str) -> dict[str, Any]:
    with open(manifest_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _identity_report_path(manifest_path: str) -> str:
    if not manifest_path:
        return ""
    return os.path.join(os.path.dirname(os.path.abspath(manifest_path)), IDENTITY_REPORT_FILENAME)


def load_identity_report(report_path: str) -> dict[str, Any]:
    if not report_path or not os.path.isfile(report_path):
        return {"items": [], "summary": {}}
    with open(report_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if "items" not in data or not isinstance(data["items"], list):
        data["items"] = []
    if "summary" not in data or not isinstance(data["summary"], dict):
        data["summary"] = {}
    return data


def load_identity_report_for_manifest(manifest_path: str) -> tuple[str, dict[str, Any]]:
    report_path = _identity_report_path(manifest_path)
    if not report_path:
        return "", {"items": [], "summary": {}}
    return report_path, load_identity_report(report_path)


def summarize_identity_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "recognized_asset_count": len(items),
        "matched_asset_count": 0,
        "no_match_asset_count": 0,
        "no_face_asset_count": 0,
        "low_quality_asset_count": 0,
        "error_asset_count": 0,
        "library_unavailable_asset_count": 0,
        "total_face_count": 0,
        "matched_face_count": 0,
    }
    status_key_map = {
        "matched": "matched_asset_count",
        "no_match": "no_match_asset_count",
        "no_face": "no_face_asset_count",
        "low_quality": "low_quality_asset_count",
        "error": "error_asset_count",
        "library_unavailable": "library_unavailable_asset_count",
    }
    for item in items:
        status = str(item.get("status") or "").strip()
        mapped_key = status_key_map.get(status)
        if mapped_key:
            summary[mapped_key] += 1
        faces = item.get("faces") or []
        summary["total_face_count"] += len(faces)
        for face in faces:
            if face.get("top_matches"):
                summary["matched_face_count"] += 1
    return summary


def persist_identity_results(
    manifest_path: str,
    job_id: str,
    identified_items: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    report_path, existing = load_identity_report_for_manifest(manifest_path)
    if not report_path:
        raise ValueError("manifest_path is required to persist identity results")
    existing_map = {
        str(item.get("asset_id")): item
        for item in existing.get("items", [])
        if isinstance(item, dict) and item.get("asset_id")
    }
    now_ts = int(time.time())

    for item in identified_items:
        asset_id = str(item.get("asset_id") or "").strip()
        if not asset_id:
            continue
        merged = dict(item)
        merged["recognized_ts"] = now_ts
        existing_map[asset_id] = merged

    merged_items = sorted(
        existing_map.values(),
        key=lambda item: (
            str(item.get("asset_name") or ""),
            str(item.get("asset_id") or ""),
        ),
    )
    report = {
        "job_id": job_id,
        "updated_ts": now_ts,
        "summary": summarize_identity_items(merged_items),
        "items": merged_items,
    }
    report["summary"]["updated_ts"] = now_ts
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report_path, report


def attach_identity_to_manifest_items(
    manifest: dict[str, Any],
    identity_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    identity_map = {}
    if identity_report:
        identity_map = {
            str(item.get("asset_id")): item
            for item in identity_report.get("items", [])
            if isinstance(item, dict) and item.get("asset_id")
        }

    items = []
    for item in manifest.get("items", []):
        payload = dict(item)
        payload["identity"] = identity_map.get(str(item.get("id")))
        items.append(payload)
    return items
