import io
import os
import shutil
import threading
import time
import zipfile
from typing import Optional, Set
from uuid import uuid4

import cv2
from PIL import Image

from shared.config.config import (
    BATCH_SIZE,
    CONF_THRESH,
    IMGSZ,
    OUTPUT_DIR,
    get_upload_model_default,
    logger,
    model_supports_text_prompt,
)
from shared.db.sqlite import get_job as get_saved_job
from shared.db.sqlite import save_job
from shared.task_queue import submit_task
from modules.detection.services.result_store_service import (
    add_result_bytes,
    create_result_store,
    finalize_result_store,
)
from shared.inference.infer_service import _predict_batch, get_model
from shared.ownership.ownership import job_matches_owner


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

UPLOAD_JOBS: dict[str, dict] = {}
UPLOAD_JOBS_LOCK = threading.Lock()
TERMINAL_STATUSES = {"done", "error", "canceled", "interrupted"}


def _upload_snapshot(job: dict) -> dict:
    return {key: value for key, value in job.items() if key != "cancel"}


def get_upload_job_snapshot(job_id: str) -> dict | None:
    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is not None:
            return _upload_snapshot(job)

    saved_job = get_saved_job(job_id)
    if saved_job is None or saved_job.get("job_type") != "upload":
        return None
    return saved_job


def request_upload_cancel(job_id: str, owner_key: str = "", owner_ip: str = "") -> bool:
    snapshot = None
    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is not None and job_matches_owner(job, owner_key, owner_ip):
            job["cancel"].set()
            if job.get("status") not in TERMINAL_STATUSES:
                job["status"] = "canceled"
                job["message"] = "cancel requested"
                job["end_ts"] = job.get("end_ts") or int(time.time())
            snapshot = _upload_snapshot(job)

    if snapshot is not None:
        save_job(snapshot)
        return True

    job = get_saved_job(job_id)
    if job is None or job.get("job_type") != "upload" or not job_matches_owner(job, owner_key, owner_ip):
        return False

    if job.get("status") in TERMINAL_STATUSES:
        return True

    job["status"] = "canceled"
    job["message"] = "cancel requested"
    job["end_ts"] = job.get("end_ts") or int(time.time())
    save_job(job)
    return True


def _save_job_state(snapshot: dict) -> None:
    try:
        save_job(snapshot)
    except Exception as exc:
        logger.exception("failed to persist upload job %s: %s", snapshot.get("id"), exc)


def _sync_cancel_state(job_id: str) -> bool:
    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is None:
            return False
        if job["cancel"].is_set():
            if job.get("status") not in TERMINAL_STATUSES:
                job["status"] = "canceled"
                job["message"] = job.get("message") or "cancel requested"
            return True

    saved_job = get_saved_job(job_id)
    if saved_job is None or saved_job.get("job_type") != "upload" or saved_job.get("status") != "canceled":
        return False

    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is None:
            return True
        job["cancel"].set()
        if job.get("status") not in TERMINAL_STATUSES:
            job["status"] = "canceled"
            job["message"] = saved_job.get("message") or "cancel requested"
            if saved_job.get("end_ts"):
                job["end_ts"] = saved_job.get("end_ts")
    return True


def _persist_job_state(job_id: str) -> None:
    _sync_cancel_state(job_id)
    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is None:
            return
        snapshot = _upload_snapshot(job)
    _save_job_state(snapshot)


def _new_upload_job(total: int, source_name: str, source_type: str, status: str = "queued") -> dict:
    return {
        "job_type": "upload",
        "id": uuid4().hex,
        "source_name": source_name,
        "source_type": source_type,
        "source_path": "",
        "temp_dir": "",
        "frame_interval": None,
        "status": status,
        "message": status,
        "total": total,
        "processed": 0,
        "kept": 0,
        "failed": 0,
        "start_ts": int(time.time()),
        "end_ts": None,
        "zip_path": None,
        "zip_parts": [],
        "result_dir": "",
        "result_manifest_path": "",
        "conf_thresh": CONF_THRESH,
        "batch_size": BATCH_SIZE,
        "imgsz": IMGSZ,
        "classes_raw": "",
        "model_key": get_upload_model_default(),
        "owner_key": "",
        "owner_ip": "",
    }


def _close_batch_images(batch: list[tuple[str, Image.Image]]) -> None:
    for _name, img in batch:
        try:
            img.close()
        except Exception:
            pass


def _resolve_model_filters(model_key: str, model, classes_raw: str) -> tuple[Optional[Set[int]], list[str] | None]:
    allowed_classes: Optional[Set[int]] = None
    prompt_classes: list[str] | None = None

    if model_supports_text_prompt(model_key):
        prompt_classes = [token.strip() for token in classes_raw.split(",") if token.strip()] or None
        return allowed_classes, prompt_classes

    names = getattr(model, "names", None)
    if classes_raw and names:
        indexes: Set[int] = set()
        if isinstance(names, dict):
            name_map = {str(value).lower(): int(key) for key, value in names.items()}
        else:
            name_map = {str(value).lower(): index for index, value in enumerate(names)}
        for token in [value.strip() for value in classes_raw.split(",") if value.strip()]:
            if token.isdigit():
                indexes.add(int(token))
            else:
                mapped = name_map.get(token.lower())
                if mapped is not None:
                    indexes.add(mapped)
        if indexes:
            allowed_classes = indexes

    return allowed_classes, prompt_classes


def _is_upload_canceled(job_id: str) -> bool:
    return _sync_cancel_state(job_id)


def _mark_upload_failed_item(job_id: str) -> None:
    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is None:
            return
        job["processed"] += 1
        job["failed"] += 1
        if job["processed"] > (job.get("total") or 0):
            job["total"] = job["processed"]


def _process_batch(
    job_id: str,
    batch: list[tuple[str, Image.Image]],
    model,
    conf_thresh: float,
    allowed_classes: Optional[Set[int]],
    imgsz: int,
    model_key: str,
    prompt_classes: list[str] | None,
    result_zip: zipfile.ZipFile,
    result_store: dict,
    kept_sequence: int,
) -> int:
    batch_names = [name for name, _ in batch]
    batch_imgs = [img for _, img in batch]

    try:
        hits = _predict_batch(batch_imgs, model, conf_thresh, allowed_classes, imgsz, model_key, prompt_classes)
    except Exception as exc:
        with UPLOAD_JOBS_LOCK:
            job = UPLOAD_JOBS.get(job_id)
            if job is not None:
                job["processed"] += len(batch)
                job["failed"] += len(batch)
                job["message"] = str(exc)
                if job["processed"] > (job.get("total") or 0):
                    job["total"] = job["processed"]
        logger.exception("upload inference failed for job %s: %s", job_id, exc)
        raise RuntimeError(f"inference failed: {exc}") from exc

    kept_delta = 0
    try:
        for name, img, hit in zip(batch_names, batch_imgs, hits):
            if not hit:
                continue
            kept_sequence += 1
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            payload = buf.getvalue()
            output_name = f"{kept_sequence:07d}_{os.path.splitext(name)[0]}.jpg"
            result_zip.writestr(output_name, payload)
            add_result_bytes(result_store, output_name, payload, extra={"origin_name": name})
            kept_delta += 1
    finally:
        _close_batch_images(batch)

    with UPLOAD_JOBS_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if job is not None:
            job["processed"] += len(batch)
            job["kept"] += kept_delta
            if job["processed"] > (job.get("total") or 0):
                job["total"] = job["processed"]

    return kept_sequence


def _run_zip_source(
    job_id: str,
    zip_path: str,
    batch_size: int,
    model,
    conf_thresh: float,
    allowed_classes: Optional[Set[int]],
    imgsz: int,
    model_key: str,
    prompt_classes: list[str] | None,
    result_zip: zipfile.ZipFile,
    result_store: dict,
) -> int:
    batch: list[tuple[str, Image.Image]] = []
    kept_sequence = 0

    with zipfile.ZipFile(zip_path) as source_zip:
        for entry in source_zip.infolist():
            if _is_upload_canceled(job_id):
                break
            if entry.is_dir():
                continue

            ext = os.path.splitext(entry.filename.lower())[1]
            safe_name = os.path.basename(entry.filename)
            if ext not in IMAGE_EXTS or not safe_name:
                continue

            try:
                payload = source_zip.read(entry)
                img = Image.open(io.BytesIO(payload)).convert("RGB")
            except Exception:
                _mark_upload_failed_item(job_id)
                continue

            batch.append((safe_name, img))
            if len(batch) >= batch_size:
                kept_sequence = _process_batch(
                    job_id,
                    batch,
                    model,
                    conf_thresh,
                    allowed_classes,
                    imgsz,
                    model_key,
                    prompt_classes,
                    result_zip,
                    result_store,
                    kept_sequence,
                )
                batch = []
                _persist_job_state(job_id)

        if batch and not _is_upload_canceled(job_id):
            kept_sequence = _process_batch(
                job_id,
                batch,
                model,
                conf_thresh,
                allowed_classes,
                imgsz,
                model_key,
                prompt_classes,
                result_zip,
                result_store,
                kept_sequence,
            )
            _persist_job_state(job_id)
        else:
            _close_batch_images(batch)

    return kept_sequence


def _run_video_source(
    job_id: str,
    video_path: str,
    frame_interval: int,
    batch_size: int,
    model,
    conf_thresh: float,
    allowed_classes: Optional[Set[int]],
    imgsz: int,
    model_key: str,
    prompt_classes: list[str] | None,
    result_zip: zipfile.ZipFile,
    result_store: dict,
) -> int:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("cannot open video file")

    batch: list[tuple[str, Image.Image]] = []
    kept_sequence = 0
    frame_idx = 0
    sample_idx = 0

    try:
        while True:
            if _is_upload_canceled(job_id):
                break

            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval != 0:
                frame_idx += 1
                continue

            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
            except Exception:
                _mark_upload_failed_item(job_id)
                frame_idx += 1
                continue

            batch.append((f"frame_{sample_idx:06d}.jpg", img))
            sample_idx += 1
            frame_idx += 1

            if len(batch) >= batch_size:
                kept_sequence = _process_batch(
                    job_id,
                    batch,
                    model,
                    conf_thresh,
                    allowed_classes,
                    imgsz,
                    model_key,
                    prompt_classes,
                    result_zip,
                    result_store,
                    kept_sequence,
                )
                batch = []
                _persist_job_state(job_id)

        if batch and not _is_upload_canceled(job_id):
            kept_sequence = _process_batch(
                job_id,
                batch,
                model,
                conf_thresh,
                allowed_classes,
                imgsz,
                model_key,
                prompt_classes,
                result_zip,
                result_store,
                kept_sequence,
            )
            _persist_job_state(job_id)
        else:
            _close_batch_images(batch)
    finally:
        cap.release()

    return kept_sequence


def _run_upload_job(
    job: dict,
    source_path: str,
    source_type: str,
    conf_thresh: float,
    batch_size: int,
    imgsz: int,
    classes_raw: str,
    model_key: str,
    temp_dir: str | None,
    frame_interval: int | None = None,
) -> None:
    job_id = str(job.get("id") or "").strip()
    if not job_id:
        raise ValueError("missing job id")

    runtime_job = dict(job)
    runtime_job["cancel"] = threading.Event()
    runtime_job["source_path"] = source_path
    runtime_job["source_type"] = source_type
    runtime_job["temp_dir"] = temp_dir or runtime_job.get("temp_dir") or ""
    runtime_job["frame_interval"] = frame_interval if frame_interval is not None else runtime_job.get("frame_interval")
    runtime_job["conf_thresh"] = conf_thresh
    runtime_job["batch_size"] = batch_size
    runtime_job["imgsz"] = imgsz
    runtime_job["classes_raw"] = classes_raw
    runtime_job["model_key"] = model_key or runtime_job.get("model_key") or get_upload_model_default()
    runtime_job["start_ts"] = runtime_job.get("start_ts") or int(time.time())
    runtime_job["message"] = runtime_job.get("message") or "queued"

    with UPLOAD_JOBS_LOCK:
        UPLOAD_JOBS[job_id] = runtime_job

    result_store = None
    zip_path = os.path.join(OUTPUT_DIR, f"upload_{job_id}.zip")

    try:
        if _sync_cancel_state(job_id):
            with UPLOAD_JOBS_LOCK:
                current = UPLOAD_JOBS[job_id]
                current["end_ts"] = current.get("end_ts") or int(time.time())
                snapshot = _upload_snapshot(current)
            _save_job_state(snapshot)
            return

        with UPLOAD_JOBS_LOCK:
            current = UPLOAD_JOBS[job_id]
            current["status"] = "running"
            current["message"] = "running"
        _persist_job_state(job_id)

        model = get_model(runtime_job["model_key"])
        result_store = create_result_store(job_id, "upload", source_type, runtime_job.get("source_name", ""))
        allowed_classes, prompt_classes = _resolve_model_filters(runtime_job["model_key"], model, classes_raw)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as result_zip:
            if source_type == "zip":
                _run_zip_source(
                    job_id,
                    source_path,
                    batch_size,
                    model,
                    conf_thresh,
                    allowed_classes,
                    imgsz,
                    runtime_job["model_key"],
                    prompt_classes,
                    result_zip,
                    result_store,
                )
            else:
                _run_video_source(
                    job_id,
                    source_path,
                    max(1, int(frame_interval or 1)),
                    batch_size,
                    model,
                    conf_thresh,
                    allowed_classes,
                    imgsz,
                    runtime_job["model_key"],
                    prompt_classes,
                    result_zip,
                    result_store,
                )

        if _is_upload_canceled(job_id):
            if os.path.isfile(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
            if result_store and os.path.isdir(result_store["result_dir"]):
                shutil.rmtree(result_store["result_dir"], ignore_errors=True)
            with UPLOAD_JOBS_LOCK:
                current = UPLOAD_JOBS.get(job_id)
                if current is not None:
                    current["status"] = "canceled"
                    current["message"] = current.get("message") or "cancel requested"
                    current["end_ts"] = current.get("end_ts") or int(time.time())
                    snapshot = _upload_snapshot(current)
                else:
                    snapshot = None
            if snapshot is not None:
                _save_job_state(snapshot)
            return

        manifest_path = finalize_result_store(result_store)

        with UPLOAD_JOBS_LOCK:
            current = UPLOAD_JOBS.get(job_id)
            if current is not None:
                current["zip_path"] = zip_path
                current["zip_parts"] = [{"path": zip_path, "name": os.path.basename(zip_path)}]
                current["result_dir"] = result_store["result_dir"]
                current["result_manifest_path"] = manifest_path
                current["status"] = "done"
                current["message"] = "completed"
                current["end_ts"] = int(time.time())
                snapshot = _upload_snapshot(current)
            else:
                snapshot = None
        if snapshot is not None:
            _save_job_state(snapshot)

    except Exception as exc:
        logger.exception("upload job %s failed: %s", job_id, exc)
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        if result_store and os.path.isdir(result_store["result_dir"]):
            shutil.rmtree(result_store["result_dir"], ignore_errors=True)

        _sync_cancel_state(job_id)
        with UPLOAD_JOBS_LOCK:
            current = UPLOAD_JOBS.get(job_id)
            if current is not None:
                if current["cancel"].is_set():
                    current["status"] = "canceled"
                    current["message"] = current.get("message") or "cancel requested"
                else:
                    current["status"] = "error"
                    current["message"] = str(exc)
                current["end_ts"] = int(time.time())
                snapshot = _upload_snapshot(current)
            else:
                snapshot = None
        if snapshot is not None:
            _save_job_state(snapshot)
    finally:
        with UPLOAD_JOBS_LOCK:
            current = UPLOAD_JOBS.get(job_id)
            if current is not None and current.get("status") in TERMINAL_STATUSES:
                UPLOAD_JOBS.pop(job_id, None)


def _enqueue_upload_job(job: dict) -> None:
    save_job(job)
    submit_task(
        "upload",
        {"job_id": job["id"]},
        owner_key=job.get("owner_key", ""),
        owner_ip=job.get("owner_ip", ""),
        task_id=job["id"],
    )


def start_zip_job(
    zip_path: str,
    original_filename: str,
    conf_thresh: float,
    batch_size: int,
    imgsz: int,
    classes_raw: str,
    model_key: str,
    owner_key: str,
    owner_ip: str,
    temp_dir: str,
) -> tuple[str | None, str]:
    try:
        with zipfile.ZipFile(zip_path) as source_zip:
            total = sum(
                1
                for entry in source_zip.infolist()
                if not entry.is_dir()
                and os.path.splitext(entry.filename.lower())[1] in IMAGE_EXTS
                and os.path.basename(entry.filename)
            )
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, f"ZIP parse failed: {exc}"

    if total <= 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, "ZIP contains no supported images (.jpg/.png/.bmp/.tiff/.webp)"

    job = _new_upload_job(total, original_filename, "zip", status="queued")
    job.update(
        source_path=zip_path,
        temp_dir=temp_dir,
        conf_thresh=conf_thresh,
        batch_size=batch_size,
        imgsz=imgsz,
        classes_raw=classes_raw,
        model_key=model_key,
        owner_key=owner_key,
        owner_ip=owner_ip,
    )

    try:
        _enqueue_upload_job(job)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, f"start upload job failed: {exc}"
    return job["id"], ""


def start_video_job(
    video_path: str,
    original_filename: str,
    frame_interval: int,
    conf_thresh: float,
    batch_size: int,
    imgsz: int,
    classes_raw: str,
    model_key: str,
    owner_key: str,
    owner_ip: str,
    temp_dir: str,
) -> tuple[str | None, str]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, "cannot open video file; expected MP4/AVI/MOV"

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    total = max(1, (frame_count + max(1, frame_interval) - 1) // max(1, frame_interval)) if frame_count > 0 else 1

    job = _new_upload_job(total, original_filename, "video", status="queued")
    job.update(
        source_path=video_path,
        temp_dir=temp_dir,
        frame_interval=max(1, int(frame_interval)),
        conf_thresh=conf_thresh,
        batch_size=batch_size,
        imgsz=imgsz,
        classes_raw=classes_raw,
        model_key=model_key,
        owner_key=owner_key,
        owner_ip=owner_ip,
    )

    try:
        _enqueue_upload_job(job)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, f"start upload job failed: {exc}"
    return job["id"], ""
