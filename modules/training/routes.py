import os

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from shared.config.config import MODEL_DIR, get_upload_model_options, logger
from shared.job_lookup import resolve_job
from modules.detection.services.result_store_service import load_result_manifest
from modules.training.services.auto_annotate_service import auto_annotate_dataset_assets
from modules.training.services.auto_annotate_task_service import (
    get_auto_annotate_job_snapshot,
    list_auto_annotate_job_snapshots,
    start_auto_annotate_job,
)
from modules.training.services.dataset_service import (
    attach_recent_assets,
    create_dataset,
    get_dataset_asset,
    get_dataset,
    import_result_assets_to_dataset,
    import_zip_to_dataset,
    load_asset_annotation,
    list_dataset_assets,
    list_datasets,
    save_asset_annotation,
    summarize_datasets,
    update_asset_review_status,
)
from modules.training.services.model_registry_service import (
    get_model_registry_options,
    get_model_slot_views,
    list_managed_models,
    rollback_model_slot,
    set_model_slot,
    update_model_metadata,
)
from modules.training.services.train_task_service import (
    build_train_job_report,
    find_train_job_artifact_path,
    get_train_job_snapshot,
    list_train_job_snapshots,
    publish_train_job_best,
    start_train_job,
)
from shared.ownership.ownership import get_request_owner, job_matches_owner


train_bp = Blueprint("train", __name__, url_prefix="/train")


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_result_job(job_id: str) -> dict | None:
    return resolve_job(job_id)


def _serialize_asset(dataset_id: str, item: dict) -> dict:
    source_job_id = item.get("source_job_id") or ""
    return {
        "id": item.get("id"),
        "filename": item.get("filename"),
        "origin_name": item.get("origin_name"),
        "source_type": item.get("source_type"),
        "is_labeled": bool(item.get("is_labeled")),
        "source_job_id": source_job_id,
        "source_asset_id": item.get("source_asset_id") or "",
        "width": item.get("width", 0),
        "height": item.get("height", 0),
        "size_bytes": item.get("size_bytes", 0),
        "confidence_count": item.get("confidence_count", 0),
        "min_confidence": item.get("min_confidence"),
        "max_confidence": item.get("max_confidence"),
        "annotation_source": item.get("annotation_source", ""),
        "review_status": item.get("review_status", "pending"),
        "is_reviewed": bool(item.get("is_reviewed")),
        "reviewed_ts": item.get("reviewed_ts"),
        "asset_url": url_for("train.dataset_asset_file", dataset_id=dataset_id, asset_id=item.get("id")),
        "source_job_url": url_for("job.history_detail_page", job_id=source_job_id) if source_job_id else "",
    }


def _serialize_dataset(item: dict) -> dict:
    dataset = {key: value for key, value in item.items() if key != "recent_assets"}
    dataset["recent_assets"] = [
        _serialize_asset(dataset["id"], asset)
        for asset in (item.get("recent_assets") or [])
    ]
    return dataset


def _serialize_train_job(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "dataset_id": item.get("dataset_id"),
        "dataset_name": item.get("dataset_name"),
        "status": item.get("status"),
        "message": item.get("message"),
        "base_model": item.get("base_model"),
        "preset_key": item.get("preset_key"),
        "epochs": item.get("epochs", 0),
        "imgsz": item.get("imgsz", 0),
        "batch_size": item.get("batch_size", 0),
        "confirmed_only": bool(item.get("confirmed_only")),
        "run_dir": item.get("run_dir", ""),
        "log_path": item.get("log_path", ""),
        "manifest_path": item.get("manifest_path", ""),
        "artifact_dir": item.get("artifact_dir", ""),
        "created_ts": item.get("created_ts"),
        "start_ts": item.get("start_ts"),
        "end_ts": item.get("end_ts"),
        "report_url": url_for("train.train_job_report_page", job_id=item.get("id")),
    }


def _serialize_managed_model(item: dict) -> dict:
    return {
        "name": item.get("name"),
        "display_name": item.get("display_name", item.get("name")),
        "path": item.get("path"),
        "category": item.get("category"),
        "category_label": item.get("category_label", item.get("category", "")),
        "lifecycle": item.get("lifecycle", "active"),
        "lifecycle_label": item.get("lifecycle_label", ""),
        "usages": item.get("usages") or [],
        "usage_labels": item.get("usage_labels") or [],
        "note": item.get("note", ""),
        "size_bytes": item.get("size_bytes", 0),
        "modified_ts": item.get("modified_ts"),
        "source_job_id": item.get("source_job_id", ""),
        "dataset_id": item.get("dataset_id", ""),
        "dataset_name": item.get("dataset_name", ""),
        "base_model": item.get("base_model", ""),
        "confirmed_only": bool(item.get("confirmed_only")),
        "metrics": item.get("metrics") or {},
        "metadata_path": item.get("metadata_path", ""),
        "slot_refs": item.get("slot_refs") or [],
        "slot_labels": item.get("slot_labels") or [],
    }


def _serialize_model_slot(item: dict) -> dict:
    return {
        "slot_key": item.get("slot_key"),
        "label": item.get("label"),
        "current_model": item.get("current_model", ""),
        "current_path": item.get("current_path", ""),
        "changed_ts": item.get("changed_ts"),
        "history": item.get("history") or [],
        "has_override": bool(item.get("has_override")),
    }


def _serialize_auto_annotate_job(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "dataset_id": item.get("dataset_id"),
        "dataset_name": item.get("dataset_name"),
        "status": item.get("status"),
        "message": item.get("message"),
        "model_key": item.get("model_key"),
        "conf_thresh": item.get("conf_thresh", 0),
        "imgsz": item.get("imgsz", 0),
        "prompt_classes": item.get("prompt_classes", ""),
        "class_mapping": item.get("class_mapping", ""),
        "overwrite": bool(item.get("overwrite")),
        "total": item.get("total", 0),
        "processed": item.get("processed", 0),
        "updated": item.get("updated", 0),
        "skipped_existing": item.get("skipped_existing", 0),
        "no_detection": item.get("no_detection", 0),
        "created_ts": item.get("created_ts"),
        "start_ts": item.get("start_ts"),
        "end_ts": item.get("end_ts"),
    }


def _datasets_payload() -> dict:
    items = attach_recent_assets(list_datasets())
    return {
        "ok": True,
        "items": [_serialize_dataset(item) for item in items],
        "summary": summarize_datasets(items),
    }


@train_bp.get("/datasets")
def dataset_list():
    return jsonify(_datasets_payload())


@train_bp.get("/jobs")
def train_job_list():
    owner_key, owner_ip = get_request_owner(request)
    limit_raw = request.args.get("limit", "20")
    try:
        limit = int(limit_raw)
    except Exception:
        limit = 20
    items = list_train_job_snapshots(owner_key, owner_ip, limit=limit)
    return jsonify({"ok": True, "items": [_serialize_train_job(item) for item in items]})


@train_bp.get("/model-registry-page")
def train_model_registry_page():
    return render_template(
        "modules/training/pages/train_model_registry.html",
        models=[_serialize_managed_model(item) for item in list_managed_models()],
        slots=[_serialize_model_slot(item) for item in get_model_slot_views()],
        registry_options=get_model_registry_options(),
    )


@train_bp.get("/models")
def train_model_registry_data():
    return jsonify(
        {
            "ok": True,
            "models": [_serialize_managed_model(item) for item in list_managed_models()],
            "slots": [_serialize_model_slot(item) for item in get_model_slot_views()],
            "registry_options": get_model_registry_options(),
        }
    )


@train_bp.post("/models/<model_name>/metadata")
def train_model_metadata_update(model_name: str):
    payload = request.get_json(silent=True) or request.form or {}
    display_name = (payload.get("display_name", "") or "").strip()
    lifecycle = (payload.get("lifecycle", "") or "").strip()
    usages = payload.get("usages")
    note = (payload.get("note", "") or "").strip()
    try:
        model = update_model_metadata(
            model_name,
            display_name=display_name,
            lifecycle=lifecycle,
            usages=usages,
            note=note,
        )
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "model not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to update model metadata %s: %s", model_name, exc)
        return jsonify({"ok": False, "error": "failed to update model metadata"}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"模型元数据已更新：{model.get('display_name') or model.get('name')}",
            "model": _serialize_managed_model(model),
            "models": [_serialize_managed_model(item) for item in list_managed_models()],
            "registry_options": get_model_registry_options(),
        }
    )


@train_bp.post("/model-slots/<slot_key>")
def train_model_slot_set(slot_key: str):
    payload = request.get_json(silent=True) or request.form or {}
    model_name = (payload.get("model_name", "") or "").strip()
    try:
        slot_view = set_model_slot(slot_key, model_name)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "model not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to set model slot %s: %s", slot_key, exc)
        return jsonify({"ok": False, "error": "failed to update model slot"}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"{slot_view.get('label')} 已切换为 {slot_view.get('current_model')}",
            "slot": _serialize_model_slot(slot_view),
            "models": [_serialize_managed_model(item) for item in list_managed_models()],
        }
    )


@train_bp.post("/model-slots/<slot_key>/rollback")
def train_model_slot_rollback(slot_key: str):
    try:
        slot_view = rollback_model_slot(slot_key)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to rollback model slot %s: %s", slot_key, exc)
        return jsonify({"ok": False, "error": "failed to rollback model slot"}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"{slot_view.get('label')} 已回滚到 {slot_view.get('current_model')}",
            "slot": _serialize_model_slot(slot_view),
            "models": [_serialize_managed_model(item) for item in list_managed_models()],
        }
    )


@train_bp.get("/jobs/<job_id>")
def train_job_detail(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_train_job_snapshot(job_id)
    if job is None or not job_matches_owner(job, owner_key, owner_ip):
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": _serialize_train_job(job)})


@train_bp.get("/jobs/<job_id>/report-page")
def train_job_report_page(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_train_job_snapshot(job_id)
    if job is None or not job_matches_owner(job, owner_key, owner_ip):
        return "job not found", 404

    try:
        report = build_train_job_report(job_id)
    except LookupError:
        return "job not found", 404

    for image in report.get("images", []):
        image["url"] = url_for("train.train_job_artifact_file", job_id=job_id, filename=image.get("filename"))

    return render_template("modules/training/pages/train_report.html", report=report, job=job, model_dir=MODEL_DIR)


@train_bp.get("/jobs/<job_id>/report")
def train_job_report_data(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_train_job_snapshot(job_id)
    if job is None or not job_matches_owner(job, owner_key, owner_ip):
        return jsonify({"ok": False, "error": "job not found"}), 404

    try:
        report = build_train_job_report(job_id)
    except LookupError:
        return jsonify({"ok": False, "error": "job not found"}), 404

    image_items = []
    for image in report.get("images", []):
        image_items.append(
            {
                "key": image.get("key"),
                "title": image.get("title"),
                "filename": image.get("filename"),
                "url": url_for("train.train_job_artifact_file", job_id=job_id, filename=image.get("filename")),
            }
        )

    return jsonify(
        {
            "ok": True,
            "report": {
                "job": _serialize_train_job(report.get("job") or job),
                "summary": report.get("summary") or {},
                "metrics": report.get("metrics") or {},
                "losses": report.get("losses") or {},
                "assessment": report.get("assessment") or {},
                "history": report.get("history") or [],
                "images": image_items,
                "paths": report.get("paths") or {},
                "publish": report.get("publish") or {},
            },
        }
    )


@train_bp.get("/jobs/<job_id>/artifacts/<filename>")
def train_job_artifact_file(job_id: str, filename: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_train_job_snapshot(job_id)
    if job is None or not job_matches_owner(job, owner_key, owner_ip):
        return "job not found", 404

    try:
        path = find_train_job_artifact_path(job_id, filename)
    except LookupError:
        return "job not found", 404
    except FileNotFoundError:
        return "artifact not found", 404

    return send_file(path)


@train_bp.post("/jobs/<job_id>/publish")
def train_job_publish(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_train_job_snapshot(job_id)
    if job is None or not job_matches_owner(job, owner_key, owner_ip):
        return jsonify({"ok": False, "error": "job not found"}), 404

    payload = request.get_json(silent=True) or request.form or {}
    target_name = (payload.get("target_name", "") or "").strip()
    try:
        published = publish_train_job_best(job_id, target_name=target_name)
    except LookupError:
        return jsonify({"ok": False, "error": "job not found"}), 404
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to publish best model for %s: %s", job_id, exc)
        return jsonify({"ok": False, "error": "publish failed"}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"best.pt 已发布到 model 目录：{published.get('model_name')}",
            "published": published,
            "upload_models": get_upload_model_options(),
        }
    )


@train_bp.get("/auto-annotate-jobs")
def auto_annotate_job_list():
    owner_key, owner_ip = get_request_owner(request)
    limit_raw = request.args.get("limit", "20")
    try:
        limit = int(limit_raw)
    except Exception:
        limit = 20
    items = list_auto_annotate_job_snapshots(owner_key, owner_ip, limit=limit)
    return jsonify({"ok": True, "items": [_serialize_auto_annotate_job(item) for item in items]})


@train_bp.get("/auto-annotate-jobs/<job_id>")
def auto_annotate_job_detail(job_id: str):
    owner_key, owner_ip = get_request_owner(request)
    job = get_auto_annotate_job_snapshot(job_id)
    if job is None or not job_matches_owner(job, owner_key, owner_ip):
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": _serialize_auto_annotate_job(job)})


@train_bp.post("/jobs")
def train_job_create():
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or request.form or {}
    dataset_id = (payload.get("dataset_id", "") or "").strip()
    base_model = (payload.get("base_model", "") or "").strip()
    preset_key = (payload.get("preset_key", "quick") or "quick").strip()
    confirmed_only = _parse_bool(payload.get("confirmed_only"))

    try:
        epochs = int(payload.get("epochs", 0) or 0)
        imgsz = int(payload.get("imgsz", 0) or 0)
        batch_size = int(payload.get("batch_size", 0) or 0)
    except Exception:
        return jsonify({"ok": False, "error": "invalid train params"}), 400

    if not dataset_id:
        return jsonify({"ok": False, "error": "dataset_id is required"}), 400
    if not base_model:
        return jsonify({"ok": False, "error": "base_model is required"}), 400

    try:
        job = start_train_job(
            dataset_id,
            base_model,
            preset_key,
            epochs,
            imgsz,
            batch_size,
            owner_key,
            owner_ip,
            confirmed_only=confirmed_only,
        )
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to create train job: %s", exc)
        return jsonify({"ok": False, "error": "训练任务创建失败"}), 500

    return jsonify({"ok": True, "message": "训练任务骨架已创建", "job": _serialize_train_job(job)}), 201


@train_bp.get("/datasets/<dataset_id>")
def dataset_detail(dataset_id: str):
    try:
        dataset = get_dataset(dataset_id)
        items = list_dataset_assets(dataset_id, limit=500)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    return jsonify(
        {
            "ok": True,
            "dataset": _serialize_dataset({**dataset, "recent_assets": items[:8]}),
            "items": [_serialize_asset(dataset_id, item) for item in items],
        }
    )


@train_bp.post("/datasets")
def dataset_create():
    payload = request.get_json(silent=True) or request.form or {}
    name = (payload.get("name", "") or "").strip()
    class_names = payload.get("class_names", "")
    notes = (payload.get("notes", "") or "").strip()

    try:
        dataset = create_dataset(name, class_names, notes)
        response = _datasets_payload()
        response["message"] = "数据集已创建"
        response["dataset_id"] = dataset["id"]
        return jsonify(response), 201
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to create dataset: %s", exc)
        return jsonify({"ok": False, "error": "创建数据集失败"}), 500


@train_bp.post("/datasets/<dataset_id>/import-zip")
def dataset_import_zip(dataset_id: str):
    upload_file = request.files.get("file")
    try:
        result = import_zip_to_dataset(dataset_id, upload_file)
        response = _datasets_payload()
        response.update(
            {
                "message": f"已导入 {result['imported']} 张图片，跳过 {result['skipped']} 项",
                "imported": result["imported"],
                "skipped": result["skipped"],
                "upload_name": result["upload_name"],
                "dataset_id": dataset_id,
            }
        )
        return jsonify(response)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to import zip into dataset %s: %s", dataset_id, exc)
        return jsonify({"ok": False, "error": "ZIP 导入失败"}), 500


@train_bp.post("/datasets/<dataset_id>/import-results")
def dataset_import_results(dataset_id: str):
    payload = request.get_json(silent=True) or request.form or {}
    job_id = (payload.get("job_id", "") or "").strip()
    asset_ids = payload.get("asset_ids") or []

    if not job_id:
        return jsonify({"ok": False, "error": "job_id is required"}), 400
    if not isinstance(asset_ids, list) or not asset_ids:
        return jsonify({"ok": False, "error": "asset_ids is required"}), 400

    job = _resolve_result_job(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404

    manifest_path = job.get("result_manifest_path")
    if not manifest_path or not os.path.isfile(manifest_path):
        return jsonify({"ok": False, "error": "result manifest not found"}), 404

    try:
        manifest = load_result_manifest(manifest_path)
    except Exception as exc:
        logger.exception("failed to load result manifest for job %s: %s", job_id, exc)
        return jsonify({"ok": False, "error": "failed to read result manifest"}), 500

    selected_ids = {
        os.path.basename(str(asset_id or "").strip())
        for asset_id in asset_ids
        if str(asset_id or "").strip()
    }
    selected_items = [
        item
        for item in manifest.get("items", [])
        if item.get("id") in selected_ids
    ]
    if not selected_items:
        return jsonify({"ok": False, "error": "no valid selected assets found"}), 400

    source_type = "upload_result" if (job.get("job_type") or "database") == "upload" else "database_result"

    try:
        result = import_result_assets_to_dataset(dataset_id, selected_items, source_type, job_id)
        response = _datasets_payload()
        response.update(
            {
                "message": f"已导入 {result['imported']} 张结果图，跳过 {result['skipped']} 张。",
                "imported": result["imported"],
                "skipped": result["skipped"],
                "dataset_id": dataset_id,
                "job_id": job_id,
            }
        )
        return jsonify(response)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to import results into dataset %s from job %s: %s", dataset_id, job_id, exc)
        return jsonify({"ok": False, "error": "结果图导入失败"}), 500


@train_bp.get("/datasets/<dataset_id>/assets")
def dataset_asset_list(dataset_id: str):
    try:
        items = list_dataset_assets(dataset_id, limit=200)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    return jsonify({"ok": True, "items": [_serialize_asset(dataset_id, item) for item in items]})


@train_bp.get("/datasets/<dataset_id>/assets/<asset_id>/annotation")
def dataset_asset_annotation(dataset_id: str, asset_id: str):
    try:
        payload = load_asset_annotation(dataset_id, asset_id)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(
        {
            "ok": True,
            "dataset": _serialize_dataset({**payload["dataset"], "recent_assets": []}),
            "asset": _serialize_asset(dataset_id, payload["asset"]),
            "boxes": payload["boxes"],
            "label_path": payload["label_path"],
            "label_meta_path": payload.get("label_meta_path", ""),
            "is_labeled": payload["is_labeled"],
            "review_status": payload.get("review_status", "pending"),
            "reviewed_ts": payload.get("reviewed_ts"),
        }
    )


@train_bp.post("/datasets/<dataset_id>/assets/<asset_id>/annotation")
def dataset_asset_annotation_save(dataset_id: str, asset_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        saved = save_asset_annotation(dataset_id, asset_id, payload.get("boxes") or [])
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to save annotation for dataset %s asset %s: %s", dataset_id, asset_id, exc)
        return jsonify({"ok": False, "error": "标注保存失败"}), 500
    return jsonify(
        {
            "ok": True,
            "message": "标注已保存",
            "dataset": _serialize_dataset({**saved["dataset"], "recent_assets": []}),
            "asset": _serialize_asset(dataset_id, saved["asset"]),
            "boxes": saved["boxes"],
            "label_path": saved["label_path"],
            "is_labeled": saved["is_labeled"],
            "review_status": saved.get("review_status", "pending"),
            "reviewed_ts": saved.get("reviewed_ts"),
        }
    )


@train_bp.post("/datasets/<dataset_id>/assets/<asset_id>/review")
def dataset_asset_review_update(dataset_id: str, asset_id: str):
    payload = request.get_json(silent=True) or {}
    review_status = (payload.get("review_status", "pending") or "pending").strip()
    try:
        saved = update_asset_review_status(dataset_id, asset_id, review_status)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to update review status for dataset %s asset %s: %s", dataset_id, asset_id, exc)
        return jsonify({"ok": False, "error": "复核状态保存失败"}), 500
    return jsonify(
        {
            "ok": True,
            "message": "复核状态已更新",
            "dataset": _serialize_dataset({**saved["dataset"], "recent_assets": []}),
            "asset": _serialize_asset(dataset_id, saved["asset"]),
            "boxes": saved["boxes"],
            "label_path": saved["label_path"],
            "label_meta_path": saved.get("label_meta_path", ""),
            "is_labeled": saved["is_labeled"],
            "review_status": saved.get("review_status", "pending"),
            "reviewed_ts": saved.get("reviewed_ts"),
        }
    )


@train_bp.post("/datasets/<dataset_id>/auto-annotate")
def dataset_auto_annotate(dataset_id: str):
    payload = request.get_json(silent=True) or {}
    asset_ids = payload.get("asset_ids") or []
    model_key = (payload.get("model_key", "") or "").strip()
    prompt_value = payload.get("prompt_classes")
    class_mapping = payload.get("class_mapping")
    overwrite = bool(payload.get("overwrite"))

    if not isinstance(asset_ids, list) or not asset_ids:
        return jsonify({"ok": False, "error": "asset_ids is required"}), 400
    if not model_key:
        return jsonify({"ok": False, "error": "model_key is required"}), 400

    try:
        conf_thresh = float(payload.get("conf_thresh", 0.25) or 0.25)
        imgsz = int(payload.get("imgsz", 640) or 640)
    except Exception:
        return jsonify({"ok": False, "error": "invalid auto annotate params"}), 400

    try:
        result = auto_annotate_dataset_assets(
            dataset_id=dataset_id,
            asset_ids=[os.path.basename(str(item or "")) for item in asset_ids if str(item or "").strip()],
            model_key=model_key,
            conf_thresh=conf_thresh,
            imgsz=imgsz,
            prompt_value=prompt_value,
            class_mapping_value=class_mapping,
            overwrite=overwrite,
        )
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to auto annotate dataset %s: %s", dataset_id, exc)
        return jsonify({"ok": False, "error": "预标注失败"}), 500

    message = f"已处理 {result['processed']} 张，生成 {result['updated']} 张预标注"
    if result["skipped_existing"]:
        message += f"，跳过已标注 {result['skipped_existing']} 张"
    if result["no_detection"]:
        message += f"，无命中 {result['no_detection']} 张"

    return jsonify(
        {
            "ok": True,
            "message": message,
            "dataset": _serialize_dataset({**result["dataset"], "recent_assets": []}),
            "processed": result["processed"],
            "updated": result["updated"],
            "skipped_existing": result["skipped_existing"],
            "no_detection": result["no_detection"],
            "items": [
                {
                    "asset": _serialize_asset(dataset_id, item["asset"]),
                    "boxes": item["boxes"],
                    "is_labeled": item["is_labeled"],
                    "label_path": item["label_path"],
                }
                for item in result["items"]
            ],
        }
    )


@train_bp.post("/datasets/<dataset_id>/auto-annotate-jobs")
def dataset_auto_annotate_job_create(dataset_id: str):
    owner_key, owner_ip = get_request_owner(request)
    payload = request.get_json(silent=True) or {}
    asset_ids = payload.get("asset_ids") or []
    model_key = (payload.get("model_key", "") or "").strip()
    prompt_value = payload.get("prompt_classes")
    class_mapping = payload.get("class_mapping")
    overwrite = bool(payload.get("overwrite"))

    if not isinstance(asset_ids, list) or not asset_ids:
        return jsonify({"ok": False, "error": "asset_ids is required"}), 400
    if not model_key:
        return jsonify({"ok": False, "error": "model_key is required"}), 400

    try:
        conf_thresh = float(payload.get("conf_thresh", 0.25) or 0.25)
        imgsz = int(payload.get("imgsz", 640) or 640)
    except Exception:
        return jsonify({"ok": False, "error": "invalid auto annotate params"}), 400

    asset_ids = [os.path.basename(str(item or "")) for item in asset_ids if str(item or "").strip()]
    if not asset_ids:
        return jsonify({"ok": False, "error": "asset_ids is required"}), 400

    try:
        job = start_auto_annotate_job(
            dataset_id=dataset_id,
            asset_ids=asset_ids,
            model_key=model_key,
            conf_thresh=conf_thresh,
            imgsz=imgsz,
            prompt_classes=prompt_value or "",
            class_mapping=class_mapping or "",
            overwrite=overwrite,
            owner_key=owner_key,
            owner_ip=owner_ip,
        )
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("failed to create auto annotate job for dataset %s: %s", dataset_id, exc)
        return jsonify({"ok": False, "error": "批量预标注任务创建失败"}), 500

    return jsonify({"ok": True, "message": "批量预标注任务已创建", "job": _serialize_auto_annotate_job(job)}), 201


@train_bp.get("/datasets/<dataset_id>/assets/<asset_id>")
def dataset_asset_file(dataset_id: str, asset_id: str):
    try:
        item = get_dataset_asset(dataset_id, os.path.basename(asset_id))
    except LookupError:
        return "dataset not found", 404

    path = item.get("file_path")
    if path and os.path.isfile(path):
        return send_file(path)
    return "asset not found", 404
