"""
Prepare a helmet detection dataset for YOLOv8 training.

Two sources are supported:

    --source roboflow   (default)
        Download a public hard-hat dataset from Roboflow Universe.
        Recommended project: "Hard Hat Workers" by joseph-nelson
        (workspace=joseph-nelson, project=hard-hat-workers, License: CC BY 4.0).
        Provide the API key via the ROBOFLOW_API_KEY environment variable
        or with --api-key. Get a free key at https://app.roboflow.com.

    --source local
        Import a YOLO-format dataset that already lives on disk.
        Pass --local-path /path/to/dataset.

By default the script merges upstream classes into a simplified two-class
layout: [helmet, no_helmet]. Use --keep-original-classes to preserve the
upstream class layout instead.

Output structure (datasets/helmet/):
    data.yaml
    train/{images,labels}/
    valid/{images,labels}/
    test/{images,labels}/      (only if upstream provides one)

License reminder:
    The default Roboflow project is distributed under CC BY 4.0. If you
    publish a derived model, retain the upstream attribution and license
    notice in your README.

Example:
    # Roboflow source
    export ROBOFLOW_API_KEY=your_key_here
    python scripts/prepare_helmet_dataset.py --source roboflow

    # Local source
    python scripts/prepare_helmet_dataset.py \
        --source local --local-path /data/my_helmet_dataset
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"
HELMET_DIR = DATASETS_DIR / "helmet"


def _load_dotenv_if_available() -> None:
    """Load ROOT/.env into os.environ if python-dotenv is installed.

    Skipped silently when python-dotenv isn't present, so the script keeps
    working on slim installs that only set environment variables directly.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    env_path = ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


# Load .env before argparse defaults read os.environ.
_load_dotenv_if_available()

# Default Roboflow project — well-known, CC BY 4.0
# Version 14 is the current published version on Roboflow Universe;
# earlier versions (e.g. 2) have been retired and now download empty zips.
DEFAULT_WORKSPACE = "joseph-nelson"
DEFAULT_PROJECT = "hard-hat-workers"
DEFAULT_VERSION = 14

# Target simplified class layout
TARGET_CLASSES = ["helmet", "no_helmet"]

# Map common upstream class names → target class name (or None to drop).
# The lookup is case-insensitive after replacing dashes/spaces with underscores.
DEFAULT_CLASS_MAPPING: dict[str, str | None] = {
    "helmet": "helmet",
    "hardhat": "helmet",
    "hard_hat": "helmet",
    "withhelmet": "helmet",
    "with_helmet": "helmet",
    "head": "no_helmet",          # bare head ≈ no helmet (typical for hard-hat sets)
    "no_helmet": "no_helmet",
    "nohelmet": "no_helmet",
    "without_helmet": "no_helmet",
    "withouthelmet": "no_helmet",
    "person": None,                # drop whole-body person box for simplicity
}


def _print(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[helmet-dataset] {msg}", file=stream)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Prepare a helmet detection dataset for YOLOv8 training.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--source",
        choices=["roboflow", "local"],
        default="roboflow",
        help="Dataset source (default: roboflow).",
    )
    p.add_argument(
        "--api-key",
        default=os.getenv("ROBOFLOW_API_KEY", ""),
        help="Roboflow API key (or set ROBOFLOW_API_KEY env var).",
    )
    p.add_argument(
        "--workspace",
        default=DEFAULT_WORKSPACE,
        help=f"Roboflow workspace slug (default: {DEFAULT_WORKSPACE}).",
    )
    p.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Roboflow project slug (default: {DEFAULT_PROJECT}).",
    )
    p.add_argument(
        "--version",
        type=int,
        default=DEFAULT_VERSION,
        help=f"Roboflow version number (default: {DEFAULT_VERSION}).",
    )
    p.add_argument(
        "--local-path",
        help="Path to a YOLO-format dataset (required for --source local).",
    )
    p.add_argument(
        "--output",
        default=str(HELMET_DIR),
        help=f"Output dataset directory (default: {HELMET_DIR}).",
    )
    p.add_argument(
        "--keep-original-classes",
        action="store_true",
        help="Keep upstream class layout instead of merging to [helmet, no_helmet].",
    )
    return p.parse_args()


def _normalize_class_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_class_target(name: str) -> str | None:
    """Look up a class name against DEFAULT_CLASS_MAPPING with light fuzz."""
    normalized = _normalize_class_name(name)
    if normalized in DEFAULT_CLASS_MAPPING:
        return DEFAULT_CLASS_MAPPING[normalized]
    # Try without underscores as a fallback (e.g. "with_helmet" → "withhelmet")
    flat = normalized.replace("_", "")
    if flat in DEFAULT_CLASS_MAPPING:
        return DEFAULT_CLASS_MAPPING[flat]
    return None


def download_from_roboflow(
    api_key: str,
    workspace: str,
    project: str,
    version: int,
    output_dir: Path,
) -> Path:
    try:
        from roboflow import Roboflow  # type: ignore
    except ImportError:
        _print("roboflow package not installed. Install with:", err=True)
        _print("  pip install roboflow", err=True)
        sys.exit(1)

    if not api_key:
        _print("Roboflow API key is required. Set it via:", err=True)
        _print("  - export ROBOFLOW_API_KEY=<your-key>", err=True)
        _print("  - or pass --api-key <your-key>", err=True)
        _print("Get a free key at https://app.roboflow.com .", err=True)
        sys.exit(1)

    output_dir = output_dir.resolve()
    if output_dir.exists():
        _print(f"removing existing dataset at {output_dir} ...")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _print(f"downloading {workspace}/{project} v{version} → {output_dir} ...")
    rf = Roboflow(api_key=api_key)
    project_obj = rf.workspace(workspace).project(project)
    # overwrite=True is required: roboflow-python skips the download silently
    # when `location` already exists, even if it's an empty directory.
    dataset = project_obj.version(version).download(
        "yolov8",
        location=str(output_dir),
        overwrite=True,
    )

    actual_dir = Path(dataset.location).resolve()
    # Some Roboflow SDK versions create a sub-folder inside the requested
    # location. Normalize so that data.yaml ends up directly under output_dir.
    if actual_dir != output_dir:
        for child in actual_dir.iterdir():
            target = output_dir / child.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(child), str(target))
        try:
            actual_dir.rmdir()
        except OSError:
            pass

    if not (output_dir / "data.yaml").exists():
        _print(
            "Downloaded archive did not contain data.yaml. "
            "The Roboflow project layout may have changed.",
            err=True,
        )
        sys.exit(1)

    _print(f"download complete: {output_dir}")
    return output_dir


def import_local_dataset(local_path: str, output_dir: Path) -> Path:
    src = Path(local_path).expanduser().resolve()
    if not src.exists():
        _print(f"local path does not exist: {src}", err=True)
        sys.exit(1)
    if not (src / "data.yaml").exists():
        _print(f"local path is missing data.yaml: {src}", err=True)
        sys.exit(1)

    output_dir = output_dir.resolve()
    if output_dir.exists():
        _print(f"removing existing dataset at {output_dir} ...")
        shutil.rmtree(output_dir)

    _print(f"copying {src} → {output_dir} ...")
    shutil.copytree(src, output_dir)
    return output_dir


def _import_yaml():
    try:
        import yaml  # type: ignore
    except ImportError:
        _print("PyYAML is required. Install with:", err=True)
        _print("  pip install pyyaml  # or: pip install -r requirements-train.txt", err=True)
        sys.exit(1)
    return yaml


def _load_yaml(path: Path) -> dict:
    yaml = _import_yaml()
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _save_yaml(path: Path, data: dict) -> None:
    yaml = _import_yaml()
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _read_class_names(cfg: dict) -> list[str]:
    names = cfg.get("names")
    if isinstance(names, dict):
        # YOLOv8 sometimes uses {0: 'name', ...}
        return [str(names[k]) for k in sorted(names.keys())]
    if isinstance(names, list):
        return [str(n) for n in names]
    return []


def merge_classes(dataset_dir: Path) -> None:
    """Rewrite labels and data.yaml to use simplified [helmet, no_helmet]."""
    data_yaml = dataset_dir / "data.yaml"
    cfg = _load_yaml(data_yaml)
    original_names = _read_class_names(cfg)

    if not original_names:
        _print("could not read class names from data.yaml", err=True)
        sys.exit(1)

    _print(f"upstream classes: {original_names}")

    # Build idx → target_idx mapping
    idx_map: dict[int, int | None] = {}
    drops_unmapped: list[str] = []
    for old_idx, name in enumerate(original_names):
        target = _resolve_class_target(name)
        if target is None:
            idx_map[old_idx] = None
            if _normalize_class_name(name) not in {"person"}:
                drops_unmapped.append(name)
            _print(f"  '{name}' (idx {old_idx}) → drop")
        else:
            new_idx = TARGET_CLASSES.index(target)
            idx_map[old_idx] = new_idx
            _print(f"  '{name}' (idx {old_idx}) → '{target}' (idx {new_idx})")

    if drops_unmapped:
        _print(
            f"note: dropped {len(drops_unmapped)} unrecognized upstream class(es): "
            f"{drops_unmapped}. Use --keep-original-classes if you need them.",
        )

    # Walk all .txt label files and rewrite
    splits_seen: list[str] = []
    rows_modified = 0
    rows_dropped = 0
    files_emptied = 0

    for split in ("train", "valid", "test"):
        labels_dir = dataset_dir / split / "labels"
        if not labels_dir.exists():
            continue
        splits_seen.append(split)
        for txt_path in labels_dir.glob("*.txt"):
            new_lines: list[str] = []
            with open(txt_path, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    try:
                        old_idx = int(parts[0])
                    except (ValueError, IndexError):
                        continue
                    target_idx = idx_map.get(old_idx)
                    if target_idx is None:
                        rows_dropped += 1
                        continue
                    parts[0] = str(target_idx)
                    new_lines.append(" ".join(parts))
                    rows_modified += 1
            with open(txt_path, "w", encoding="utf-8") as fh:
                if new_lines:
                    fh.write("\n".join(new_lines) + "\n")
                else:
                    fh.write("")
                    files_emptied += 1

    _print(
        f"rewrote {rows_modified} label rows ({rows_dropped} dropped) "
        f"across splits: {splits_seen}"
    )
    if files_emptied:
        _print(f"  ({files_emptied} label files became empty after dropping)")

    _write_normalized_data_yaml(dataset_dir, TARGET_CLASSES)


def _write_normalized_data_yaml(dataset_dir: Path, names: list[str]) -> None:
    data_yaml = dataset_dir / "data.yaml"
    cfg = {
        "path": str(dataset_dir.resolve()),
        "train": "train/images",
        "val": "valid/images",
    }
    if (dataset_dir / "test" / "images").exists():
        cfg["test"] = "test/images"
    cfg["nc"] = len(names)
    cfg["names"] = list(names)
    _save_yaml(data_yaml, cfg)
    _print(f"wrote {data_yaml}")


def normalize_data_yaml_keep_original(dataset_dir: Path) -> None:
    """For --keep-original-classes: ensure data.yaml uses absolute paths."""
    data_yaml = dataset_dir / "data.yaml"
    cfg = _load_yaml(data_yaml)
    names = _read_class_names(cfg)
    _write_normalized_data_yaml(dataset_dir, names)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output).resolve()

    if args.source == "roboflow":
        dataset_dir = download_from_roboflow(
            api_key=args.api_key,
            workspace=args.workspace,
            project=args.project,
            version=args.version,
            output_dir=output_dir,
        )
    else:
        if not args.local_path:
            _print("--local-path is required when --source local", err=True)
            sys.exit(1)
        dataset_dir = import_local_dataset(args.local_path, output_dir)

    if args.keep_original_classes:
        normalize_data_yaml_keep_original(dataset_dir)
        _print("kept upstream class layout (--keep-original-classes)")
    else:
        merge_classes(dataset_dir)

    _print("")
    _print(f"dataset ready at {dataset_dir}")
    _print(f"next: python scripts/train_helmet_model.py --data {dataset_dir / 'data.yaml'}")


if __name__ == "__main__":
    main()
