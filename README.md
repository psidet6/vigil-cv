# Vigil CV

**Helmet Compliance Detection on Construction Sites (and other vision tasks)**

Vigil CV demonstrates how to build a lightweight visual recognition management system with YOLOv8, YOLO-World, InsightFace, Flask, PostgreSQL, and Tailwind CSS. The default scene is construction-site / factory helmet (PPE) compliance detection, but the architecture is generic enough to host any closed-set or open-vocabulary detection task.

The project includes database-backed batch inference, local media upload, result review, face-library matching, notification workflow previews, dataset management, annotation, and model training workflows.

The repository is designed as a generic engineering reference for visual detection systems. It does not include real runtime data, model weights, database credentials, internal hostnames, or organization-specific documents.

## Example Scenarios

- Construction site PPE (helmet) compliance detection
- Park or campus rule-violation detection
- Factory safety monitoring
- Community entrance and asset review
- Training data collection and model iteration for custom visual tasks

## Architecture

- `modules/detection`: database batch detection and local upload detection
- `modules/face`: face-library cache, feature extraction, and 1:N matching
- `modules/dispatch`: generic notification and task workflow previews
- `modules/training`: dataset import, annotation, auto-annotation, and training jobs
- `shared/db`: SQLite runtime state and PostgreSQL integration
- `shared/inference`: YOLO runtime loading and inference helpers
- `ops`: Docker and environment examples

## Train Your First Model

Get from zero to a running helmet-detection demo in three steps.

### 0. Install training dependencies

```bash
pip install -r requirements-train.txt
```

This adds the `roboflow` and `ultralytics` packages on top of the runtime
deps. The web app itself does not need these — only the helper scripts in
`scripts/` use them.

### 1. Prepare the dataset

```bash
# Option A — Roboflow auto-download (recommended).
# Put your real key in a local .env (which is gitignored), not in
# .env.example. Then either source the file or export inline:
export ROBOFLOW_API_KEY=<your-roboflow-key>
python scripts/prepare_helmet_dataset.py --source roboflow

# Option B — import an existing YOLO-format dataset
python scripts/prepare_helmet_dataset.py --source local --local-path /path/to/dataset
```

The script writes a YOLOv8-compatible dataset to `datasets/helmet/` and
generates a `data.yaml` configuration. Upstream classes are merged into
`[helmet, no_helmet]` by default; pass `--keep-original-classes` to keep
the upstream layout instead.

> **Dataset license**: the default Roboflow project ("Hard Hat Workers" by
> joseph-nelson) is distributed under **CC BY 4.0**. If you publish a
> derived model or video tutorial, retain the upstream attribution and
> link back to the Roboflow Universe project page.

### 2. Train the model

```bash
python scripts/train_helmet_model.py --epochs 50 --imgsz 640 --batch 16
```

Default training takes ~15–60 minutes on a single mid-range GPU. CPU works
too but is much slower (`--device cpu`).

The trained weights are copied to `model/helmet-detector.pt` automatically.
Training curves and the confusion matrix land in `runs/train/helmet/`.

### 3. Run the demo

Continue with **Local Demo Setup** below.

## Local Demo Setup

1. Copy `ops/app.env.local.example` to `app.env`.
2. Keep `POSTGRES_ENABLED=false` and `DISPATCH_MOCK_MODE=true` for demo-only runs.
3. Place required model binaries in `model/` if inference is needed.
4. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

5. Start the app:

```powershell
python app.py
```

The app listens on `http://localhost:5001/` by default.

## PostgreSQL Data Source

All external database-backed flows use the unified `POSTGRES_*` settings:

- image URL query for batch detection
- SMS or notification outbox insert when mock mode is disabled
- person context lookup for notification payloads
- face-library sync SQL

## Not Included

- model weights under `model/`
- runtime output, datasets, uploads, training runs, and face-library caches
- real `.env` or `app.env` files
- private notes, internal records, or organization-specific documents

## License

MIT License. See `LICENSE`.
