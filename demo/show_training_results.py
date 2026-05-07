"""
Helmet detection — training-run visualization for video content.

Reads a YOLOv8 training run directory (default: runs/train/helmet/) and
produces a tidy set of artifacts under output/demo_training/ that are
suitable for inclusion in a 1080p tech video:

  - training_loss.png        Train vs. validation loss curves.
  - training_map.png         mAP50 / mAP50-95 over epochs.
  - confusion_matrix.png     Copied from the run, if present.
  - confusion_matrix_normalized.png   Copied if present.
  - val_batch0_pred.jpg, val_batch0_labels.jpg, labels.jpg   Copied if present.
  - summary.md               Short text summary of best metrics.

Charts use larger fonts and a high-contrast palette tuned for video
playback rather than ultralytics' on-disk default.

Example:
    python demo/show_training_results.py
    python demo/show_training_results.py --run-dir runs/train/helmet2
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = ROOT / "runs" / "train" / "helmet"
DEFAULT_OUTPUT = ROOT / "output" / "demo_training"

# Files to copy verbatim (only those that exist will be copied).
ARTIFACTS_TO_COPY = (
    "confusion_matrix.png",
    "confusion_matrix_normalized.png",
    "results.png",
    "labels.jpg",
    "labels_correlogram.jpg",
    "val_batch0_labels.jpg",
    "val_batch0_pred.jpg",
    "val_batch1_pred.jpg",
)

# High-contrast palette tuned for 1080p video playback.
COLOR_TRAIN = "#FB7299"   # warm pink
COLOR_VAL = "#23ADE5"     # cool blue
COLOR_MAP50 = "#FFB400"   # gold
COLOR_MAP50_95 = "#00C4B6"  # teal
GRID_COLOR = "#E5E5E5"
TEXT_COLOR = "#1F2933"

# Font sizes — readable at 1080p.
TITLE_SIZE = 22
LABEL_SIZE = 18
TICK_SIZE = 14
LEGEND_SIZE = 14
LINE_WIDTH = 2.6

# Figure size in inches; combined with dpi=150 -> 1500x900 px (good for 1080p).
FIGURE_SIZE = (10, 6)
FIGURE_DPI = 150


def _print(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[demo:train-viz] {msg}", file=stream)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Render video-friendly training artifacts from a YOLOv8 run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--run-dir",
        default=str(DEFAULT_RUN_DIR),
        help=f"Path to the YOLOv8 training run directory (default: {DEFAULT_RUN_DIR}).",
    )
    p.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output directory (default: {DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--no-charts",
        action="store_true",
        help="Skip re-rendering charts; only copy supporting artifacts.",
    )
    return p.parse_args()


def _import_matplotlib():
    try:
        import matplotlib  # type: ignore

        matplotlib.use("Agg")  # headless rendering
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError as exc:
        missing = getattr(exc, "name", str(exc))
        _print(f"missing dependency '{missing}'.", err=True)
        _print("Install with: pip install -r requirements-train.txt", err=True)
        sys.exit(1)
    return plt


def _read_results_csv(results_csv: Path) -> tuple[list[str], list[list[str]]]:
    with open(results_csv, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = [row for row in reader if row]
    if not rows:
        return [], []
    header = [col.strip() for col in rows[0]]
    body = rows[1:]
    return header, body


def _column_index(header: list[str], *aliases: str) -> int | None:
    """Return the first matching column index for any of `aliases` (case/space insensitive)."""
    norm = {col.replace(" ", "").lower(): idx for idx, col in enumerate(header)}
    for alias in aliases:
        key = alias.replace(" ", "").lower()
        if key in norm:
            return norm[key]
    return None


def _extract_series(body: list[list[str]], idx: int | None) -> list[float]:
    if idx is None:
        return []
    series: list[float] = []
    for row in body:
        if idx >= len(row):
            series.append(float("nan"))
            continue
        try:
            series.append(float(row[idx]))
        except (ValueError, TypeError):
            series.append(float("nan"))
    return series


def _is_finite_series(values: list[float]) -> bool:
    return any(v == v and v not in (float("inf"), float("-inf")) for v in values)


def _setup_axes(plt, ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=TITLE_SIZE, color=TEXT_COLOR, pad=14)
    ax.set_xlabel(xlabel, fontsize=LABEL_SIZE, color=TEXT_COLOR)
    ax.set_ylabel(ylabel, fontsize=LABEL_SIZE, color=TEXT_COLOR)
    ax.tick_params(axis="both", labelsize=TICK_SIZE, colors=TEXT_COLOR)
    ax.grid(True, color=GRID_COLOR, linestyle="-", linewidth=1)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID_COLOR)


def _render_loss_chart(plt, header: list[str], body: list[list[str]], output: Path) -> bool:
    epoch_idx = _column_index(header, "epoch")
    train_loss_aliases = (
        "train/total_loss",
        "train/loss",
        "train/box_loss",
    )
    val_loss_aliases = (
        "val/total_loss",
        "val/loss",
        "val/box_loss",
    )

    train_idx = _column_index(header, *train_loss_aliases)
    val_idx = _column_index(header, *val_loss_aliases)

    if train_idx is None and val_idx is None:
        _print("no recognised loss columns in results.csv; skipping loss chart.", err=True)
        return False

    epochs = _extract_series(body, epoch_idx) if epoch_idx is not None else list(range(1, len(body) + 1))
    train_series = _extract_series(body, train_idx)
    val_series = _extract_series(body, val_idx)

    fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    if _is_finite_series(train_series):
        ax.plot(epochs[: len(train_series)], train_series, color=COLOR_TRAIN, linewidth=LINE_WIDTH, label="train loss")
    if _is_finite_series(val_series):
        ax.plot(epochs[: len(val_series)], val_series, color=COLOR_VAL, linewidth=LINE_WIDTH, label="val loss")

    _setup_axes(plt, ax, "Training & Validation Loss", "epoch", "loss")
    ax.legend(fontsize=LEGEND_SIZE, frameon=False, loc="upper right")

    fig.tight_layout()
    fig.savefig(output, dpi=FIGURE_DPI, facecolor="white")
    plt.close(fig)
    _print(f"  wrote {output}")
    return True


def _render_map_chart(plt, header: list[str], body: list[list[str]], output: Path) -> bool:
    epoch_idx = _column_index(header, "epoch")
    map50_idx = _column_index(header, "metrics/mAP50(B)", "metrics/mAP50", "mAP50")
    map5095_idx = _column_index(
        header,
        "metrics/mAP50-95(B)",
        "metrics/mAP50-95",
        "mAP50-95",
    )

    if map50_idx is None and map5095_idx is None:
        _print("no recognised mAP columns in results.csv; skipping mAP chart.", err=True)
        return False

    epochs = _extract_series(body, epoch_idx) if epoch_idx is not None else list(range(1, len(body) + 1))
    map50 = _extract_series(body, map50_idx)
    map5095 = _extract_series(body, map5095_idx)

    fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    if _is_finite_series(map50):
        ax.plot(epochs[: len(map50)], map50, color=COLOR_MAP50, linewidth=LINE_WIDTH, label="mAP50")
    if _is_finite_series(map5095):
        ax.plot(epochs[: len(map5095)], map5095, color=COLOR_MAP50_95, linewidth=LINE_WIDTH, label="mAP50-95")

    _setup_axes(plt, ax, "Validation mAP", "epoch", "mAP")
    ax.set_ylim(0.0, 1.0)
    ax.legend(fontsize=LEGEND_SIZE, frameon=False, loc="lower right")

    fig.tight_layout()
    fig.savefig(output, dpi=FIGURE_DPI, facecolor="white")
    plt.close(fig)
    _print(f"  wrote {output}")
    return True


def _copy_artifacts(run_dir: Path, output_dir: Path) -> list[str]:
    copied: list[str] = []
    for filename in ARTIFACTS_TO_COPY:
        src = run_dir / filename
        if not src.is_file():
            continue
        dst = output_dir / filename
        shutil.copy2(src, dst)
        copied.append(filename)
    return copied


def _final_metrics(header: list[str], body: list[list[str]]) -> dict[str, float]:
    if not body:
        return {}
    last_row = body[-1]

    keys = {
        "mAP50": ("metrics/mAP50(B)", "metrics/mAP50", "mAP50"),
        "mAP50-95": ("metrics/mAP50-95(B)", "metrics/mAP50-95", "mAP50-95"),
        "precision": ("metrics/precision(B)", "metrics/precision", "precision"),
        "recall": ("metrics/recall(B)", "metrics/recall", "recall"),
    }
    out: dict[str, float] = {}
    for label, aliases in keys.items():
        idx = _column_index(header, *aliases)
        if idx is None or idx >= len(last_row):
            continue
        try:
            out[label] = float(last_row[idx])
        except (ValueError, TypeError):
            continue
    return out


def _write_summary(
    run_dir: Path,
    output_dir: Path,
    header: list[str],
    body: list[list[str]],
    copied_artifacts: list[str],
    charts: list[str],
) -> Path:
    metrics = _final_metrics(header, body)
    summary_path = output_dir / "summary.md"

    lines: list[str] = []
    lines.append("# Helmet detector training summary")
    lines.append("")
    lines.append(f"- **Run directory:** `{run_dir}`")
    if body:
        lines.append(f"- **Epochs recorded:** {len(body)}")

    if metrics:
        lines.append("")
        lines.append("## Final metrics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| --- | --- |")
        for key in ("mAP50", "mAP50-95", "precision", "recall"):
            if key in metrics:
                lines.append(f"| {key} | {metrics[key]:.4f} |")

    if charts:
        lines.append("")
        lines.append("## Charts")
        lines.append("")
        for name in charts:
            lines.append(f"- `{name}`")

    if copied_artifacts:
        lines.append("")
        lines.append("## Copied artifacts")
        lines.append("")
        for name in copied_artifacts:
            lines.append(f"- `{name}`")

    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path


def main() -> None:
    args = parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        _print(f"run directory not found: {run_dir}", err=True)
        _print("Hint: run scripts/train_helmet_model.py first.", err=True)
        sys.exit(1)

    results_csv = run_dir / "results.csv"
    if not results_csv.is_file():
        _print(f"results.csv not found in {run_dir}", err=True)
        sys.exit(1)

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    header, body = _read_results_csv(results_csv)
    if not header or not body:
        _print(f"results.csv is empty or malformed: {results_csv}", err=True)
        sys.exit(1)

    charts: list[str] = []
    if not args.no_charts:
        plt = _import_matplotlib()
        _print("rendering charts ...")
        if _render_loss_chart(plt, header, body, output_dir / "training_loss.png"):
            charts.append("training_loss.png")
        if _render_map_chart(plt, header, body, output_dir / "training_map.png"):
            charts.append("training_map.png")

    _print("copying supporting artifacts ...")
    copied = _copy_artifacts(run_dir, output_dir)
    for name in copied:
        _print(f"  copied {name}")
    if not copied:
        _print("  (no supporting artifacts found)")

    summary_path = _write_summary(run_dir, output_dir, header, body, copied, charts)

    _print("")
    _print(f"output directory: {output_dir}")
    _print(f"summary:          {summary_path}")


if __name__ == "__main__":
    main()
