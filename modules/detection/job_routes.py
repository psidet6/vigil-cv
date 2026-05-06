import os
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from shared.config.config import (
    BATCH_SIZE,
    CONF_THRESH,
    IMGSZ,
    MODEL_DEFAULT,
    MODEL_REGISTRY,
    get_train_base_model_options,
    get_upload_model_default,
    get_upload_model_options,
)
from shared.db.postgres import fetch_image_urls
from shared.db.sqlite import get_job as get_saved_job
from shared.db.sqlite import list_all_jobs as list_all_saved_jobs
from modules.detection.services.job_service import (
    get_job_snapshot,
    list_running_jobs,
    request_cancel,
    start_detection_job,
)
from modules.detection.services.result_store_service import (
    attach_identity_to_manifest_items,
    load_identity_report,
    load_result_manifest,
)
from shared.utils.helpers import (
    default_time_range,
    ensure_hours_list,
    format_timestamp,
    parse_and_normalize_dt,
    to_datetime_local_str,
)
from shared.ownership.ownership import get_request_owner, job_matches_owner


job_bp = Blueprint("job", __name__)


def _get_face_library_status() -> dict:
    """Lazy import to avoid circular dependency on face module at import time."""
    from modules.face.services.library_service import get_face_library_status
    return get_face_library_status()


def _progress_payload(job: dict) -> dict:
    data = {
        key: job.get(key)
        for key in (
            "id",
            "status",
            "message",
            "total",
            "processed",
            "kept",
            "notfound",
            "failed",
            "downloaded",
            "start_ts",
            "end_ts",
            "owner_ip",
            "model_key",
        )
    }
    data["zip_parts_count"] = len(job.get("zip_parts") or [])
    return data


def _history_summary_payload(record: dict) -> dict:
    identity_summary = record.get("identity_summary") or {}
    return {
        "id": record.get("id"),
        "job_type": record.get("job_type", "database"),
        "source_name": record.get("source_name", ""),
        "source_type": record.get("source_type", ""),
        "start_ts": format_timestamp(record.get("start_ts")),
        "end_ts": format_timestamp(record.get("end_ts")),
        "status": record.get("status"),
        "kept": record.get("kept", 0),
        "total": record.get("total", 0),
        "zip_parts_count": len(record.get("zip_parts") or []),
        "model_key": record.get("model_key", MODEL_DEFAULT),
        "identity_summary": identity_summary,
        "detail_url": url_for("job.history_detail_page", job_id=record.get("id")),
        "download_url": url_for("file.download_zip", job_id=record.get("id")),
    }


@job_bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return redirect(url_for("job.index"))

    kssj, jssj = default_time_range()
    try:
        kssj_dt = datetime.strptime(kssj, "%Y-%m-%d %H:%M:%S")
        jssj_dt = datetime.strptime(jssj, "%Y-%m-%d %H:%M:%S")
    except Exception:
        now = datetime.now()
        kssj_dt = now
        jssj_dt = now

    return render_template(
        "index.html",
        kssj=kssj,
        jssj=jssj,
        kssj_local=to_datetime_local_str(kssj_dt),
        jssj_local=to_datetime_local_str(jssj_dt),
        conf_default=CONF_THRESH,
        batch_default=BATCH_SIZE,
        imgsz_default=IMGSZ,
        model_default=MODEL_DEFAULT,
        upload_model_default=get_upload_model_default(),
        upload_models=get_upload_model_options(),
        train_base_models=get_train_base_model_options(),
    )


@job_bp.route("/start", methods=["GET", "POST", "OPTIONS"])
def start_job():
    if request.method == "OPTIONS":
        return ("", 204)

    form = request.form if request.method == "POST" else request.args
    kssj_in = (form.get("kssj", "") or "").strip()
    jssj_in = (form.get("jssj", "") or "").strip()
    hours_raw = request.form.getlist("hours") if request.method == "POST" else request.args.getlist("hours")
    hours = ensure_hours_list(hours_raw)

    conf_in = (form.get("conf", "") or "").strip()
    batch_in = (form.get("batch_size", "") or "").strip()
    imgsz_in = (form.get("imgsz", "") or "").strip()
    classes_raw = (form.get("classes", "") or "").strip()
    model_key = (form.get("model_key", MODEL_DEFAULT) or MODEL_DEFAULT).strip()

    if model_key not in MODEL_REGISTRY:
        return jsonify({"ok": False, "error": f"非法 model_key: {model_key}"}), 400

    try:
        kssj = parse_and_normalize_dt(kssj_in)
        jssj = parse_and_normalize_dt(jssj_in)
    except Exception:
        kssj = kssj_in
        jssj = jssj_in

    try:
        url_and_times = fetch_image_urls(kssj, jssj, hours, model_key)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"数据库查询失败: {exc}"}), 500

    if not url_and_times:
        return jsonify({"ok": False, "error": "未查询到图片 URL"}), 400

    conf_val = CONF_THRESH
    try:
        if conf_in:
            conf_val = max(0.0, min(1.0, float(conf_in)))
    except Exception:
        pass

    batch_val = BATCH_SIZE
    try:
        if batch_in:
            batch_val = max(1, int(batch_in))
    except Exception:
        pass

    imgsz_val = IMGSZ
    try:
        if imgsz_in:
            imgsz_val = max(64, int(imgsz_in))
    except Exception:
        pass

    owner_key, owner_ip = get_request_owner(request)
    job = start_detection_job(
        url_and_times,
        conf_val,
        batch_val,
        imgsz_val,
        classes_raw,
        model_key,
        owner_key,
        owner_ip,
    )
    return jsonify({"ok": True, "job_id": job["id"], "total": len(url_and_times)})


@job_bp.get("/progress/<job_id>")
def get_progress(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_job_snapshot(job_id)
    if job is not None:
        if not job_matches_owner(job, owner_key, owner_ip):
            return jsonify({"ok": False, "error": "job not found"}), 404
        return jsonify({"ok": True, "job": _progress_payload(job)})

    saved_job = get_saved_job(job_id)
    if saved_job is None or not job_matches_owner(saved_job, owner_key, owner_ip):
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": _progress_payload(saved_job)})


@job_bp.post("/cancel/<job_id>")
def cancel_job(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    if not request_cancel(job_id, owner_key, owner_ip):
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True})


@job_bp.get("/jobs")
def list_jobs():
    owner_key, owner_ip = get_request_owner(request)
    running = list_running_jobs(owner_key, owner_ip)
    return jsonify({"ok": True, "running_count": len(running), "running": running})


@job_bp.get("/history")
def history():
    limit_raw = request.args.get("limit", "50")
    try:
        limit = int(limit_raw)
    except Exception:
        limit = 50

    records = list_all_saved_jobs(limit=limit)
    items = [_history_summary_payload(record) for record in records]
    return jsonify({"ok": True, "jobs": items})


@job_bp.get("/history-page")
def history_page():
    return render_template("modules/detection/history/history.html")


@job_bp.get("/history-page/<job_id>")
def history_detail_page(job_id: str):
    return render_template("modules/detection/history/history_detail.html", job_id=job_id)


@job_bp.get("/history/<job_id>")
def history_detail(job_id: str):
    record = get_saved_job(job_id)
    if record is None:
        return jsonify({"ok": False, "error": "job not found"}), 404

    manifest = None
    manifest_path = record.get("result_manifest_path")
    if manifest_path and os.path.isfile(manifest_path):
        try:
            manifest = load_result_manifest(manifest_path)
        except Exception:
            manifest = None

    identity_report = {"summary": {}, "items": []}
    identity_path = record.get("identity_result_path")
    if identity_path and os.path.isfile(identity_path):
        try:
            identity_report = load_identity_report(identity_path)
        except Exception:
            identity_report = {"summary": {}, "items": []}

    items = []
    if manifest is not None:
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

    payload = {
        "ok": True,
        "job": {
            **_history_summary_payload(record),
            "message": record.get("message", ""),
            "downloaded": record.get("downloaded", 0),
            "notfound": record.get("notfound", 0),
            "failed": record.get("failed", 0),
            "summary_text": record.get("summary_text", ""),
            "result_count": len(items),
            "summary_url": url_for("file.download_summary", job_id=job_id),
            "download_parts": [
                {
                    "name": part.get("name"),
                    "url": url_for("file.download_zip_part", job_id=job_id, part=part.get("name")),
                }
                for part in (record.get("zip_parts") or [])
                if part.get("name")
            ] if len(record.get("zip_parts") or []) > 1 else [],
        },
        "items": items,
        "identity_summary": identity_report.get("summary") or (record.get("identity_summary") or {}),
        "library": _get_face_library_status(),
    }
    return jsonify(payload)


@job_bp.get("/api/dashboard/stats")
def dashboard_stats():
    """Return real-time header stats: today's identity matches and pending dispatch count."""
    import sqlite3 as _sqlite3
    import time as _time
    from shared.config.config import SQLITE_DB_PATH as _DB_PATH

    owner_key, owner_ip = get_request_owner(request)

    today_start = int(_time.time()) - (_time.time() % 86400)  # midnight UTC approx
    # More accurate: midnight local calendar day
    import datetime as _dt
    now_local = _dt.datetime.now()
    today_midnight = _dt.datetime(now_local.year, now_local.month, now_local.day).timestamp()

    today_matched = 0
    pending_dispatch = 0

    try:
        conn = _sqlite3.connect(_DB_PATH, timeout=5)
        conn.row_factory = _sqlite3.Row

        # "今日命中" = dispatch_queue entries created today for this user
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM dispatch_queue WHERE created_ts >= ? AND (owner_key=? OR owner_ip=?)",
            (int(today_midnight), owner_key, owner_ip),
        ).fetchone()
        today_matched = row["cnt"] if row else 0

        # "待推送" = dispatch_queue entries pending for this user
        row2 = conn.execute(
            "SELECT COUNT(*) AS cnt FROM dispatch_queue WHERE dispatch_status='pending' AND (owner_key=? OR owner_ip=?)",
            (owner_key, owner_ip),
        ).fetchone()
        pending_dispatch = row2["cnt"] if row2 else 0

        conn.close()
    except Exception:
        pass

    return jsonify({"ok": True, "today_matched": today_matched, "pending_dispatch": pending_dispatch})
