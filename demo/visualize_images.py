"""
Helmet detection — image-folder visualization demo.

Runs the trained helmet detector on every supported image inside an input
folder and writes two artifacts per image:

  1. The image with bounding boxes drawn on top, saved under output/demo_images/.
  2. A side-by-side comparison (original | annotated) saved under
     output/demo_images/comparison/, useful as a still cut in video edits.

Bounding boxes follow a fixed colour scheme:

  helmet     -> green  (BGR 0,200,0)   3px stroke
  no_helmet  -> red    (BGR 0,0,220)   3px stroke
  other      -> grey fallback

Each box gets a "{class} {conf:.2f}" label rendered with cv2.FONT_HERSHEY_SIMPLEX
on a same-coloured semi-transparent background, white text.

Example:
    python demo/visualize_images.py --input /path/to/images
    python demo/visualize_images.py --input ./samples --conf 0.4 --device cpu
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "model" / "helmet-detector.pt"
DEFAULT_OUTPUT = ROOT / "output" / "demo_images"

# BGR colour scheme — keep in sync with demo/visualize_video.py.
CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "helmet": (0, 200, 0),
    "no_helmet": (0, 0, 220),
}
DEFAULT_BOX_COLOR = (160, 160, 160)
BOX_THICKNESS = 3

LABEL_FONT_SCALE = 0.7
LABEL_FONT_THICKNESS = 2
LABEL_TEXT_COLOR = (255, 255, 255)
LABEL_PADDING = 6
LABEL_BG_ALPHA = 0.55

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _print(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[demo:images] {msg}", file=stream)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Visualize helmet detection on a folder of images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input",
        required=True,
        help="Path to a folder containing images (jpg/png/bmp/webp).",
    )
    p.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output directory (default: {DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--model",
        default=str(DEFAULT_MODEL),
        help=f"Path to the helmet detector weights (default: {DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold (default: 0.25).",
    )
    p.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Inference image size (default: 640).",
    )
    p.add_argument(
        "--device",
        default="0",
        help="Inference device ('0' for GPU 0, '0,1' for multi-GPU, 'cpu' for CPU).",
    )
    return p.parse_args()


def _import_runtime():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:
        missing = getattr(exc, "name", str(exc))
        _print(f"missing dependency '{missing}'.", err=True)
        _print("Install with: pip install -r requirements-train.txt", err=True)
        sys.exit(1)
    return cv2, np, YOLO


def _draw_box_with_label(
    cv2_mod,
    image,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    class_name: str,
    confidence: float,
) -> None:
    color = CLASS_COLORS.get(class_name, DEFAULT_BOX_COLOR)
    cv2_mod.rectangle(image, (x1, y1), (x2, y2), color, BOX_THICKNESS)

    label = f"{class_name} {confidence:.2f}"
    (text_w, text_h), _baseline = cv2_mod.getTextSize(
        label,
        cv2_mod.FONT_HERSHEY_SIMPLEX,
        LABEL_FONT_SCALE,
        LABEL_FONT_THICKNESS,
    )

    pad = LABEL_PADDING
    bg_x1 = x1
    bg_y1 = max(0, y1 - text_h - 2 * pad)
    bg_x2 = x1 + text_w + 2 * pad
    bg_y2 = bg_y1 + text_h + 2 * pad

    overlay = image.copy()
    cv2_mod.rectangle(overlay, (bg_x1, bg_y1), (bg_x2, bg_y2), color, -1)
    cv2_mod.addWeighted(overlay, LABEL_BG_ALPHA, image, 1.0 - LABEL_BG_ALPHA, 0, image)

    text_origin = (bg_x1 + pad, bg_y2 - pad)
    cv2_mod.putText(
        image,
        label,
        text_origin,
        cv2_mod.FONT_HERSHEY_SIMPLEX,
        LABEL_FONT_SCALE,
        LABEL_TEXT_COLOR,
        LABEL_FONT_THICKNESS,
        cv2_mod.LINE_AA,
    )


def _annotate_image(cv2_mod, image, result, class_names: dict) -> tuple:
    annotated = image.copy()
    counts: dict[str, int] = {}
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return annotated, counts

    for i in range(len(boxes)):
        cls_id = int(boxes.cls[i].item())
        conf = float(boxes.conf[i].item())
        x1, y1, x2, y2 = (int(v) for v in boxes.xyxy[i].tolist())
        class_name = str(class_names.get(cls_id, cls_id))
        _draw_box_with_label(cv2_mod, annotated, x1, y1, x2, y2, class_name, conf)
        counts[class_name] = counts.get(class_name, 0) + 1
    return annotated, counts


def _make_comparison(np_mod, original, annotated):
    if original.shape != annotated.shape:
        # Should not happen for normal images, but guard against rare edge cases.
        return annotated
    return np_mod.concatenate([original, annotated], axis=1)


def _summarize_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "no detections"
    return ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))


def main() -> None:
    args = parse_args()
    cv2_mod, np_mod, YOLO = _import_runtime()

    input_dir = Path(args.input).resolve()
    if not input_dir.is_dir():
        _print(f"input is not a directory: {input_dir}", err=True)
        sys.exit(1)

    model_path = Path(args.model).resolve()
    if not model_path.is_file():
        _print(f"model weights not found: {model_path}", err=True)
        _print("Hint: run scripts/train_helmet_model.py first.", err=True)
        sys.exit(1)

    output_dir = Path(args.output).resolve()
    annotated_dir = output_dir
    comparison_dir = output_dir / "comparison"
    annotated_dir.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        _print(f"no supported images found in {input_dir}", err=True)
        sys.exit(1)

    _print(f"loading model: {model_path}")
    model = YOLO(str(model_path))
    class_names: dict = dict(getattr(model, "names", {}) or {})

    _print(f"processing {len(images)} image(s) ...")
    processed = 0
    for img_path in images:
        image = cv2_mod.imread(str(img_path))
        if image is None:
            _print(f"  skipping unreadable image: {img_path.name}", err=True)
            continue

        prediction = model.predict(
            source=image,
            conf=args.conf,
            imgsz=args.imgsz,
            device=args.device,
            verbose=False,
        )[0]

        annotated, counts = _annotate_image(cv2_mod, image, prediction, class_names)
        comparison = _make_comparison(np_mod, image, annotated)

        annotated_path = annotated_dir / f"{img_path.stem}_annotated{img_path.suffix}"
        comparison_path = comparison_dir / f"{img_path.stem}_compare{img_path.suffix}"
        cv2_mod.imwrite(str(annotated_path), annotated)
        cv2_mod.imwrite(str(comparison_path), comparison)
        processed += 1
        _print(f"  {img_path.name}: {_summarize_counts(counts)}")

    _print("")
    _print(f"done. processed {processed}/{len(images)} image(s).")
    _print(f"annotated:  {annotated_dir}")
    _print(f"comparison: {comparison_dir}")


if __name__ == "__main__":
    main()
