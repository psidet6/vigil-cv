import os
import threading
from typing import Optional, Set

import requests
from PIL import Image

from shared.config.config import (
    CLIP_VIT_B32_PATH,
    MOBILECLIP_TS_PATH,
    MOBILECLIP2_TS_PATH,
    TORCH_NUM_THREADS,
    logger,
    model_supports_text_prompt,
    resolve_model_path,
)


ULTR_ERR = None
try:
    from ultralytics import YOLO
    from ultralytics.nn.modules import block as ultralytics_block
    from ultralytics.nn.modules import head as ultralytics_head
    from ultralytics.utils import downloads as ultralytics_downloads
except Exception as exc:
    YOLO = None
    ultralytics_block = None
    ultralytics_head = None
    ultralytics_downloads = None
    ULTR_ERR = str(exc)


_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCKS: dict[str, threading.Lock] = {}
_CACHE_LOCK = threading.Lock()


def _configure_torch_threads() -> None:
    if TORCH_NUM_THREADS <= 0:
        return
    try:
        import torch

        torch.set_num_threads(TORCH_NUM_THREADS)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(max(1, min(2, TORCH_NUM_THREADS)))
        logger.info("Configured torch CPU threads: %s", TORCH_NUM_THREADS)
    except RuntimeError as exc:
        logger.debug("torch CPU thread configuration skipped: %s", exc)
    except Exception as exc:
        logger.warning("failed to configure torch CPU threads: %s", exc)


_configure_torch_threads()

session = requests.Session()
session.headers.update(
    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python/requests"}
)

_DOWNLOAD_PATCHED = False
_CLIP_PATCHED = False


def _model_cache_key(model_key: str) -> str:
    return os.path.normcase(os.path.abspath(resolve_model_path(model_key)))


def _patch_ultralytics_head_compat() -> None:
    """Provide aliases for legacy class names embedded in older model files."""
    if ultralytics_head is None:
        return

    alias_map = {
        "YOLOESegment26": ("Segment26", "YOLOESegment", "Segment"),
        "YOLOSegment26": ("Segment26", "Segment"),
        "YOLOEDetect26": ("YOLOEDetect", "Detect"),
        "YOLODetect26": ("Detect",),
    }

    for missing_name, candidates in alias_map.items():
        if hasattr(ultralytics_head, missing_name):
            continue
        for candidate in candidates:
            target = getattr(ultralytics_head, candidate, None)
            if target is not None:
                setattr(ultralytics_head, missing_name, target)
                logger.info(
                    "Applied ultralytics compatibility alias: %s -> %s",
                    missing_name,
                    candidate,
                )
                break


def _patch_ultralytics_block_compat() -> None:
    """Provide aliases for legacy block names embedded in older model files."""
    if ultralytics_block is None:
        return

    alias_map = {
        "Proto26": ("Proto",),
    }

    for missing_name, candidates in alias_map.items():
        if hasattr(ultralytics_block, missing_name):
            continue
        for candidate in candidates:
            target = getattr(ultralytics_block, candidate, None)
            if target is not None:
                setattr(ultralytics_block, missing_name, target)
                logger.info(
                    "Applied ultralytics compatibility alias: %s -> %s",
                    missing_name,
                    candidate,
                )
                break


def _patch_ultralytics_asset_downloads() -> None:
    """Resolve MobileCLIP TorchScript assets from local files before downloading."""
    global _DOWNLOAD_PATCHED
    if ultralytics_downloads is None or _DOWNLOAD_PATCHED:
        return

    original_attempt_download_asset = ultralytics_downloads.attempt_download_asset
    local_assets = {
        "mobileclip_blt.ts": MOBILECLIP_TS_PATH,
        "mobileclip2_b.ts": MOBILECLIP2_TS_PATH,
    }

    def _attempt_download_asset_offline_first(file, *args, **kwargs):
        asset_name = os.path.basename(str(file))
        local_path = local_assets.get(asset_name)
        if local_path and os.path.isfile(local_path):
            logger.info("Using local text-model asset: %s", local_path)
            return local_path
        return original_attempt_download_asset(file, *args, **kwargs)

    ultralytics_downloads.attempt_download_asset = _attempt_download_asset_offline_first
    _DOWNLOAD_PATCHED = True


def _patch_clip_asset_downloads() -> None:
    """Resolve OpenAI CLIP weights from local files before falling back to user cache/download."""
    global _CLIP_PATCHED
    if _CLIP_PATCHED:
        return

    try:
        import clip
    except Exception:
        return

    original_load = clip.load
    local_assets = {
        "ViT-B/32": CLIP_VIT_B32_PATH,
        "ViT-B-32.pt": CLIP_VIT_B32_PATH,
    }

    def _load_offline_first(name, *args, **kwargs):
        asset_name = str(name)
        local_path = local_assets.get(asset_name) or local_assets.get(os.path.basename(asset_name))
        if local_path and os.path.isfile(local_path):
            logger.info("Using local CLIP asset: %s", local_path)
            return original_load(local_path, *args, **kwargs)
        return original_load(name, *args, **kwargs)

    clip.load = _load_offline_first
    _CLIP_PATCHED = True


def _normalize_names(names) -> list[str]:
    if isinstance(names, dict):
        return [str(names[index]) for index in sorted(names)]
    if isinstance(names, (list, tuple)):
        return [str(item) for item in names]
    return []


def _ensure_general_prompt_state(model, prompt_classes: list[str] | None) -> None:
    default_classes = tuple(getattr(model, "_codex_default_classes", ()))
    if not default_classes:
        default_classes = tuple(_normalize_names(getattr(model, "names", [])))
        model._codex_default_classes = default_classes

    desired_classes = tuple(prompt_classes or default_classes)
    if not desired_classes:
        return

    active_classes = tuple(getattr(model, "_codex_active_classes", ()))
    if active_classes != desired_classes:
        model.set_classes(list(desired_classes))
        model._codex_active_classes = desired_classes


def get_model(model_key: str):
    cache_key = _model_cache_key(model_key)

    with _CACHE_LOCK:
        model = _MODEL_CACHE.get(cache_key)
        if model is not None:
            return model

        if YOLO is None:
            raise RuntimeError(
                f"ultralytics import failed: {ULTR_ERR or 'not installed or missing dependencies'}"
            )

        _patch_ultralytics_asset_downloads()
        _patch_clip_asset_downloads()
        _patch_ultralytics_head_compat()
        _patch_ultralytics_block_compat()

        model_path = resolve_model_path(model_key)
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"model file not found: {model_path}")

        model = YOLO(model_path)
        if model_supports_text_prompt(model_key):
            default_classes = tuple(_normalize_names(getattr(model, "names", [])))
            model._codex_default_classes = default_classes
            model._codex_active_classes = default_classes

        _MODEL_CACHE[cache_key] = model
        _MODEL_LOCKS.setdefault(cache_key, threading.Lock())
        return model


def download_image_with_status(
    url: str, timeout=(6, 15)
) -> tuple[bytes | None, int | None, str | None]:
    try:
        resp = session.get(url, timeout=timeout, stream=True)
        code = resp.status_code
        content_type = resp.headers.get("Content-Type") if hasattr(resp, "headers") else None
        if 200 <= code < 300:
            return resp.content, code, content_type
        return None, code, content_type
    except requests.HTTPError as exc:
        try:
            return None, exc.response.status_code if exc.response is not None else None, None
        except Exception:
            return None, None, None
    except Exception:
        return None, None, None


def _predict_batch(
    images: list[Image.Image],
    model,
    conf_thresh: float,
    allowed_classes: Optional[Set[int]],
    imgsz: int,
    model_key: str,
    prompt_classes: list[str] | None = None,
) -> list[bool]:
    model_lock = _MODEL_LOCKS.setdefault(_model_cache_key(model_key), threading.Lock())
    with model_lock:
        if model_supports_text_prompt(model_key):
            _ensure_general_prompt_state(model, prompt_classes)

        results = model.predict(images, conf=min(conf_thresh, 0.25), imgsz=imgsz, verbose=False)

    output: list[bool] = []
    for result in results:
        try:
            boxes = result.boxes
            if boxes is None or boxes.conf is None:
                output.append(False)
                continue

            conf_list = boxes.conf.tolist()
            if allowed_classes is not None and hasattr(boxes, "cls") and boxes.cls is not None:
                cls_list = [int(item) for item in boxes.cls.tolist()]
                keep = any(
                    float(conf) >= conf_thresh and cls_id in allowed_classes
                    for conf, cls_id in zip(conf_list, cls_list)
                )
            else:
                keep = any(float(conf) >= conf_thresh for conf in conf_list)
            output.append(keep)
        except Exception:
            output.append(False)
    return output


def predict_image_boxes_batch(
    images: list[Image.Image],
    model_key: str,
    conf_thresh: float,
    imgsz: int,
    prompt_classes: list[str] | None = None,
) -> list[list[dict]]:
    if not images:
        return []

    prepared_images: list[Image.Image] = []
    for image in images:
        if image.mode != "RGB":
            prepared_images.append(image.convert("RGB"))
        else:
            prepared_images.append(image)

    model = get_model(model_key)
    model_lock = _MODEL_LOCKS.setdefault(_model_cache_key(model_key), threading.Lock())
    with model_lock:
        if model_supports_text_prompt(model_key):
            _ensure_general_prompt_state(model, prompt_classes)
            predict_conf = max(0.001, min(float(conf_thresh), 0.25))
        else:
            predict_conf = max(0.001, float(conf_thresh))

        results = model.predict(prepared_images, conf=predict_conf, imgsz=imgsz, verbose=False)

    outputs: list[list[dict]] = []
    for result in results:
        items: list[dict] = []
        boxes = getattr(result, "boxes", None)
        names = getattr(result, "names", None) or getattr(model, "names", None) or {}
        if boxes is None or boxes.xyxy is None:
            outputs.append(items)
            continue

        try:
            xyxy_list = boxes.xyxy.tolist()
            conf_list = boxes.conf.tolist() if boxes.conf is not None else [0.0] * len(xyxy_list)
            cls_list = boxes.cls.tolist() if boxes.cls is not None else [0] * len(xyxy_list)
        except Exception:
            outputs.append(items)
            continue

        for coords, conf_value, cls_value in zip(xyxy_list, conf_list, cls_list):
            try:
                class_index = int(cls_value)
                x1, y1, x2, y2 = [float(value) for value in coords[:4]]
            except Exception:
                continue
            if float(conf_value) < float(conf_thresh):
                continue

            class_name = ""
            if isinstance(names, dict):
                class_name = str(names.get(class_index, ""))
            elif isinstance(names, (list, tuple)) and 0 <= class_index < len(names):
                class_name = str(names[class_index])

            items.append(
                {
                    "class_index": class_index,
                    "class_name": class_name,
                    "confidence": round(float(conf_value), 4),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                }
            )

        outputs.append(items)
    return outputs
