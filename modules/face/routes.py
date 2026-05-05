import os

from flask import Blueprint, jsonify, request, send_file, url_for

from shared.db.sqlite import get_job as get_saved_job
from shared.db.sqlite import save_job
from shared.job_lookup import resolve_job
from modules.detection.services.result_store_service import (
    attach_identity_to_manifest_items,
    load_identity_report_for_manifest,
    load_result_manifest,
    persist_identity_results,
)
from shared.events import emit
from modules.face.services.library_service import (
    get_face_library_photo_path,
    get_face_library_status,
    identify_image_path,
    list_persons,
)
from modules.face.services.library_task_service import (
    get_face_library_task,
    get_running_face_library_task,
    list_face_library_tasks,
    start_face_library_task,
)
from shared.config.config import logger
from shared.ownership.ownership import get_request_owner


face_bp = Blueprint("face", __name__, url_prefix="/face")


def _resolve_job(job_id: str) -> dict | None:
    return resolve_job(job_id)


def _job_manifest(job_id: str) -> tuple[dict | None, dict | None]:
    job = _resolve_job(job_id)
    if not job:
        return None, None
    manifest_path = job.get("result_manifest_path")
    if not manifest_path or not os.path.isfile(manifest_path):
        return job, None
    try:
        return job, load_result_manifest(manifest_path)
    except Exception:
        return job, None


@face_bp.get("/results/<job_id>")
def list_job_results(job_id: str):
    job, manifest = _job_manifest(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    if manifest is None:
        return jsonify({"ok": False, "error": "result manifest not found"}), 404

    _report_path, identity_report = load_identity_report_for_manifest(job.get("result_manifest_path") or "")
    items = []
    for item in attach_identity_to_manifest_items(manifest, identity_report):
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "origin_name": item.get("origin_name") or item.get("name"),
                "size_bytes": item.get("size_bytes", 0),
                "asset_url": url_for("face.result_asset", job_id=job_id, asset_id=item.get("id")),
                "identity": item.get("identity"),
            }
        )

    return jsonify(
        {
            "ok": True,
            "job": {
                "id": job.get("id"),
                "job_type": job.get("job_type"),
                "source_type": job.get("source_type"),
                "source_name": job.get("source_name"),
                "status": job.get("status"),
                "result_count": len(items),
            },
            "items": items,
            "identity_summary": identity_report.get("summary") or {},
        }
    )


@face_bp.get("/results/<job_id>/asset/<asset_id>")
def result_asset(job_id: str, asset_id: str):
    job, manifest = _job_manifest(job_id)
    if job is None or manifest is None:
        return "result manifest not found", 404

    safe_asset_id = os.path.basename(asset_id)
    for item in manifest.get("items", []):
        if item.get("id") == safe_asset_id:
            path = item.get("path")
            if path and os.path.isfile(path):
                return send_file(path)
            break
    return "asset not found", 404


@face_bp.get("/library/status")
def face_library_status():
    return jsonify(
        {
            "ok": True,
            "library": get_face_library_status(),
            "task": get_running_face_library_task(),
        }
    )


@face_bp.get("/library/photo/<person_id>")
def face_library_photo(person_id: str):
    path = get_face_library_photo_path(person_id)
    if not path or not os.path.isfile(path):
        return "photo not found", 404
    return send_file(path)


@face_bp.get("/library/persons")
def face_library_persons():
    try:
        page = int(request.args.get("page", 1))
    except Exception:
        page = 1
    try:
        page_size = int(request.args.get("page_size", 12))
    except Exception:
        page_size = 12
    keyword = (request.args.get("keyword", "") or "").strip()
    result = list_persons(page=page, page_size=page_size, keyword=keyword)
    return jsonify({"ok": True, **result})


@face_bp.get("/library/tasks")
def face_library_tasks_list():
    tasks = list_face_library_tasks()
    tasks.sort(key=lambda t: t.get("start_ts", 0), reverse=True)
    return jsonify({"ok": True, "tasks": tasks})


@face_bp.post("/library/rebuild")
def face_library_rebuild():
    task, started = start_face_library_task("rebuild")
    return jsonify({"ok": True, "started": started, "task": task})


@face_bp.post("/library/sync")
def face_library_sync():
    task, started = start_face_library_task("sync")
    return jsonify({"ok": True, "started": started, "task": task})


@face_bp.get("/library/task/<task_id>")
def face_library_task(task_id: str):
    task = get_face_library_task(task_id)
    if task is None:
        return jsonify({"ok": False, "error": "task not found"}), 404
    return jsonify({"ok": True, "task": task})


@face_bp.post("/identify")
def identify_faces():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    job_id = (payload.get("job_id", "") or "").strip()
    asset_ids = payload.get("asset_ids") or []
    try:
        top_k = int(payload.get("top_k") or 5)
    except Exception:
        top_k = 5

    if not job_id:
        return jsonify({"ok": False, "error": "job_id is required"}), 400
    if not isinstance(asset_ids, list) or not asset_ids:
        return jsonify({"ok": False, "error": "asset_ids is required"}), 400

    job, manifest = _job_manifest(job_id)
    if job is None or manifest is None:
        return jsonify({"ok": False, "error": "result manifest not found"}), 404

    selected = []
    selected_ids = {os.path.basename(str(asset_id)) for asset_id in asset_ids if str(asset_id).strip()}
    for item in manifest.get("items", []):
        if item.get("id") in selected_ids and item.get("path") and os.path.isfile(item["path"]):
            selected.append(item)

    if not selected:
        return jsonify({"ok": False, "error": "no valid selected assets found"}), 400

    items = []
    for item in selected:
        result = identify_image_path(item["path"], top_k=top_k)
        for face in result.get("faces", []):
            for match in face.get("top_matches", []):
                person_id = match.get("id_number")
                if person_id:
                    match["photo_url"] = url_for("face.face_library_photo", person_id=person_id)
        items.append(
            {
                "asset_id": item.get("id"),
                "asset_name": item.get("name"),
                "asset_url": url_for("face.result_asset", job_id=job_id, asset_id=item.get("id")),
                **result,
            }
        )

    manifest_path = (job or {}).get("result_manifest_path") or ""
    identity_report_path = ""
    identity_report = {"summary": {}, "items": []}
    if manifest_path:
        identity_report_path, identity_report = persist_identity_results(manifest_path, job_id, items)
        if job is not None:
            snapshot = dict(job)
            snapshot["identity_result_path"] = identity_report_path
            snapshot["identity_summary"] = identity_report.get("summary") or {}
            try:
                save_job(snapshot)
            except Exception as exc:
                logger.exception("failed to persist identity summary for job %s: %s", job_id, exc)

    dispatch_flow = {"created": 0, "updated": 0, "items": []}
    try:
        emit(
            "identity_matched",
            owner_key=owner_key,
            owner_ip=owner_ip,
            job=job,
            items=items,
            result=dispatch_flow,
        )
    except Exception as exc:
        logger.exception("failed to flow identity results into dispatch queue for job %s: %s", job_id, exc)

    return jsonify(
        {
            "ok": True,
            "items": items,
            "library": get_face_library_status(),
            "identity_summary": identity_report.get("summary") or {},
            "identity_result_path": identity_report_path,
            "dispatch_flow": {
                "created": dispatch_flow.get("created", 0),
                "updated": dispatch_flow.get("updated", 0),
            },
        }
    )
