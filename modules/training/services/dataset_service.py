import io
import json
import os
import re
import shutil
import time
import zipfile
from uuid import uuid4

from PIL import Image

from shared.config.config import DATASETS_DIR
from shared.db.sqlite import count_dataset_assets
from shared.db.sqlite import get_dataset_asset as get_saved_dataset_asset
from shared.db.sqlite import get_dataset as get_saved_dataset
from shared.db.sqlite import list_dataset_assets as list_saved_dataset_assets
from shared.db.sqlite import list_datasets as list_saved_datasets
from shared.db.sqlite import save_dataset, save_dataset_asset


DATASET_SUBDIRS = ("images", "labels", "splits", "exports")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
REVIEW_STATUSES = {"pending", "reviewed", "confirmed"}
REVIEWED_STATUSES = {"reviewed", "confirmed"}


def _clean_dataset_name(value: str) -> str:
    name = " ".join((value or "").strip().split())
    if not name:
        raise ValueError("数据集名称不能为空")
    if len(name) > 80:
        raise ValueError("数据集名称过长")
    return name


def _parse_class_names(value) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,;\n\r]+", str(value or ""))

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = " ".join(str(raw_item or "").strip().split())
        if not item:
            continue
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(item)

    if not items:
        raise ValueError("至少填写一个类别")
    if len(items) > 50:
        raise ValueError("类别数量过多")
    return items


def _clean_notes(value: str) -> str:
    notes = str(value or "").strip()
    if len(notes) > 500:
        raise ValueError("备注内容过长")
    return notes


def _new_dataset_id() -> str:
    return "ds_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]


def _ensure_dataset_dirs(root_dir: str) -> None:
    os.makedirs(root_dir, exist_ok=False)
    for subdir in DATASET_SUBDIRS:
        os.makedirs(os.path.join(root_dir, subdir), exist_ok=True)


def _require_dataset(dataset_id: str) -> dict:
    dataset = get_saved_dataset(dataset_id)
    if dataset is None:
        raise LookupError("数据集不存在")
    return dataset


def _safe_filename(name: str, fallback: str) -> str:
    base = os.path.basename((name or "").strip()) or fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned or fallback


def _unique_asset_filename(directory: str, origin_name: str, used_names: set[str]) -> str:
    safe_name = _safe_filename(origin_name, "image.jpg")
    root, ext = os.path.splitext(safe_name)
    ext = ext.lower()
    if ext not in IMAGE_EXTS:
        ext = ".jpg"
    root = root or "image"

    candidate = root + ext
    index = 1
    while candidate.lower() in used_names or os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{root}_{index}{ext}"
        index += 1

    used_names.add(candidate.lower())
    return candidate


def create_dataset(name: str, class_names, notes: str = "") -> dict:
    dataset_name = _clean_dataset_name(name)
    dataset_classes = _parse_class_names(class_names)
    dataset_notes = _clean_notes(notes)
    dataset_id = _new_dataset_id()
    root_dir = os.path.join(DATASETS_DIR, dataset_id)
    now = int(time.time())

    _ensure_dataset_dirs(root_dir)

    dataset = {
        "id": dataset_id,
        "name": dataset_name,
        "notes": dataset_notes,
        "class_names": dataset_classes,
        "status": "draft",
        "image_count": 0,
        "labeled_count": 0,
        "reviewed_count": 0,
        "version_count": 0,
        "root_dir": root_dir,
        "created_ts": now,
        "updated_ts": now,
    }
    save_dataset(dataset)
    return dataset


def list_datasets(limit: int = 100) -> list[dict]:
    return list_saved_datasets(limit=limit)


def get_dataset(dataset_id: str) -> dict:
    return _require_dataset(dataset_id)


def get_dataset_asset(dataset_id: str, asset_id: str) -> dict:
    _require_dataset(dataset_id)
    asset = get_saved_dataset_asset(dataset_id, asset_id)
    if asset is None:
        raise LookupError("数据集图片不存在")
    return asset


def list_dataset_assets(dataset_id: str, limit: int = 100) -> list[dict]:
    dataset = _require_dataset(dataset_id)
    items = list_saved_dataset_assets(dataset_id, limit=limit)
    return [_attach_asset_label_status(dataset, item) for item in items]


def attach_recent_assets(items: list[dict], limit_per_dataset: int = 4) -> list[dict]:
    output: list[dict] = []
    for item in items:
        dataset = dict(item)
        dataset["recent_assets"] = list_saved_dataset_assets(dataset["id"], limit=limit_per_dataset)
        output.append(dataset)
    return output


def import_zip_to_dataset(dataset_id: str, upload_file) -> dict:
    dataset = _require_dataset(dataset_id)
    if upload_file is None or not getattr(upload_file, "filename", ""):
        raise ValueError("请选择 ZIP 文件")

    upload_name = os.path.basename(upload_file.filename or "")
    if os.path.splitext(upload_name)[1].lower() != ".zip":
        raise ValueError("仅支持 ZIP 文件")

    images_dir = os.path.join(dataset["root_dir"], "images")
    os.makedirs(images_dir, exist_ok=True)
    used_names = {entry.lower() for entry in os.listdir(images_dir)}

    try:
        upload_file.stream.seek(0)
    except Exception:
        pass

    imported = 0
    skipped = 0
    now = int(time.time())

    try:
        with zipfile.ZipFile(upload_file.stream) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue

                ext = os.path.splitext(member.filename)[1].lower()
                if ext not in IMAGE_EXTS:
                    skipped += 1
                    continue

                try:
                    payload = archive.read(member)
                except Exception:
                    skipped += 1
                    continue

                try:
                    with Image.open(io.BytesIO(payload)) as image:
                        image.load()
                        width, height = image.size
                except Exception:
                    skipped += 1
                    continue

                origin_name = os.path.basename(member.filename) or f"image_{imported + skipped + 1}{ext}"
                stored_name = _unique_asset_filename(images_dir, origin_name, used_names)
                full_path = os.path.join(images_dir, stored_name)
                with open(full_path, "wb") as fh:
                    fh.write(payload)

                save_dataset_asset(
                    {
                        "id": uuid4().hex,
                        "dataset_id": dataset_id,
                        "filename": stored_name,
                        "origin_name": origin_name,
                        "source_type": "zip",
                        "file_path": os.path.abspath(full_path),
                        "width": width,
                        "height": height,
                        "size_bytes": len(payload),
                        "created_ts": now + imported,
                    }
                )
                imported += 1
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"ZIP 文件无法读取: {exc}") from exc

    if imported == 0:
        raise ValueError("ZIP 中没有可导入的有效图片")

    dataset["image_count"] = count_dataset_assets(dataset_id)
    dataset["updated_ts"] = int(time.time())
    save_dataset(dataset)

    return {
        "dataset": dataset,
        "imported": imported,
        "skipped": skipped,
        "upload_name": upload_name,
        "recent_assets": list_saved_dataset_assets(dataset_id, limit=8),
    }


def import_result_assets_to_dataset(
    dataset_id: str,
    source_items: list[dict],
    source_type: str,
    source_job_id: str,
) -> dict:
    dataset = _require_dataset(dataset_id)
    images_dir = os.path.join(dataset["root_dir"], "images")
    os.makedirs(images_dir, exist_ok=True)
    used_names = {entry.lower() for entry in os.listdir(images_dir)}

    imported = 0
    skipped = 0
    now = int(time.time())

    for item in source_items:
        path = str(item.get("path") or "").strip()
        if not path or not os.path.isfile(path):
            skipped += 1
            continue

        origin_name = (
            os.path.basename(str(item.get("origin_name") or "").strip())
            or os.path.basename(str(item.get("name") or "").strip())
            or os.path.basename(path)
            or f"result_{imported + skipped + 1}.jpg"
        )
        stored_name = _unique_asset_filename(images_dir, origin_name, used_names)
        full_path = os.path.join(images_dir, stored_name)

        try:
            with Image.open(path) as image:
                image.load()
                width, height = image.size
        except Exception:
            skipped += 1
            continue

        shutil.copy2(path, full_path)

        save_dataset_asset(
            {
                "id": uuid4().hex,
                "dataset_id": dataset_id,
                "filename": stored_name,
                "origin_name": origin_name,
                "source_type": source_type,
                "source_job_id": source_job_id,
                "source_asset_id": item.get("id", ""),
                "file_path": os.path.abspath(full_path),
                "width": width,
                "height": height,
                "size_bytes": os.path.getsize(full_path),
                "created_ts": now + imported,
            }
        )
        imported += 1

    if imported == 0:
        raise ValueError("所选结果图未能导入到数据集")

    dataset = _refresh_dataset_counters(dataset)

    return {
        "dataset": dataset,
        "imported": imported,
        "skipped": skipped,
        "recent_assets": list_saved_dataset_assets(dataset_id, limit=8),
    }


def _label_path(dataset: dict, asset: dict) -> str:
    labels_dir = os.path.join(dataset["root_dir"], "labels")
    os.makedirs(labels_dir, exist_ok=True)
    stem, _ext = os.path.splitext(asset.get("filename") or asset.get("origin_name") or "image")
    stem = stem or "image"
    return os.path.join(labels_dir, stem + ".txt")


def _label_meta_path(dataset: dict, asset: dict) -> str:
    labels_dir = os.path.join(dataset["root_dir"], "labels")
    os.makedirs(labels_dir, exist_ok=True)
    stem, _ext = os.path.splitext(asset.get("filename") or asset.get("origin_name") or "image")
    stem = stem or "image"
    return os.path.join(labels_dir, stem + ".meta.json")


def _read_annotation_meta(dataset: dict, asset: dict) -> dict:
    meta_path = _label_meta_path(dataset, asset)
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_annotation_meta(dataset: dict, asset: dict, payload: dict) -> str:
    meta_path = _label_meta_path(dataset, asset)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return meta_path


def _remove_annotation_meta(dataset: dict, asset: dict) -> None:
    meta_path = _label_meta_path(dataset, asset)
    if os.path.isfile(meta_path):
        os.remove(meta_path)


def _normalize_review_status(value) -> str:
    status = str(value or "").strip().lower()
    if status not in REVIEW_STATUSES:
        return "pending"
    return status


def _label_file_has_content(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return any(line.strip() for line in fh)
    except Exception:
        return False


def is_asset_labeled(dataset: dict, asset: dict) -> bool:
    return _label_file_has_content(_label_path(dataset, asset))


def _attach_asset_label_status(dataset: dict, asset: dict) -> dict:
    item = dict(asset)
    item["is_labeled"] = is_asset_labeled(dataset, asset)
    meta = _read_annotation_meta(dataset, asset)
    confidence_values = []
    for box in meta.get("boxes", []) if isinstance(meta.get("boxes"), list) else []:
        confidence = box.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence_values.append(float(confidence))
    item["confidence_count"] = len(confidence_values)
    item["min_confidence"] = round(min(confidence_values), 4) if confidence_values else None
    item["max_confidence"] = round(max(confidence_values), 4) if confidence_values else None
    item["annotation_source"] = str(meta.get("source") or "")
    item["review_status"] = _normalize_review_status(meta.get("review_status"))
    item["is_reviewed"] = item["review_status"] in REVIEWED_STATUSES
    item["reviewed_ts"] = int(meta.get("reviewed_ts") or 0) if meta.get("reviewed_ts") else None
    return item


def _count_labeled_assets(dataset: dict) -> int:
    labels_dir = os.path.join(dataset["root_dir"], "labels")
    if not os.path.isdir(labels_dir):
        return 0
    count = 0
    for name in os.listdir(labels_dir):
        if not name.lower().endswith(".txt"):
            continue
        path = os.path.join(labels_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                if any(line.strip() for line in fh):
                    count += 1
        except Exception:
            continue
    return count


def _count_reviewed_assets(dataset: dict) -> int:
    count = 0
    for asset in list_saved_dataset_assets(dataset["id"], limit=5000):
        if not asset:
            continue
        meta = _read_annotation_meta(dataset, asset)
        if _normalize_review_status(meta.get("review_status")) in REVIEWED_STATUSES:
            count += 1
    return count


def _refresh_dataset_counters(dataset: dict) -> dict:
    dataset["image_count"] = count_dataset_assets(dataset["id"])
    dataset["labeled_count"] = _count_labeled_assets(dataset)
    dataset["reviewed_count"] = _count_reviewed_assets(dataset)
    dataset["updated_ts"] = int(time.time())
    save_dataset(dataset)
    return dataset


def load_asset_annotation(dataset_id: str, asset_id: str) -> dict:
    dataset = _require_dataset(dataset_id)
    asset = get_dataset_asset(dataset_id, asset_id)
    width = int(asset.get("width") or 0)
    height = int(asset.get("height") or 0)
    label_path = _label_path(dataset, asset)
    label_meta = _read_annotation_meta(dataset, asset)
    meta_boxes = label_meta.get("boxes", []) if isinstance(label_meta.get("boxes"), list) else []
    boxes: list[dict] = []

    if os.path.isfile(label_path) and width > 0 and height > 0:
        with open(label_path, "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.strip().split()
                if len(parts) != 5:
                    continue
                try:
                    class_index = int(float(parts[0]))
                    x_center = float(parts[1]) * width
                    y_center = float(parts[2]) * height
                    box_width = float(parts[3]) * width
                    box_height = float(parts[4]) * height
                except Exception:
                    continue
                x1 = max(0.0, x_center - box_width / 2.0)
                y1 = max(0.0, y_center - box_height / 2.0)
                x2 = min(float(width), x_center + box_width / 2.0)
                y2 = min(float(height), y_center + box_height / 2.0)
                class_names = dataset.get("class_names") or []
                boxes.append(
                    {
                        "class_index": class_index,
                        "class_name": class_names[class_index] if 0 <= class_index < len(class_names) else "",
                        "x1": round(x1, 2),
                        "y1": round(y1, 2),
                        "x2": round(x2, 2),
                        "y2": round(y2, 2),
                        "confidence": None,
                    }
                )

    for index, meta_box in enumerate(meta_boxes):
        if index >= len(boxes):
            break
        confidence = meta_box.get("confidence")
        if isinstance(confidence, (int, float)):
            boxes[index]["confidence"] = round(float(confidence), 4)

    return {
        "dataset": dataset,
        "asset": _attach_asset_label_status(dataset, asset),
        "boxes": boxes,
        "label_path": os.path.abspath(label_path),
        "label_meta_path": os.path.abspath(_label_meta_path(dataset, asset)),
        "is_labeled": bool(boxes),
        "review_status": _normalize_review_status(label_meta.get("review_status")),
        "reviewed_ts": int(label_meta.get("reviewed_ts") or 0) if label_meta.get("reviewed_ts") else None,
    }


def save_asset_annotation(dataset_id: str, asset_id: str, boxes_payload) -> dict:
    dataset = _require_dataset(dataset_id)
    asset = get_dataset_asset(dataset_id, asset_id)
    width = int(asset.get("width") or 0)
    height = int(asset.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效，无法保存标注")

    if not isinstance(boxes_payload, list):
        raise ValueError("boxes must be a list")

    class_names = dataset.get("class_names") or []
    lines: list[str] = []
    normalized_boxes: list[dict] = []
    meta_boxes: list[dict] = []
    for raw_box in boxes_payload:
        if not isinstance(raw_box, dict):
            continue
        try:
            class_index = int(raw_box.get("class_index"))
            x1 = float(raw_box.get("x1"))
            y1 = float(raw_box.get("y1"))
            x2 = float(raw_box.get("x2"))
            y2 = float(raw_box.get("y2"))
        except Exception as exc:
            raise ValueError(f"invalid box payload: {exc}") from exc

        if class_index < 0 or class_index >= len(class_names):
            raise ValueError("class_index out of range")

        left = max(0.0, min(x1, x2))
        top = max(0.0, min(y1, y2))
        right = min(float(width), max(x1, x2))
        bottom = min(float(height), max(y1, y2))
        box_width = right - left
        box_height = bottom - top
        if box_width < 2 or box_height < 2:
            continue

        x_center = (left + right) / 2.0 / width
        y_center = (top + bottom) / 2.0 / height
        norm_w = box_width / width
        norm_h = box_height / height
        lines.append(f"{class_index} {x_center:.6f} {y_center:.6f} {norm_w:.6f} {norm_h:.6f}")
        normalized_boxes.append(
            {
                "class_index": class_index,
                "class_name": class_names[class_index],
                "x1": round(left, 2),
                "y1": round(top, 2),
                "x2": round(right, 2),
                "y2": round(bottom, 2),
                "confidence": round(float(raw_box.get("confidence")), 4)
                if isinstance(raw_box.get("confidence"), (int, float))
                else None,
            }
        )
        meta_box = {"class_index": class_index}
        if isinstance(raw_box.get("confidence"), (int, float)):
            meta_box["confidence"] = round(float(raw_box.get("confidence")), 4)
        meta_boxes.append(meta_box)

    label_path = _label_path(dataset, asset)
    existing_meta = _read_annotation_meta(dataset, asset)
    if lines:
        with open(label_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        _write_annotation_meta(
            dataset,
            asset,
            {
                **existing_meta,
                "source": "auto" if any(box.get("confidence") is not None for box in normalized_boxes) else "manual",
                "boxes": meta_boxes,
                "updated_ts": int(time.time()),
            },
        )
    elif os.path.isfile(label_path):
        os.remove(label_path)
        _remove_annotation_meta(dataset, asset)

    dataset = _refresh_dataset_counters(dataset)
    return {
        "dataset": dataset,
        "asset": _attach_asset_label_status(dataset, asset),
        "boxes": normalized_boxes,
        "label_path": os.path.abspath(label_path),
        "label_meta_path": os.path.abspath(_label_meta_path(dataset, asset)),
        "is_labeled": bool(normalized_boxes),
        "review_status": _normalize_review_status(existing_meta.get("review_status")),
        "reviewed_ts": int(existing_meta.get("reviewed_ts") or 0) if existing_meta.get("reviewed_ts") else None,
    }


def update_asset_review_status(dataset_id: str, asset_id: str, review_status: str) -> dict:
    dataset = _require_dataset(dataset_id)
    asset = get_dataset_asset(dataset_id, asset_id)
    status = _normalize_review_status(review_status)
    now = int(time.time())
    meta = _read_annotation_meta(dataset, asset)
    meta.setdefault("boxes", [])
    meta.setdefault("source", "")
    meta["review_status"] = status
    meta["reviewed_ts"] = now if status in REVIEWED_STATUSES else None
    meta["updated_ts"] = now
    _write_annotation_meta(dataset, asset, meta)

    dataset = _refresh_dataset_counters(dataset)
    payload = load_asset_annotation(dataset_id, asset_id)
    payload["dataset"] = dataset
    payload["asset"] = _attach_asset_label_status(dataset, asset)
    payload["review_status"] = status
    payload["reviewed_ts"] = meta.get("reviewed_ts")
    return payload


def summarize_datasets(items: list[dict]) -> dict[str, int]:
    summary = {
        "dataset_count": len(items),
        "image_count": 0,
        "labeled_count": 0,
        "reviewed_count": 0,
        "version_count": 0,
    }
    for item in items:
        summary["image_count"] += int(item.get("image_count") or 0)
        summary["labeled_count"] += int(item.get("labeled_count") or 0)
        summary["reviewed_count"] += int(item.get("reviewed_count") or 0)
        summary["version_count"] += int(item.get("version_count") or 0)
    return summary
