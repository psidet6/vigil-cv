import time
from uuid import uuid4

from shared.config.config import logger
from shared.db.sqlite import (
    get_auto_annotate_job,
    list_auto_annotate_jobs,
    save_auto_annotate_job,
)
from shared.task_queue import submit_task
from modules.training.services.auto_annotate_service import auto_annotate_dataset_assets
from modules.training.services.dataset_service import get_dataset


def _new_auto_job_id() -> str:
    return "auto_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]


def _update_job(job: dict, **changes) -> dict:
    job.update(changes)
    save_auto_annotate_job(job)
    return job


def _run_auto_annotate_job(job: dict, asset_ids: list[str]) -> None:
    try:
        _update_job(
            job,
            status="running",
            start_ts=int(time.time()),
            message="正在批量执行预标注",
        )

        def on_progress(snapshot: dict) -> None:
            total = int(snapshot.get("total") or 0)
            processed = int(snapshot.get("processed") or 0)
            updated = int(snapshot.get("updated") or 0)
            skipped_existing = int(snapshot.get("skipped_existing") or 0)
            no_detection = int(snapshot.get("no_detection") or 0)
            message = f"已处理 {processed}/{total} 张，生成 {updated} 张预标注"
            if skipped_existing:
                message += f"，跳过已标注 {skipped_existing} 张"
            if no_detection:
                message += f"，无命中 {no_detection} 张"
            _update_job(
                job,
                total=total,
                processed=processed,
                updated=updated,
                skipped_existing=skipped_existing,
                no_detection=no_detection,
                message=message,
            )

        result = auto_annotate_dataset_assets(
            dataset_id=job["dataset_id"],
            asset_ids=asset_ids,
            model_key=job["model_key"],
            conf_thresh=float(job["conf_thresh"] or 0.25),
            imgsz=int(job["imgsz"] or 640),
            prompt_value=job.get("prompt_classes") or "",
            class_mapping_value=job.get("class_mapping") or "",
            overwrite=bool(job.get("overwrite")),
            progress_callback=on_progress,
        )

        message = f"批量预标注完成，处理 {result['processed']} 张，生成 {result['updated']} 张预标注"
        if result["skipped_existing"]:
            message += f"，跳过已标注 {result['skipped_existing']} 张"
        if result["no_detection"]:
            message += f"，无命中 {result['no_detection']} 张"

        _update_job(
            job,
            status="done",
            end_ts=int(time.time()),
            total=int(result["processed"] or 0),
            processed=int(result["processed"] or 0),
            updated=int(result["updated"] or 0),
            skipped_existing=int(result["skipped_existing"] or 0),
            no_detection=int(result["no_detection"] or 0),
            message=message,
        )
    except Exception as exc:
        logger.exception("failed to run auto annotate job %s: %s", job.get("id"), exc)
        _update_job(
            job,
            status="error",
            end_ts=int(time.time()),
            message=str(exc) or "批量预标注失败",
        )


def start_auto_annotate_job(
    dataset_id: str,
    asset_ids: list[str],
    model_key: str,
    conf_thresh: float,
    imgsz: int,
    prompt_classes: str,
    class_mapping: str,
    overwrite: bool,
    owner_key: str,
    owner_ip: str,
) -> dict:
    dataset = get_dataset(dataset_id)
    if not asset_ids:
        raise ValueError("当前没有可用于批量预标注的图片")

    job = {
        "id": _new_auto_job_id(),
        "dataset_id": dataset["id"],
        "dataset_name": dataset.get("name") or dataset["id"],
        "status": "queued",
        "message": "批量预标注任务已创建，等待启动",
        "model_key": model_key,
        "conf_thresh": float(conf_thresh or 0.25),
        "imgsz": int(imgsz or 640),
        "prompt_classes": str(prompt_classes or "").strip(),
        "class_mapping": str(class_mapping or "").strip(),
        "overwrite": bool(overwrite),
        "total": len(asset_ids),
        "processed": 0,
        "updated": 0,
        "skipped_existing": 0,
        "no_detection": 0,
        "created_ts": int(time.time()),
        "start_ts": None,
        "end_ts": None,
        "owner_key": owner_key,
        "owner_ip": owner_ip,
    }
    save_auto_annotate_job(job)

    submit_task(
        "auto_annotate",
        {"job_id": job["id"], "asset_ids": list(asset_ids)},
        owner_key=owner_key,
        owner_ip=owner_ip,
        task_id=job["id"],
    )
    return job


def get_auto_annotate_job_snapshot(job_id: str) -> dict | None:
    return get_auto_annotate_job(job_id)


def list_auto_annotate_job_snapshots(owner_key: str, owner_ip: str, limit: int = 20) -> list[dict]:
    return list_auto_annotate_jobs(owner_key, owner_ip, limit=limit)
