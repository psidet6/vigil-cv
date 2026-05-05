import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from shared.config.config import BASE_DIR, MODEL_DIR, TRAIN_RUNS_DIR, logger, resolve_model_path
from shared.db.sqlite import get_train_job, list_train_jobs, save_train_job
from shared.task_queue import submit_task
from modules.training.services.dataset_service import get_dataset, list_dataset_assets


def _new_train_job_id() -> str:
    return "train_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]


def _append_log(log_path: str, message: str) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _update_job(job: dict, **changes) -> dict:
    job.update(changes)
    save_train_job(job)
    return job


def _normalize_path(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


def _resolve_yolo_executable() -> str:
    candidates = [
        os.path.join(BASE_DIR, ".venv", "Scripts", "yolo.exe"),
        os.path.join(os.path.dirname(sys.executable), "yolo.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError("未找到 yolo.exe，请确认项目虚拟环境已安装 Ultralytics。")


def _split_labeled_assets(dataset_id: str, confirmed_only: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    assets = list_dataset_assets(dataset_id, limit=5000)
    labeled = [item for item in assets if item.get("is_labeled")]
    if confirmed_only:
        labeled = [item for item in labeled if str(item.get("review_status") or "pending") == "confirmed"]
        if not labeled:
            raise ValueError("当前数据集还没有已确认样本，无法按“仅使用已确认样本”启动训练任务。")
    labeled.sort(key=lambda item: ((item.get("origin_name") or item.get("filename") or "").lower(), item.get("id") or ""))
    if not labeled:
        raise ValueError("当前数据集没有可用于训练的已标注图片。")

    if len(labeled) == 1:
        return assets, labeled, labeled

    val_count = max(1, min(len(labeled) - 1, int(round(len(labeled) * 0.2))))
    val_assets = labeled[:val_count]
    train_assets = labeled[val_count:]
    if not train_assets:
        train_assets = labeled[:-1]
        val_assets = labeled[-1:]
    return assets, train_assets, val_assets


def _write_split_file(path: str, items: list[dict]) -> None:
    lines = []
    for item in items:
        file_path = item.get("file_path") or ""
        if file_path and os.path.isfile(file_path):
            lines.append(_normalize_path(file_path))
    if not lines:
        raise ValueError("训练划分中没有有效图片路径。")
    _write_text(path, "\n".join(lines) + "\n")


def _build_dataset_yaml(dataset: dict, train_txt_path: str, val_txt_path: str) -> str:
    lines = [
        "path: " + _normalize_path(dataset.get("root_dir") or ""),
        "train: " + _normalize_path(train_txt_path),
        "val: " + _normalize_path(val_txt_path),
        "names:",
    ]
    for index, name in enumerate(dataset.get("class_names") or []):
        lines.append(f"  {index}: {json.dumps(name, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _build_train_command(yolo_exe: str, job: dict, dataset_yaml_path: str) -> list[str]:
    return [
        yolo_exe,
        "detect",
        "train",
        f"model={job['base_model_path']}",
        f"data={dataset_yaml_path}",
        f"epochs={job['epochs']}",
        f"imgsz={job['imgsz']}",
        f"batch={job['batch_size']}",
        f"project={_normalize_path(TRAIN_RUNS_DIR)}",
        f"name={job['id']}",
        "exist_ok=True",
        "workers=0",
        "cache=False",
        "verbose=True",
    ]


def _copy_artifacts(run_dir: str, artifact_dir: str) -> dict:
    os.makedirs(artifact_dir, exist_ok=True)
    mapping = {
        "best_weights": os.path.join(run_dir, "weights", "best.pt"),
        "last_weights": os.path.join(run_dir, "weights", "last.pt"),
        "results_csv": os.path.join(run_dir, "results.csv"),
        "args_yaml": os.path.join(run_dir, "args.yaml"),
        "results_plot": os.path.join(run_dir, "results.png"),
        "confusion_matrix": os.path.join(run_dir, "confusion_matrix.png"),
        "confusion_matrix_normalized": os.path.join(run_dir, "confusion_matrix_normalized.png"),
        "box_f1_curve": os.path.join(run_dir, "BoxF1_curve.png"),
        "box_pr_curve": os.path.join(run_dir, "BoxPR_curve.png"),
        "box_p_curve": os.path.join(run_dir, "BoxP_curve.png"),
        "box_r_curve": os.path.join(run_dir, "BoxR_curve.png"),
        "train_batch0": os.path.join(run_dir, "train_batch0.jpg"),
        "val_batch0_labels": os.path.join(run_dir, "val_batch0_labels.jpg"),
        "val_batch0_pred": os.path.join(run_dir, "val_batch0_pred.jpg"),
    }
    copied = {}
    for key, source in mapping.items():
        if not os.path.isfile(source):
            continue
        target = os.path.join(artifact_dir, os.path.basename(source))
        shutil.copy2(source, target)
        copied[key] = os.path.abspath(target)
    return copied


def _read_results_summary(results_csv_path: str) -> dict:
    if not results_csv_path or not os.path.isfile(results_csv_path):
        return {}
    try:
        with open(results_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            return {}
        last = rows[-1]
        summary = {}
        for key in ("epoch", "train/box_loss", "train/cls_loss", "metrics/precision(B)", "metrics/recall(B)", "metrics/mAP50(B)", "metrics/mAP50-95(B)"):
            if key in last and last[key] not in ("", None):
                summary[key] = last[key]
        return summary
    except Exception:
        return {}


def _manifest_payload(
    job: dict,
    request_payload: dict,
    command: list[str],
    dataset_yaml_path: str,
    train_txt_path: str,
    val_txt_path: str,
    request_path: str,
    command_path: str,
    notes_path: str,
    artifact_paths: dict,
    summary: dict,
    status: str,
    error: str = "",
) -> dict:
    payload = {
        "job": request_payload,
        "status": status,
        "command": command,
        "paths": {
            "run_dir": job.get("run_dir", ""),
            "artifact_dir": job.get("artifact_dir", ""),
            "dataset_yaml": dataset_yaml_path,
            "train_split": train_txt_path,
            "val_split": val_txt_path,
            "request_json": request_path,
            "command_txt": command_path,
            "notes_md": notes_path,
            "log_path": job.get("log_path", ""),
            **artifact_paths,
        },
        "summary": summary,
    }
    if error:
        payload["error"] = error
    return payload


def _run_train_job(job: dict) -> None:
    process = None
    dataset_yaml_path = os.path.join(job["run_dir"], "dataset.yaml")
    request_path = os.path.join(job["run_dir"], "train_request.json")
    command_path = os.path.join(job["run_dir"], "train_command.txt")
    notes_path = os.path.join(job["run_dir"], "NEXT_STEPS.md")
    split_dir = os.path.join(job["run_dir"], "splits")
    train_txt_path = os.path.join(split_dir, "train.txt")
    val_txt_path = os.path.join(split_dir, "val.txt")
    request_payload = {}
    command = []
    artifact_paths = {}
    try:
        now = int(time.time())
        _update_job(job, status="running", start_ts=now, message="正在准备训练数据与运行参数")
        _append_log(job["log_path"], "Training job started.")

        dataset = get_dataset(job["dataset_id"])
        all_assets, train_assets, val_assets = _split_labeled_assets(
            job["dataset_id"],
            confirmed_only=bool(job.get("confirmed_only")),
        )
        os.makedirs(job["run_dir"], exist_ok=True)
        os.makedirs(job["artifact_dir"], exist_ok=True)

        _write_split_file(train_txt_path, train_assets)
        _write_split_file(val_txt_path, val_assets)
        _append_log(job["log_path"], f"Prepared split files: train={len(train_assets)}, val={len(val_assets)}")

        _write_text(dataset_yaml_path, _build_dataset_yaml(dataset, train_txt_path, val_txt_path))
        _append_log(job["log_path"], "dataset.yaml written.")

        request_payload = {
            "job_id": job["id"],
            "dataset_id": job["dataset_id"],
            "dataset_name": job["dataset_name"],
            "base_model": job["base_model"],
            "base_model_path": job["base_model_path"],
            "preset_key": job["preset_key"],
            "epochs": job["epochs"],
            "imgsz": job["imgsz"],
            "batch_size": job["batch_size"],
            "confirmed_only": bool(job.get("confirmed_only")),
            "image_count": dataset.get("image_count", 0),
            "labeled_count": dataset.get("labeled_count", 0),
            "reviewed_count": dataset.get("reviewed_count", 0),
            "class_names": dataset.get("class_names") or [],
            "created_ts": job["created_ts"],
            "split": {
                "total_assets": len(all_assets),
                "labeled_assets": len(train_assets) + len(val_assets),
                "train_assets": len(train_assets),
                "val_assets": len(val_assets),
            },
        }
        _write_json(request_path, request_payload)
        _append_log(job["log_path"], "train_request.json written.")

        yolo_exe = _resolve_yolo_executable()
        command = _build_train_command(yolo_exe, job, dataset_yaml_path)
        _write_text(command_path, " ".join(f'"{part}"' if " " in part else part for part in command) + "\n")
        _append_log(job["log_path"], "train_command.txt written.")

        notes = "\n".join(
            [
                "# Train Run",
                "",
                "This run executes a real Ultralytics training command.",
                "",
                "Prepared files:",
                "- dataset.yaml",
                "- splits/train.txt",
                "- splits/val.txt",
                "- train_request.json",
                "- train_command.txt",
                "- train.log",
                "",
                "Dataset:",
                f"- name: {job['dataset_name']}",
                f"- confirmed only: {'yes' if job.get('confirmed_only') else 'no'}",
                f"- train images: {len(train_assets)}",
                f"- val images: {len(val_assets)}",
                f"- classes: {', '.join(dataset.get('class_names') or []) or '--'}",
            ]
        )
        _write_text(notes_path, notes + "\n")

        _update_job(job, message="正在执行 Ultralytics 训练")
        _append_log(job["log_path"], "Launching Ultralytics training process.")

        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        popen_kwargs = {
            "cwd": BASE_DIR,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(command, **popen_kwargs)
        while True:
            line = process.stdout.readline() if process.stdout is not None else ""
            if line:
                _append_log(job["log_path"], line.rstrip())
            elif process.poll() is not None:
                break

        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"Ultralytics training exited with code {return_code}")

        artifact_paths = _copy_artifacts(job["run_dir"], job["artifact_dir"])
        summary = _read_results_summary(artifact_paths.get("results_csv") or os.path.join(job["run_dir"], "results.csv"))
        _write_json(
            job["manifest_path"],
            _manifest_payload(
                job,
                request_payload,
                command,
                dataset_yaml_path,
                train_txt_path,
                val_txt_path,
                request_path,
                command_path,
                notes_path,
                artifact_paths,
                summary,
                "done",
            ),
        )

        message = "训练完成"
        if artifact_paths.get("best_weights"):
            message += "，best.pt 已生成"
        _update_job(job, status="done", end_ts=int(time.time()), message=message)
        _append_log(job["log_path"], "Training finished successfully.")
    except Exception as exc:
        logger.exception("failed to run training for %s: %s", job.get("id"), exc)
        _update_job(job, status="error", end_ts=int(time.time()), message=str(exc) or "训练任务失败")
        try:
            _append_log(job["log_path"], "ERROR: " + (str(exc) or "unknown error"))
        except Exception:
            pass
        try:
            _write_json(
                job["manifest_path"],
                _manifest_payload(
                    job,
                    request_payload or {
                        "job_id": job.get("id"),
                        "dataset_id": job.get("dataset_id"),
                        "dataset_name": job.get("dataset_name"),
                    },
                    command,
                    dataset_yaml_path,
                    train_txt_path,
                    val_txt_path,
                    request_path,
                    command_path,
                    notes_path,
                    artifact_paths,
                    {},
                    "error",
                    error=str(exc),
                ),
            )
        except Exception:
            pass
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass


def start_train_job(
    dataset_id: str,
    base_model: str,
    preset_key: str,
    epochs: int,
    imgsz: int,
    batch_size: int,
    owner_key: str,
    owner_ip: str,
    confirmed_only: bool = False,
) -> dict:
    dataset = get_dataset(dataset_id)
    if not dataset:
        raise LookupError("dataset not found")
    if not (dataset.get("class_names") or []):
        raise ValueError("当前数据集还没有类别，无法创建训练任务")
    if int(dataset.get("image_count") or 0) <= 0:
        raise ValueError("当前数据集还没有图片，无法创建训练任务")
    if int(dataset.get("labeled_count") or 0) <= 0:
        raise ValueError("当前数据集还没有标注，至少先完成 1 张图片的框标注")

    base_model_path = resolve_model_path(base_model)
    if not os.path.isfile(base_model_path):
        raise ValueError("训练底模不存在")

    _resolve_yolo_executable()
    _split_labeled_assets(dataset_id, confirmed_only=bool(confirmed_only))

    job_id = _new_train_job_id()
    run_dir = os.path.join(TRAIN_RUNS_DIR, job_id)
    artifact_dir = os.path.join(run_dir, "artifacts")
    log_path = os.path.join(run_dir, "train.log")
    manifest_path = os.path.join(run_dir, "train_manifest.json")

    job = {
        "id": job_id,
        "dataset_id": dataset["id"],
        "dataset_name": dataset.get("name") or dataset["id"],
        "status": "queued",
        "message": "训练任务已创建，等待启动训练",
        "base_model": os.path.basename(base_model),
        "base_model_path": base_model_path,
        "preset_key": preset_key,
        "epochs": max(1, int(epochs)),
        "imgsz": max(64, int(imgsz)),
        "batch_size": max(1, int(batch_size)),
        "confirmed_only": bool(confirmed_only),
        "run_dir": run_dir,
        "log_path": log_path,
        "manifest_path": manifest_path,
        "artifact_dir": artifact_dir,
        "created_ts": int(time.time()),
        "start_ts": None,
        "end_ts": None,
        "owner_key": owner_key,
        "owner_ip": owner_ip,
    }
    save_train_job(job)

    submit_task(
        "train",
        {"job_id": job_id},
        owner_key=owner_key,
        owner_ip=owner_ip,
        task_id=job_id,
    )
    return job


def get_train_job_snapshot(job_id: str) -> dict | None:
    return get_train_job(job_id)


def list_train_job_snapshots(owner_key: str, owner_ip: str, limit: int = 20) -> list[dict]:
    return list_train_jobs(owner_key, owner_ip, limit=limit)


_REPORT_IMAGE_SPECS = (
    ("results_plot", "Training Results", "results.png"),
    ("confusion_matrix", "Confusion Matrix", "confusion_matrix.png"),
    ("confusion_matrix_normalized", "Confusion Matrix (Normalized)", "confusion_matrix_normalized.png"),
    ("box_f1_curve", "Box F1 Curve", "BoxF1_curve.png"),
    ("box_pr_curve", "Box PR Curve", "BoxPR_curve.png"),
    ("box_p_curve", "Box Precision Curve", "BoxP_curve.png"),
    ("box_r_curve", "Box Recall Curve", "BoxR_curve.png"),
    ("train_batch0", "Train Batch Preview", "train_batch0.jpg"),
    ("val_batch0_labels", "Validation Labels", "val_batch0_labels.jpg"),
    ("val_batch0_pred", "Validation Predictions", "val_batch0_pred.jpg"),
)


def _load_json_file(path: str) -> dict:
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


def _first_existing_path(*paths: str) -> str:
    for path in paths:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    return ""


def _collect_search_dirs(job: dict, manifest: dict) -> list[str]:
    candidates = [
        job.get("artifact_dir", ""),
        job.get("run_dir", ""),
        ((manifest.get("paths") or {}).get("artifact_dir") or ""),
        ((manifest.get("paths") or {}).get("run_dir") or ""),
    ]
    seen = set()
    dirs = []
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in seen or not os.path.isdir(normalized):
            continue
        seen.add(normalized)
        dirs.append(normalized)
    return dirs


def _safe_float(value) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _format_metric_value(value) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "--"
    return f"{numeric:.4f}"


def _read_results_history(results_csv_path: str, limit: int = 20) -> list[dict]:
    if not results_csv_path or not os.path.isfile(results_csv_path):
        return []
    try:
        with open(results_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return []
    if not rows:
        return []

    recent_rows = rows[-max(1, int(limit or 20)) :]
    items = []
    for row in recent_rows:
        items.append(
            {
                "epoch": row.get("epoch") or "--",
                "time": _format_metric_value(row.get("time")),
                "train_box_loss": _format_metric_value(row.get("train/box_loss")),
                "train_cls_loss": _format_metric_value(row.get("train/cls_loss")),
                "precision": _format_metric_value(row.get("metrics/precision(B)")),
                "recall": _format_metric_value(row.get("metrics/recall(B)")),
                "mAP50": _format_metric_value(row.get("metrics/mAP50(B)")),
                "mAP50_95": _format_metric_value(row.get("metrics/mAP50-95(B)")),
            }
        )
    return items


def _read_results_rows(results_csv_path: str) -> list[dict]:
    if not results_csv_path or not os.path.isfile(results_csv_path):
        return []
    try:
        with open(results_csv_path, "r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def _best_epoch_snapshot(rows: list[dict]) -> dict:
    best_row = None
    best_score = None
    for row in rows:
        score = _safe_float(row.get("metrics/mAP50-95(B)"))
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_row = row
    if not best_row:
        return {}
    return {
        "epoch": best_row.get("epoch") or "--",
        "precision": _format_metric_value(best_row.get("metrics/precision(B)")),
        "recall": _format_metric_value(best_row.get("metrics/recall(B)")),
        "mAP50": _format_metric_value(best_row.get("metrics/mAP50(B)")),
        "mAP50_95": _format_metric_value(best_row.get("metrics/mAP50-95(B)")),
    }


def _build_report_assessment(job: dict, manifest: dict, summary: dict, rows: list[dict]) -> dict:
    manifest_job = manifest.get("job") or {}
    labeled_count = int(manifest_job.get("labeled_count") or 0)
    train_count = int(((manifest_job.get("split") or {}).get("train_assets")) or 0)
    val_count = int(((manifest_job.get("split") or {}).get("val_assets")) or 0)
    precision = _safe_float(summary.get("metrics/precision(B)"))
    recall = _safe_float(summary.get("metrics/recall(B)"))
    map50 = _safe_float(summary.get("metrics/mAP50(B)"))
    map50_95 = _safe_float(summary.get("metrics/mAP50-95(B)"))
    best_epoch = _best_epoch_snapshot(rows)

    status = "needs_improvement"
    title = "建议继续优化"
    summary_text = "当前模型可以继续迭代，建议先补样本并复核标注后再用于正式识别。"
    if map50_95 is not None and map50_95 >= 0.50 and map50 is not None and map50 >= 0.80:
        status = "good"
        title = "效果较好"
        summary_text = "当前模型已经具备较好的识别能力，可优先使用 best.pt 做演示或小范围试用。"
    elif map50_95 is not None and map50_95 >= 0.35 and map50 is not None and map50 >= 0.65:
        status = "usable"
        title = "可以演示"
        summary_text = "当前模型已具备演示价值，建议优先使用 best.pt，并继续补充样本提升稳定性。"

    recommendations = []
    if labeled_count < 200:
        recommendations.append("当前标注样本量偏少，建议至少补到 200 张以上，再继续训练。")
    elif labeled_count < 500:
        recommendations.append("当前样本量可用于演示，但若要更稳定，建议继续补到 500 张左右。")

    if val_count < 20:
        recommendations.append("验证集样本较少，当前指标波动会偏大，建议补充验证集。")

    if precision is not None and recall is not None and abs(precision - recall) >= 0.15:
        if precision > recall:
            recommendations.append("查准率高于查全率较多，漏检偏多，可增加复杂场景样本并适当放宽阈值测试。")
        else:
            recommendations.append("查全率高于查准率较多，误检偏多，建议补充负样本并复核标注框。")

    if map50_95 is not None and map50 is not None and (map50 - map50_95) >= 0.25:
        recommendations.append("mAP50 与 mAP50-95 差距较大，说明定位还不够稳定，建议继续收紧标注框并补充难样本。")

    if str(job.get("status") or "") == "done":
        recommendations.append("发布或测试时建议优先使用 best.pt，不建议直接使用最后一轮权重。")

    if not recommendations:
        recommendations.append("当前结果较平稳，可先用 best.pt 做演示，再根据误检和漏检继续补样本。")

    sample_level = "low"
    sample_text = "样本量偏少"
    if labeled_count >= 500:
        sample_level = "good"
        sample_text = "样本量较充足"
    elif labeled_count >= 200:
        sample_level = "medium"
        sample_text = "样本量基本够演示"

    return {
        "status": status,
        "title": title,
        "summary": summary_text,
        "sample_level": sample_level,
        "sample_text": sample_text,
        "sample_count": labeled_count,
        "train_count": train_count,
        "val_count": val_count,
        "best_epoch": best_epoch,
        "recommendations": recommendations,
    }


def _collect_report_images(job: dict, manifest: dict) -> list[dict]:
    search_dirs = _collect_search_dirs(job, manifest)
    items = []
    for key, title, filename in _REPORT_IMAGE_SPECS:
        source_path = _first_existing_path(*[os.path.join(base_dir, filename) for base_dir in search_dirs])
        if not source_path:
            continue
        items.append(
            {
                "key": key,
                "title": title,
                "filename": filename,
                "path": source_path,
            }
        )
    return items


def _sanitize_model_name(value: str) -> str:
    raw = os.path.basename(str(value or "").strip())
    if not raw:
        return ""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if not safe:
        return ""
    if not safe.lower().endswith(".pt"):
        safe += ".pt"
    return safe


def _slugify_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("._-")
    return safe or "trained_model"


def _suggest_publish_name(job: dict) -> str:
    dataset_name = _slugify_name(job.get("dataset_name") or job.get("dataset_id") or "dataset")
    return f"{dataset_name}_{job.get('id') or 'best'}.pt"


def _resolve_best_weights_path(job: dict, manifest: dict) -> str:
    paths = manifest.get("paths") or {}
    return _first_existing_path(
        paths.get("best_weights", ""),
        os.path.join(job.get("artifact_dir", ""), "best.pt"),
        os.path.join(job.get("run_dir", ""), "weights", "best.pt"),
    )


def _store_manifest_publish_info(job: dict, manifest: dict, publish_info: dict) -> None:
    if not job.get("manifest_path"):
        return
    payload = dict(manifest or {})
    published_models = list(payload.get("published_models") or [])
    published_models.insert(0, publish_info)
    payload["published_models"] = published_models[:10]
    _write_json(job["manifest_path"], payload)


def build_train_job_report(job_id: str) -> dict:
    job = get_train_job(job_id)
    if not job:
        raise LookupError("job not found")

    manifest = _load_json_file(job.get("manifest_path", ""))
    paths = manifest.get("paths") or {}
    results_csv_path = _first_existing_path(
        paths.get("results_csv", ""),
        os.path.join(job.get("artifact_dir", ""), "results.csv"),
        os.path.join(job.get("run_dir", ""), "results.csv"),
    )
    summary = manifest.get("summary") or _read_results_summary(results_csv_path)
    images = _collect_report_images(job, manifest)
    history = _read_results_history(results_csv_path, limit=20)
    rows = _read_results_rows(results_csv_path)
    assessment = _build_report_assessment(job, manifest, summary, rows)

    report = {
        "job": job,
        "manifest": manifest,
        "summary": summary,
        "metrics": {
            "precision": _format_metric_value(summary.get("metrics/precision(B)")),
            "recall": _format_metric_value(summary.get("metrics/recall(B)")),
            "mAP50": _format_metric_value(summary.get("metrics/mAP50(B)")),
            "mAP50_95": _format_metric_value(summary.get("metrics/mAP50-95(B)")),
        },
        "losses": {
            "box_loss": _format_metric_value(summary.get("train/box_loss")),
            "cls_loss": _format_metric_value(summary.get("train/cls_loss")),
        },
        "history": history,
        "assessment": assessment,
        "images": images,
        "paths": {
            "run_dir": paths.get("run_dir") or job.get("run_dir") or "",
            "artifact_dir": paths.get("artifact_dir") or job.get("artifact_dir") or "",
            "results_csv": results_csv_path,
            "best_weights": _resolve_best_weights_path(job, manifest),
            "args_yaml": _first_existing_path(
                paths.get("args_yaml", ""),
                os.path.join(job.get("artifact_dir", ""), "args.yaml"),
                os.path.join(job.get("run_dir", ""), "args.yaml"),
            ),
            "log_path": paths.get("log_path") or job.get("log_path") or "",
        },
        "publish": {
            "suggested_name": _suggest_publish_name(job),
            "published_models": list(manifest.get("published_models") or []),
        },
    }
    return report


def find_train_job_artifact_path(job_id: str, filename: str) -> str:
    job = get_train_job(job_id)
    if not job:
        raise LookupError("job not found")

    safe_name = os.path.basename(str(filename or "").strip())
    if not safe_name:
        raise FileNotFoundError("artifact not found")

    manifest = _load_json_file(job.get("manifest_path", ""))
    search_dirs = _collect_search_dirs(job, manifest)
    for base_dir in search_dirs:
        candidate = os.path.join(base_dir, safe_name)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    raise FileNotFoundError("artifact not found")


def publish_train_job_best(job_id: str, target_name: str = "") -> dict:
    report = build_train_job_report(job_id)
    job = report["job"]
    if str(job.get("status") or "") != "done":
        raise ValueError("training job is not finished yet")

    source_path = report["paths"].get("best_weights") or ""
    if not source_path or not os.path.isfile(source_path):
        raise FileNotFoundError("best.pt not found")

    requested_name = _sanitize_model_name(target_name or "")
    desired_name = requested_name or report["publish"]["suggested_name"]
    safe_name = _sanitize_model_name(desired_name)
    if not safe_name:
        raise ValueError("invalid target model name")

    os.makedirs(MODEL_DIR, exist_ok=True)
    target_path = os.path.join(MODEL_DIR, safe_name)
    if os.path.abspath(target_path) != os.path.abspath(source_path):
        base_name, ext = os.path.splitext(safe_name)
        suffix = 2
        while os.path.exists(target_path):
            target_path = os.path.join(MODEL_DIR, f"{base_name}_{suffix}{ext}")
            suffix += 1

    shutil.copy2(source_path, target_path)

    metadata = {
        "source_job_id": job.get("id"),
        "dataset_id": job.get("dataset_id"),
        "dataset_name": job.get("dataset_name"),
        "base_model": job.get("base_model"),
        "display_name": target_name or os.path.basename(target_path),
        "lifecycle": "active",
        "usages": ["upload_inference"],
        "created_ts": int(time.time()),
        "source_best_weights": source_path,
        "summary": report.get("summary") or {},
        "confirmed_only": bool(job.get("confirmed_only")),
    }
    metadata_path = os.path.splitext(target_path)[0] + ".meta.json"
    _write_json(metadata_path, metadata)

    publish_info = {
        "model_name": os.path.basename(target_path),
        "model_path": os.path.abspath(target_path),
        "metadata_path": metadata_path,
        "published_ts": int(time.time()),
    }
    _store_manifest_publish_info(job, report.get("manifest") or {}, publish_info)

    return publish_info
