"""
Train a YOLOv8s helmet detection model from a prepared dataset.

Prerequisites:
    1. Run scripts/prepare_helmet_dataset.py first to prepare datasets/helmet/.
    2. Install training deps:  pip install ultralytics

Default behaviour:
    - Fine-tune yolov8s.pt (auto-downloaded by ultralytics if missing).
    - Train for 50 epochs at imgsz=640, batch=16.
    - Save training artifacts to runs/train/helmet/ .
    - Copy the best checkpoint to model/helmet-detector.pt .
    - Print final metrics: mAP50, mAP50-95, precision, recall.

Example:
    python scripts/train_helmet_model.py
    python scripts/train_helmet_model.py --epochs 100 --batch 32 --device 0
    python scripts/train_helmet_model.py --device cpu --epochs 10  # quick smoke test
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_YAML = ROOT / "datasets" / "helmet" / "data.yaml"
MODEL_DIR = ROOT / "model"
RUNS_PROJECT_DIR = ROOT / "runs" / "train"
TARGET_WEIGHTS = MODEL_DIR / "helmet-detector.pt"
DEFAULT_BASE_MODEL = "yolov8s.pt"


def _print(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[helmet-train] {msg}", file=stream)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train a YOLOv8s helmet detector.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--data",
        default=str(DEFAULT_DATA_YAML),
        help=f"Path to data.yaml (default: {DEFAULT_DATA_YAML}).",
    )
    p.add_argument(
        "--base-model",
        default=DEFAULT_BASE_MODEL,
        help=(
            "Base model for fine-tuning. Accepts a local .pt path or an "
            "ultralytics model name (default: yolov8s.pt — auto-downloaded "
            "by ultralytics if missing)."
        ),
    )
    p.add_argument("--epochs", type=int, default=50, help="Training epochs (default: 50).")
    p.add_argument("--imgsz", type=int, default=640, help="Image size (default: 640).")
    p.add_argument("--batch", type=int, default=16, help="Batch size (default: 16).")
    p.add_argument(
        "--device",
        default="0",
        help="Training device. Use '0' (or '0,1') for GPU(s), or 'cpu' for CPU.",
    )
    p.add_argument(
        "--name",
        default="helmet",
        help="Run name under runs/train/ (default: helmet).",
    )
    p.add_argument(
        "--project",
        default=str(RUNS_PROJECT_DIR),
        help=f"Run project directory (default: {RUNS_PROJECT_DIR}).",
    )
    p.add_argument(
        "--no-copy-best",
        action="store_true",
        help="Do not copy best.pt to model/helmet-detector.pt after training.",
    )
    return p.parse_args()


def _import_yolo():
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        _print("ultralytics package not installed. Install with:", err=True)
        _print("  pip install ultralytics", err=True)
        sys.exit(1)
    return YOLO


def _validate_dataset(data_yaml: Path) -> None:
    if not data_yaml.exists():
        _print(f"data.yaml not found: {data_yaml}", err=True)
        _print("Run scripts/prepare_helmet_dataset.py first.", err=True)
        sys.exit(1)


def _resolve_base_model(base_model_arg: str) -> str:
    """Resolve a local .pt under model/ or fall through to ultralytics name."""
    candidate = Path(base_model_arg)
    if candidate.is_file():
        return str(candidate.resolve())
    repo_candidate = MODEL_DIR / base_model_arg
    if repo_candidate.is_file():
        return str(repo_candidate.resolve())
    return base_model_arg  # ultralytics will resolve / download


def _format_metric_line(metrics: dict, key: str, label: str) -> str | None:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        return f"  {label:<14} {float(value):.4f}"
    except (TypeError, ValueError):
        return None


def _print_final_metrics(results) -> None:
    metrics: dict = {}
    if hasattr(results, "results_dict") and isinstance(results.results_dict, dict):
        metrics = results.results_dict

    _print("")
    _print("Final metrics:")
    candidates = [
        ("metrics/mAP50(B)", "mAP50"),
        ("metrics/mAP50-95(B)", "mAP50-95"),
        ("metrics/precision(B)", "precision"),
        ("metrics/recall(B)", "recall"),
    ]
    printed_any = False
    for key, label in candidates:
        line = _format_metric_line(metrics, key, label)
        if line:
            print(line)
            printed_any = True
    if not printed_any:
        _print("  (metrics dict empty; check the run directory for results)")


def _copy_best_weights(run_dir: Path, target: Path) -> bool:
    best_pt = run_dir / "weights" / "best.pt"
    if not best_pt.exists():
        _print(f"WARNING: best.pt not found at {best_pt}", err=True)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_pt, target)
    _print(f"copied best weights → {target}")
    return True


def main() -> None:
    args = parse_args()
    data_yaml = Path(args.data).resolve()
    _validate_dataset(data_yaml)

    YOLO = _import_yolo()
    base_model = _resolve_base_model(args.base_model)

    _print(f"data:       {data_yaml}")
    _print(f"base model: {base_model}")
    _print(f"epochs:     {args.epochs}")
    _print(f"imgsz:      {args.imgsz}")
    _print(f"batch:      {args.batch}")
    _print(f"device:     {args.device}")
    _print(f"output:     {Path(args.project) / args.name}")

    model = YOLO(base_model)
    results = model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(Path(args.project).resolve()),
        name=args.name,
        exist_ok=True,
    )

    run_dir = Path(args.project).resolve() / args.name

    if not args.no_copy_best:
        _copy_best_weights(run_dir, TARGET_WEIGHTS)

    _print_final_metrics(results)

    _print("")
    _print(f"training artifacts: {run_dir}")
    if (run_dir / "results.png").exists():
        _print(f"  curves:           {run_dir / 'results.png'}")
    if (run_dir / "confusion_matrix.png").exists():
        _print(f"  confusion matrix: {run_dir / 'confusion_matrix.png'}")
    if not args.no_copy_best and TARGET_WEIGHTS.exists():
        _print(f"  detector weights: {TARGET_WEIGHTS}")


if __name__ == "__main__":
    main()
