import os
from uuid import uuid4

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from shared.config.config import (
    BATCH_SIZE,
    CONF_THRESH,
    IMGSZ,
    PROMPT_MODEL_DEFAULT_CLASSES,
    PROMPT_MODEL_DEFAULT_CONF,
    UPLOAD_TEMP_DIR,
    VIDEO_FRAME_INTERVAL,
    get_upload_model_default,
    model_supports_text_prompt,
    resolve_model_path,
)
from shared.db.sqlite import get_job as get_saved_job
from modules.detection.services.upload_job_service import (
    get_upload_job_snapshot,
    request_upload_cancel,
    start_video_job,
    start_zip_job,
)
from shared.ownership.ownership import get_request_owner, job_matches_owner


upload_bp = Blueprint("upload", __name__, url_prefix="/upload")

_ALLOWED_EXTS = {".zip", ".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"}


def _parse_params(form) -> tuple:
    """Parse and validate common detection parameters from a form dict."""
    model_key = (form.get("model_key", "") or "").strip() or get_upload_model_default()
    conf_in = (form.get("conf", "") or "").strip()
    batch_in = (form.get("batch_size", "") or "").strip()
    imgsz_in = (form.get("imgsz", "") or "").strip()
    classes_raw = (form.get("classes", "") or "").strip()
    frame_interval_in = (form.get("frame_interval", "") or "").strip()
    default_conf = PROMPT_MODEL_DEFAULT_CONF if model_supports_text_prompt(model_key) else CONF_THRESH

    try:
        conf = max(0.01, min(1.0, float(conf_in))) if conf_in else default_conf
    except ValueError:
        conf = default_conf
    try:
        batch_size = max(1, min(64, int(batch_in))) if batch_in else BATCH_SIZE
    except ValueError:
        batch_size = BATCH_SIZE
    try:
        imgsz = max(320, min(1280, int(imgsz_in))) if imgsz_in else IMGSZ
    except ValueError:
        imgsz = IMGSZ
    try:
        frame_interval = max(1, min(60, int(frame_interval_in))) if frame_interval_in else VIDEO_FRAME_INTERVAL
    except ValueError:
        frame_interval = VIDEO_FRAME_INTERVAL

    if model_supports_text_prompt(model_key) and not classes_raw:
        classes_raw = PROMPT_MODEL_DEFAULT_CLASSES

    return conf, batch_size, imgsz, classes_raw, model_key, frame_interval


@upload_bp.post("/start")
def upload_start():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "未选择文件"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "文件为空"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _ALLOWED_EXTS:
        return jsonify({"ok": False, "error": f"不支持的文件类型 {ext}，请上传 ZIP 或 MP4/AVI/MOV/MKV/MPG/MPEG"}), 400

    owner_key, owner_ip = get_request_owner(request)
    conf, batch_size, imgsz, classes_raw, model_key, frame_interval = _parse_params(request.form)
    try:
        resolve_model_path(model_key)
    except Exception:
        return jsonify({"ok": False, "error": f"未找到可用模型: {model_key}"}), 400

    temp_dir = os.path.join(UPLOAD_TEMP_DIR, uuid4().hex)
    os.makedirs(temp_dir, exist_ok=True)

    if ext == ".zip":
        zip_path = os.path.join(temp_dir, filename)
        file.save(zip_path)
        job_id, err = start_zip_job(
            zip_path, filename, conf, batch_size, imgsz, classes_raw, model_key, owner_key, owner_ip, temp_dir
        )
    else:
        # Video: save to temp dir first so cv2 can open it by path
        video_path = os.path.join(temp_dir, filename)
        file.save(video_path)
        job_id, err = start_video_job(
            video_path, filename, frame_interval, conf, batch_size, imgsz,
            classes_raw, model_key, owner_key, owner_ip, temp_dir,
        )

    if not job_id:
        return jsonify({"ok": False, "error": err or "启动失败"}), 500

    return jsonify({"ok": True, "job_id": job_id})


@upload_bp.get("/progress/<job_id>")
def upload_progress(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_upload_job_snapshot(job_id)
    if job:
        if not job_matches_owner(job, owner_key, owner_ip):
            return jsonify({"ok": False, "error": "任务不存在"}), 404
    else:
        job = get_saved_job(job_id)
        if not job or job.get("job_type") != "upload" or not job_matches_owner(job, owner_key, owner_ip):
            return jsonify({"ok": False, "error": "任务不存在"}), 404

    return jsonify({
        "ok": True,
        "job": {
            k: job.get(k)
            for k in (
                "id", "status", "message", "total", "processed",
                "kept", "failed", "start_ts", "end_ts",
                "model_key", "source_name", "source_type",
            )
        },
    })


@upload_bp.post("/cancel/<job_id>")
def upload_cancel(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    ok = request_upload_cancel(job_id, owner_key, owner_ip)
    return jsonify({"ok": ok})


@upload_bp.get("/download/<job_id>")
def upload_download(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_upload_job_snapshot(job_id)
    if job is not None and not job_matches_owner(job, owner_key, owner_ip):
        return "任务未完成或不存在", 404
    if job is None:
        job = get_saved_job(job_id)
        if not job or job.get("job_type") != "upload" or not job_matches_owner(job, owner_key, owner_ip):
            return "任务未完成或不存在", 404
    if job.get("status") != "done":
        return "任务未完成或不存在", 404

    zip_path = job.get("zip_path")
    if not zip_path or not os.path.isfile(zip_path):
        return "结果文件不存在或已过期", 404

    src_name = job.get("source_name", "result")
    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"detected_{src_name}.zip",
    )
