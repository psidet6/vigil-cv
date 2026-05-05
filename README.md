# Vigil CV

Vigil CV demonstrates how to build a lightweight visual recognition management system with YOLOv8, YOLO-World, InsightFace, Flask, PostgreSQL, and Tailwind CSS. The project includes database-backed batch inference, local media upload, result review, face-library matching, notification workflow previews, dataset management, annotation, and model training workflows.

The repository is designed as a generic engineering reference for visual detection systems. It does not include real runtime data, model weights, database credentials, internal hostnames, or organization-specific documents.

## Example Scenarios

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
