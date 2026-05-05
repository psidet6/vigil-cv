import os
import re
from typing import Iterable

from PIL import Image

from shared.config.config import logger, model_supports_text_prompt, resolve_model_path
from modules.training.services.dataset_service import (
    get_dataset,
    get_dataset_asset,
    is_asset_labeled,
    list_dataset_assets,
    save_asset_annotation,
)
from shared.inference.infer_service import predict_image_boxes_batch


AUTO_ANNOTATE_BATCH_SIZE = 8
_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_ALIASES = {
    "rider": ("multirider", "rider"),
    "multirider": ("multirider", "rider"),
    "multipeople": ("multiperson", "person"),
}


def _normalize_token(value: str) -> str:
    return _TOKEN_RE.sub("", str(value or "").strip().lower())


def _parse_name_list(value) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,;\n\r]+", str(value or ""))

    items: list[str] = []
    for raw_item in raw_items:
        item = " ".join(str(raw_item or "").strip().split())
        if item:
            items.append(item)
    return items


def _parse_class_mapping(value, dataset_classes: list[str]) -> dict[str, int]:
    dataset_lookup = {_normalize_token(name): index for index, name in enumerate(dataset_classes)}
    mapping: dict[str, int] = {}

    if isinstance(value, dict):
        pairs: Iterable[tuple[str, object]] = value.items()
    else:
        lines = _parse_name_list(value)
        pairs = []
        parsed_pairs: list[tuple[str, str]] = []
        for line in lines:
            if "=" not in line:
                continue
            left, right = line.split("=", 1)
            parsed_pairs.append((left.strip(), right.strip()))
        pairs = parsed_pairs

    for raw_source, raw_target in pairs:
        source_key = _normalize_token(raw_source)
        if not source_key:
            continue

        target_index = None
        if isinstance(raw_target, int) or str(raw_target).strip().isdigit():
            candidate = int(str(raw_target).strip())
            if 0 <= candidate < len(dataset_classes):
                target_index = candidate
        else:
            target_key = _normalize_token(str(raw_target))
            if target_key in dataset_lookup:
                target_index = dataset_lookup[target_key]

        if target_index is not None:
            mapping[source_key] = target_index

    return mapping


def _resolve_dataset_class_index(
    pred_index: int,
    pred_name: str,
    dataset_classes: list[str],
    class_mapping: dict[str, int],
    prompt_classes: list[str],
) -> int | None:
    name_key = _normalize_token(pred_name)
    index_key = str(int(pred_index))

    if index_key in class_mapping:
        return class_mapping[index_key]
    if name_key and name_key in class_mapping:
        return class_mapping[name_key]

    if prompt_classes and len(prompt_classes) == len(dataset_classes) and 0 <= pred_index < len(dataset_classes):
        return pred_index

    dataset_lookup = {_normalize_token(name): index for index, name in enumerate(dataset_classes)}
    if name_key and name_key in dataset_lookup:
        return dataset_lookup[name_key]

    for alias in _ALIASES.get(name_key, ()):
        if alias in dataset_lookup:
            return dataset_lookup[alias]

    return None


def _prepare_prompt_classes(model_key: str, dataset_classes: list[str], prompt_value) -> list[str]:
    if not model_supports_text_prompt(model_key):
        return []
    prompt_classes = _parse_name_list(prompt_value) if prompt_value else list(dataset_classes)
    if not prompt_classes:
        raise ValueError("开放词表模型需要至少一个提示词")
    return prompt_classes


def _collect_assets(dataset_id: str, asset_ids: list[str], overwrite: bool) -> tuple[dict, list[dict], int]:
    dataset = get_dataset(dataset_id)
    all_items = {item["id"]: item for item in list_dataset_assets(dataset_id, limit=5000)}
    selected_items: list[dict] = []
    skipped_existing = 0

    for asset_id in asset_ids:
        item = all_items.get(asset_id) or get_dataset_asset(dataset_id, asset_id)
        if not overwrite and is_asset_labeled(dataset, item):
            skipped_existing += 1
            continue
        selected_items.append(item)
    return dataset, selected_items, skipped_existing


def auto_annotate_dataset_assets(
    dataset_id: str,
    asset_ids: list[str],
    model_key: str,
    conf_thresh: float,
    imgsz: int,
    prompt_value=None,
    class_mapping_value=None,
    overwrite: bool = False,
    progress_callback=None,
) -> dict:
    if not asset_ids:
        raise ValueError("至少选择一张图片")

    model_path = resolve_model_path(model_key)
    if not os.path.isfile(model_path):
        raise ValueError("预标注模型不存在")

    dataset, selected_items, skipped_existing = _collect_assets(dataset_id, asset_ids, overwrite)
    if not selected_items:
        if callable(progress_callback):
            progress_callback(
                {
                    "total": 0,
                    "processed": 0,
                    "updated": 0,
                    "skipped_existing": skipped_existing,
                    "no_detection": 0,
                }
            )
        return {
            "dataset": dataset,
            "processed": 0,
            "updated": 0,
            "skipped_existing": skipped_existing,
            "no_detection": 0,
            "items": [],
        }

    dataset_classes = dataset.get("class_names") or []
    prompt_classes = _prepare_prompt_classes(model_key, dataset_classes, prompt_value)
    class_mapping = _parse_class_mapping(class_mapping_value, dataset_classes)

    processed = 0
    updated = 0
    no_detection = 0
    updated_items: list[dict] = []
    total = len(selected_items)

    if callable(progress_callback):
        progress_callback(
            {
                "total": total,
                "processed": processed,
                "updated": updated,
                "skipped_existing": skipped_existing,
                "no_detection": no_detection,
            }
        )

    for start in range(0, len(selected_items), AUTO_ANNOTATE_BATCH_SIZE):
        chunk = selected_items[start : start + AUTO_ANNOTATE_BATCH_SIZE]
        images: list[Image.Image] = []
        image_items: list[dict] = []
        for item in chunk:
            path = item.get("file_path") or ""
            if not path or not os.path.isfile(path):
                continue
            try:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
                image_items.append(item)
            except Exception as exc:
                logger.warning("failed to open dataset asset for auto annotation: %s (%s)", path, exc)

        if not images:
            continue

        predictions = predict_image_boxes_batch(
            images=images,
            model_key=model_key,
            conf_thresh=conf_thresh,
            imgsz=imgsz,
            prompt_classes=prompt_classes or None,
        )

        for item, pred_boxes in zip(image_items, predictions):
            processed += 1
            mapped_boxes = []
            for box in pred_boxes:
                target_index = _resolve_dataset_class_index(
                    pred_index=int(box.get("class_index", 0)),
                    pred_name=str(box.get("class_name", "")),
                    dataset_classes=dataset_classes,
                    class_mapping=class_mapping,
                    prompt_classes=prompt_classes,
                )
                if target_index is None:
                    continue
                mapped_boxes.append(
                    {
                        "class_index": target_index,
                        "class_name": dataset_classes[target_index] if 0 <= target_index < len(dataset_classes) else "",
                        "confidence": float(box.get("confidence", 0.0) or 0.0),
                        "x1": box["x1"],
                        "y1": box["y1"],
                        "x2": box["x2"],
                        "y2": box["y2"],
                    }
                )

            if not mapped_boxes:
                no_detection += 1
                if callable(progress_callback):
                    progress_callback(
                        {
                            "total": total,
                            "processed": processed,
                            "updated": updated,
                            "skipped_existing": skipped_existing,
                            "no_detection": no_detection,
                        }
                    )
                continue

            saved = save_asset_annotation(dataset_id, item["id"], mapped_boxes)
            saved_boxes = saved["boxes"]
            for index, saved_box in enumerate(saved_boxes):
                if index < len(mapped_boxes):
                    saved_box["confidence"] = round(float(mapped_boxes[index].get("confidence", 0.0) or 0.0), 4)
            updated += 1
            updated_items.append(
                {
                    "asset": saved["asset"],
                    "boxes": saved_boxes,
                    "is_labeled": saved["is_labeled"],
                    "label_path": saved["label_path"],
                }
            )
            if callable(progress_callback):
                progress_callback(
                    {
                        "total": total,
                        "processed": processed,
                        "updated": updated,
                        "skipped_existing": skipped_existing,
                        "no_detection": no_detection,
                    }
                )

    dataset = get_dataset(dataset_id)
    return {
        "dataset": dataset,
        "processed": processed,
        "updated": updated,
        "skipped_existing": skipped_existing,
        "no_detection": no_detection,
        "items": updated_items,
    }
