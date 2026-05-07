"""
Helmet detection — video file annotation demo.

Reads a video frame by frame, runs the trained helmet detector on every
frame, and writes:

  - output/demo_videos/{name}_annotated.mp4   The annotated video.
  - output/demo_videos/{name}_annotated.log   Per-frame timing CSV log.

Bounding boxes follow the same colour scheme as visualize_images.py
(helmet -> green, no_helmet -> red, 3px stroke). A small stats HUD is
rendered in the top-right corner of every frame:

    Frame: {n}/{total}
    Helmet: {count}
    No Helmet: {count}

The HUD has a black semi-transparent background and white text.

Example:
    python demo/visualize_video.py --input site_walk.mp4
    python demo/visualize_video.py --input clip.mov --device cpu --conf 0.4
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "model" / "helmet-detector.pt"
DEFAULT_OUTPUT = ROOT / "output" / "demo_videos"

# Box style — keep in sync with demo/visualize_images.py.
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

# HUD style.
HUD_BG_COLOR = (0, 0, 0)
HUD_BG_ALPHA = 0.55
HUD_TEXT_COLOR = (255, 255, 255)
HUD_FONT_SCALE = 0.7
HUD_FONT_THICKNESS = 2
HUD_LINE_HEIGHT = 30
HUD_PADDING_X = 14
HUD_PADDING_Y = 12
HUD_MARGIN_RIGHT = 18
HUD_MARGIN_TOP = 18

# Output codec.
OUTPUT_FOURCC = "mp4v"


def _print(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[demo:video] {msg}", file=stream)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Annotate a video with helmet detection bounding boxes and a stats HUD.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input",
        required=True,
        help="Path to the input video file (.mp4, .mov, .avi, .mkv, ...).",
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
        help="Inference device ('0' for GPU 0, 'cpu' for CPU).",
    )
    p.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Optional cap on processed frames (0 = process the whole video).",
    )
    return p.parse_args()


def _import_runtime():
    try:
        import cv2  # type: ignore
        from tqdm import tqdm  # type: ignore
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:
        missing = getattr(exc, "name", str(exc))
        _print(f"missing dependency '{missing}'.", err=True)
        _print("Install with: pip install -r requirements-train.txt", err=True)
        sys.exit(1)
    return cv2, tqdm, YOLO


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

    cv2_mod.putText(
        image,
        label,
        (bg_x1 + pad, bg_y2 - pad),
        cv2_mod.FONT_HERSHEY_SIMPLEX,
        LABEL_FONT_SCALE,
        LABEL_TEXT_COLOR,
        LABEL_FONT_THICKNESS,
        cv2_mod.LINE_AA,
    )


def _annotate_frame(cv2_mod, frame, result, class_names: dict) -> tuple:
    counts: dict[str, int] = {}
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return frame, counts

    for i in range(len(boxes)):
        cls_id = int(boxes.cls[i].item())
        conf = float(boxes.conf[i].item())
        x1, y1, x2, y2 = (int(v) for v in boxes.xyxy[i].tolist())
        class_name = str(class_names.get(cls_id, cls_id))
        _draw_box_with_label(cv2_mod, frame, x1, y1, x2, y2, class_name, conf)
        counts[class_name] = counts.get(class_name, 0) + 1
    return frame, counts


def _draw_hud(cv2_mod, frame, frame_index: int, total_frames: int, counts: dict[str, int]) -> None:
    height, width = frame.shape[:2]

    helmet_n = counts.get("helmet", 0)
    no_helmet_n = counts.get("no_helmet", 0)
    lines = [
        f"Frame: {frame_index}/{total_frames}" if total_frames else f"Frame: {frame_index}",
        f"Helmet: {helmet_n}",
        f"No Helmet: {no_helmet_n}",
    ]

    text_widths = []
    for line in lines:
        (w, _h), _ = cv2_mod.getTextSize(
            line,
            cv2_mod.FONT_HERSHEY_SIMPLEX,
            HUD_FONT_SCALE,
            HUD_FONT_THICKNESS,
        )
        text_widths.append(w)
    max_w = max(text_widths)

    box_w = max_w + 2 * HUD_PADDING_X
    box_h = HUD_LINE_HEIGHT * len(lines) + 2 * HUD_PADDING_Y - HUD_LINE_HEIGHT // 3

    box_x2 = width - HUD_MARGIN_RIGHT
    box_x1 = box_x2 - box_w
    box_y1 = HUD_MARGIN_TOP
    box_y2 = box_y1 + box_h

    overlay = frame.copy()
    cv2_mod.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), HUD_BG_COLOR, -1)
    cv2_mod.addWeighted(overlay, HUD_BG_ALPHA, frame, 1.0 - HUD_BG_ALPHA, 0, frame)

    text_x = box_x1 + HUD_PADDING_X
    text_y = box_y1 + HUD_PADDING_Y + HUD_LINE_HEIGHT - 8
    for line in lines:
        cv2_mod.putText(
            frame,
            line,
            (text_x, text_y),
            cv2_mod.FONT_HERSHEY_SIMPLEX,
            HUD_FONT_SCALE,
            HUD_TEXT_COLOR,
            HUD_FONT_THICKNESS,
            cv2_mod.LINE_AA,
        )
        text_y += HUD_LINE_HEIGHT


def _open_writer(cv2_mod, output_path: Path, fps: float, width: int, height: int):
    fourcc = cv2_mod.VideoWriter_fourcc(*OUTPUT_FOURCC)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2_mod.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        _print(f"failed to open video writer for {output_path}", err=True)
        sys.exit(1)
    return writer


def main() -> None:
    args = parse_args()
    cv2_mod, tqdm_mod, YOLO = _import_runtime()

    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        _print(f"input video not found: {input_path}", err=True)
        sys.exit(1)

    model_path = Path(args.model).resolve()
    if not model_path.is_file():
        _print(f"model weights not found: {model_path}", err=True)
        _print("Hint: run scripts/train_helmet_model.py first.", err=True)
        sys.exit(1)

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_video = output_dir / f"{input_path.stem}_annotated.mp4"
    output_log = output_dir / f"{input_path.stem}_annotated.log"

    cap = cv2_mod.VideoCapture(str(input_path))
    if not cap.isOpened():
        _print(f"failed to open input video: {input_path}", err=True)
        sys.exit(1)

    width = int(cap.get(cv2_mod.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2_mod.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2_mod.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2_mod.CAP_PROP_FRAME_COUNT) or 0)
    if args.max_frames > 0 and total_frames:
        total_frames = min(total_frames, args.max_frames)

    _print(f"input:  {input_path}  ({width}x{height} @ {fps:.2f} fps, {total_frames or '?'} frames)")
    _print(f"model:  {model_path}")
    _print(f"output: {output_video}")

    model = YOLO(str(model_path))
    class_names: dict = dict(getattr(model, "names", {}) or {})

    writer = _open_writer(cv2_mod, output_video, fps, width, height)
    log_lines = ["frame_index,inference_ms,total_ms,helmet,no_helmet"]

    progress = tqdm_mod(total=total_frames or None, unit="frame", dynamic_ncols=True)
    frame_index = 0
    aggregate_inference_ms = 0.0
    aggregate_total_ms = 0.0

    try:
        while True:
            t_start = time.perf_counter()
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if args.max_frames > 0 and frame_index >= args.max_frames:
                break

            t_inf_start = time.perf_counter()
            prediction = model.predict(
                source=frame,
                conf=args.conf,
                imgsz=args.imgsz,
                device=args.device,
                verbose=False,
            )[0]
            inference_ms = (time.perf_counter() - t_inf_start) * 1000.0

            frame, counts = _annotate_frame(cv2_mod, frame, prediction, class_names)
            _draw_hud(
                cv2_mod,
                frame,
                frame_index=frame_index + 1,
                total_frames=total_frames,
                counts=counts,
            )
            writer.write(frame)

            total_ms = (time.perf_counter() - t_start) * 1000.0
            aggregate_inference_ms += inference_ms
            aggregate_total_ms += total_ms
            log_lines.append(
                f"{frame_index},{inference_ms:.2f},{total_ms:.2f},"
                f"{counts.get('helmet', 0)},{counts.get('no_helmet', 0)}"
            )

            frame_index += 1
            progress.update(1)
    finally:
        progress.close()
        cap.release()
        writer.release()

    output_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    _print("")
    _print(f"processed {frame_index} frame(s).")
    if frame_index:
        avg_inference = aggregate_inference_ms / frame_index
        avg_total = aggregate_total_ms / frame_index
        avg_fps = 1000.0 / avg_total if avg_total > 0 else 0.0
        _print(f"avg inference: {avg_inference:.2f} ms / frame")
        _print(f"avg pipeline:  {avg_total:.2f} ms / frame  (~{avg_fps:.2f} fps)")
    _print(f"video: {output_video}")
    _print(f"log:   {output_log}")


if __name__ == "__main__":
    main()
