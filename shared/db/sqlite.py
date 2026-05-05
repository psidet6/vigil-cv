import json
import os
import sqlite3
import time
import shutil
from typing import Any

from shared.config.config import MODEL_DEFAULT, SQLITE_DB_PATH, logger


JOB_COLUMNS = (
    "job_type",
    "id",
    "source_name",
    "source_type",
    "source_path",
    "temp_dir",
    "frame_interval",
    "status",
    "message",
    "total",
    "processed",
    "kept",
    "notfound",
    "failed",
    "downloaded",
    "start_ts",
    "end_ts",
    "owner_key",
    "owner_ip",
    "conf_thresh",
    "batch_size",
    "imgsz",
    "classes_raw",
    "model_key",
    "zip_paths_json",
    "result_dir",
    "result_manifest_path",
    "identity_result_path",
    "identity_summary_json",
    "summary_text",
)

DATASET_COLUMNS = (
    "id",
    "name",
    "notes",
    "class_names_json",
    "status",
    "image_count",
    "labeled_count",
    "reviewed_count",
    "version_count",
    "root_dir",
    "created_ts",
    "updated_ts",
)

DATASET_ASSET_COLUMNS = (
    "id",
    "dataset_id",
    "filename",
    "origin_name",
    "source_type",
    "source_job_id",
    "source_asset_id",
    "file_path",
    "width",
    "height",
    "size_bytes",
    "created_ts",
)

TRAIN_JOB_COLUMNS = (
    "id",
    "dataset_id",
    "dataset_name",
    "status",
    "message",
    "base_model",
    "base_model_path",
    "preset_key",
    "epochs",
    "imgsz",
    "batch_size",
    "confirmed_only",
    "run_dir",
    "log_path",
    "manifest_path",
    "artifact_dir",
    "created_ts",
    "start_ts",
    "end_ts",
    "owner_key",
    "owner_ip",
)

AUTO_ANNOTATE_JOB_COLUMNS = (
    "id",
    "dataset_id",
    "dataset_name",
    "status",
    "message",
    "model_key",
    "conf_thresh",
    "imgsz",
    "prompt_classes",
    "class_mapping",
    "overwrite",
    "total",
    "processed",
    "updated",
    "skipped_existing",
    "no_detection",
    "created_ts",
    "start_ts",
    "end_ts",
    "owner_key",
    "owner_ip",
)

FACE_LIBRARY_JOB_COLUMNS = (
    "id",
    "action",
    "status",
    "message",
    "stage",
    "processed",
    "total",
    "created_ts",
    "start_ts",
    "end_ts",
    "error",
    "result_json",
    "library_json",
)


def _connect() -> sqlite3.Connection:
    parent = os.path.dirname(SQLITE_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _existing_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _extract_zip_paths(job: dict[str, Any]) -> list[str]:
    if "zip_parts" in job and isinstance(job["zip_parts"], list):
        return [
            part.get("path")
            for part in job["zip_parts"]
            if isinstance(part, dict) and part.get("path")
        ]
    if "zip_paths" in job and isinstance(job["zip_paths"], list):
        return [path for path in job["zip_paths"] if path]
    if job.get("zip_path"):
        return [job["zip_path"]]
    return []


def _row_to_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    job = {column: row[column] for column in JOB_COLUMNS}
    try:
        zip_paths = json.loads(job.get("zip_paths_json") or "[]")
    except Exception:
        zip_paths = []
    try:
        identity_summary = json.loads(job.get("identity_summary_json") or "{}")
    except Exception:
        identity_summary = {}

    job["zip_paths"] = zip_paths
    job["zip_parts"] = [{"path": path, "name": os.path.basename(path)} for path in zip_paths]
    job["zip_path"] = zip_paths[0] if len(zip_paths) == 1 else None
    job["identity_summary"] = identity_summary
    return job


def _row_to_dataset(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    dataset = {column: row[column] for column in DATASET_COLUMNS}
    try:
        class_names = json.loads(dataset.get("class_names_json") or "[]")
    except Exception:
        class_names = []

    dataset["class_names"] = class_names
    return dataset


def _row_to_dataset_asset(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {column: row[column] for column in DATASET_ASSET_COLUMNS}


def _row_to_train_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {column: row[column] for column in TRAIN_JOB_COLUMNS}


def _row_to_auto_annotate_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {column: row[column] for column in AUTO_ANNOTATE_JOB_COLUMNS}


def _row_to_face_library_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    job = {column: row[column] for column in FACE_LIBRARY_JOB_COLUMNS}
    try:
        result = json.loads(job.get("result_json") or "{}")
    except Exception:
        result = {}
    try:
        library = json.loads(job.get("library_json") or "{}")
    except Exception:
        library = {}

    job["result"] = result
    job["library"] = library
    job.pop("result_json", None)
    job.pop("library_json", None)
    return job


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL DEFAULT 'database',
                source_name TEXT,
                source_type TEXT,
                source_path TEXT,
                temp_dir TEXT,
                frame_interval INTEGER,
                status TEXT NOT NULL,
                message TEXT,
                total INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                kept INTEGER NOT NULL DEFAULT 0,
                notfound INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                downloaded INTEGER NOT NULL DEFAULT 0,
                start_ts INTEGER,
                end_ts INTEGER,
                owner_key TEXT,
                owner_ip TEXT,
                conf_thresh REAL,
                batch_size INTEGER,
                imgsz INTEGER,
                classes_raw TEXT,
                model_key TEXT NOT NULL DEFAULT 'general',
                zip_paths_json TEXT,
                result_dir TEXT,
                result_manifest_path TEXT,
                identity_result_path TEXT,
                identity_summary_json TEXT,
                summary_text TEXT
            )
            """
        )

        columns = _existing_columns(conn, "jobs")
        if "model_key" not in columns:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN model_key TEXT NOT NULL DEFAULT 'general'"
            )
        if "job_type" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'database'")
        if "source_name" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN source_name TEXT")
        if "source_type" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN source_type TEXT")
        if "source_path" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN source_path TEXT")
        if "temp_dir" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN temp_dir TEXT")
        if "frame_interval" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN frame_interval INTEGER")
        if "owner_key" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN owner_key TEXT")
        if "result_dir" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN result_dir TEXT")
        if "result_manifest_path" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN result_manifest_path TEXT")
        if "identity_result_path" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN identity_result_path TEXT")
        if "identity_summary_json" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN identity_summary_json TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_owner_key_start_ts ON jobs(owner_key, start_ts DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_owner_start_ts ON jobs(owner_ip, start_ts DESC)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_end_ts ON jobs(end_ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                class_names_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'draft',
                image_count INTEGER NOT NULL DEFAULT 0,
                labeled_count INTEGER NOT NULL DEFAULT 0,
                reviewed_count INTEGER NOT NULL DEFAULT 0,
                version_count INTEGER NOT NULL DEFAULT 0,
                root_dir TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            )
            """
        )

        dataset_columns = _existing_columns(conn, "datasets")
        if "notes" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "class_names_json" not in dataset_columns:
            conn.execute(
                "ALTER TABLE datasets ADD COLUMN class_names_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "status" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'")
        if "image_count" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN image_count INTEGER NOT NULL DEFAULT 0")
        if "labeled_count" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN labeled_count INTEGER NOT NULL DEFAULT 0")
        if "reviewed_count" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN reviewed_count INTEGER NOT NULL DEFAULT 0")
        if "version_count" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN version_count INTEGER NOT NULL DEFAULT 0")
        if "root_dir" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN root_dir TEXT NOT NULL DEFAULT ''")
        if "created_ts" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN created_ts INTEGER NOT NULL DEFAULT 0")
        if "updated_ts" not in dataset_columns:
            conn.execute("ALTER TABLE datasets ADD COLUMN updated_ts INTEGER NOT NULL DEFAULT 0")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_updated_ts ON datasets(updated_ts DESC)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_assets (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                origin_name TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'zip',
                source_job_id TEXT NOT NULL DEFAULT '',
                source_asset_id TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                FOREIGN KEY(dataset_id) REFERENCES datasets(id)
            )
            """
        )

        asset_columns = _existing_columns(conn, "dataset_assets")
        if "origin_name" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN origin_name TEXT NOT NULL DEFAULT ''")
        if "source_type" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN source_type TEXT NOT NULL DEFAULT 'zip'")
        if "source_job_id" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN source_job_id TEXT NOT NULL DEFAULT ''")
        if "source_asset_id" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN source_asset_id TEXT NOT NULL DEFAULT ''")
        if "file_path" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN file_path TEXT NOT NULL DEFAULT ''")
        if "width" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN width INTEGER NOT NULL DEFAULT 0")
        if "height" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN height INTEGER NOT NULL DEFAULT 0")
        if "size_bytes" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
        if "created_ts" not in asset_columns:
            conn.execute("ALTER TABLE dataset_assets ADD COLUMN created_ts INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dataset_assets_dataset_created_ts ON dataset_assets(dataset_id, created_ts DESC)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS train_jobs (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                base_model TEXT NOT NULL,
                base_model_path TEXT NOT NULL,
                preset_key TEXT NOT NULL,
                epochs INTEGER NOT NULL DEFAULT 0,
                imgsz INTEGER NOT NULL DEFAULT 0,
                batch_size INTEGER NOT NULL DEFAULT 0,
                confirmed_only INTEGER NOT NULL DEFAULT 0,
                run_dir TEXT NOT NULL,
                log_path TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                artifact_dir TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                start_ts INTEGER,
                end_ts INTEGER,
                owner_key TEXT,
                owner_ip TEXT
            )
            """
        )

        train_columns = _existing_columns(conn, "train_jobs")
        if "dataset_name" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN dataset_name TEXT NOT NULL DEFAULT ''")
        if "status" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'")
        if "message" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN message TEXT NOT NULL DEFAULT ''")
        if "base_model" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN base_model TEXT NOT NULL DEFAULT ''")
        if "base_model_path" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN base_model_path TEXT NOT NULL DEFAULT ''")
        if "preset_key" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN preset_key TEXT NOT NULL DEFAULT 'quick'")
        if "epochs" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN epochs INTEGER NOT NULL DEFAULT 0")
        if "imgsz" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN imgsz INTEGER NOT NULL DEFAULT 0")
        if "batch_size" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN batch_size INTEGER NOT NULL DEFAULT 0")
        if "confirmed_only" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN confirmed_only INTEGER NOT NULL DEFAULT 0")
        if "run_dir" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN run_dir TEXT NOT NULL DEFAULT ''")
        if "log_path" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN log_path TEXT NOT NULL DEFAULT ''")
        if "manifest_path" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN manifest_path TEXT NOT NULL DEFAULT ''")
        if "artifact_dir" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN artifact_dir TEXT NOT NULL DEFAULT ''")
        if "created_ts" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN created_ts INTEGER NOT NULL DEFAULT 0")
        if "start_ts" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN start_ts INTEGER")
        if "end_ts" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN end_ts INTEGER")
        if "owner_key" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN owner_key TEXT")
        if "owner_ip" not in train_columns:
            conn.execute("ALTER TABLE train_jobs ADD COLUMN owner_ip TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_train_jobs_owner_key_created_ts ON train_jobs(owner_key, created_ts DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_train_jobs_owner_ip_created_ts ON train_jobs(owner_ip, created_ts DESC)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_train_jobs_status ON train_jobs(status)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_annotate_jobs (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                model_key TEXT NOT NULL,
                conf_thresh REAL NOT NULL DEFAULT 0.25,
                imgsz INTEGER NOT NULL DEFAULT 640,
                prompt_classes TEXT NOT NULL DEFAULT '',
                class_mapping TEXT NOT NULL DEFAULT '',
                overwrite INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                skipped_existing INTEGER NOT NULL DEFAULT 0,
                no_detection INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                start_ts INTEGER,
                end_ts INTEGER,
                owner_key TEXT,
                owner_ip TEXT
            )
            """
        )

        auto_columns = _existing_columns(conn, "auto_annotate_jobs")
        if "dataset_name" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN dataset_name TEXT NOT NULL DEFAULT ''")
        if "status" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'")
        if "message" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN message TEXT NOT NULL DEFAULT ''")
        if "model_key" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN model_key TEXT NOT NULL DEFAULT ''")
        if "conf_thresh" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN conf_thresh REAL NOT NULL DEFAULT 0.25")
        if "imgsz" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN imgsz INTEGER NOT NULL DEFAULT 640")
        if "prompt_classes" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN prompt_classes TEXT NOT NULL DEFAULT ''")
        if "class_mapping" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN class_mapping TEXT NOT NULL DEFAULT ''")
        if "overwrite" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN overwrite INTEGER NOT NULL DEFAULT 0")
        if "total" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN total INTEGER NOT NULL DEFAULT 0")
        if "processed" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN processed INTEGER NOT NULL DEFAULT 0")
        if "updated" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN updated INTEGER NOT NULL DEFAULT 0")
        if "skipped_existing" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN skipped_existing INTEGER NOT NULL DEFAULT 0")
        if "no_detection" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN no_detection INTEGER NOT NULL DEFAULT 0")
        if "created_ts" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN created_ts INTEGER NOT NULL DEFAULT 0")
        if "start_ts" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN start_ts INTEGER")
        if "end_ts" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN end_ts INTEGER")
        if "owner_key" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN owner_key TEXT")
        if "owner_ip" not in auto_columns:
            conn.execute("ALTER TABLE auto_annotate_jobs ADD COLUMN owner_ip TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auto_annotate_jobs_owner_key_created_ts ON auto_annotate_jobs(owner_key, created_ts DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auto_annotate_jobs_owner_ip_created_ts ON auto_annotate_jobs(owner_ip, created_ts DESC)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auto_annotate_jobs_status ON auto_annotate_jobs(status)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS face_library_jobs (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                message TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                processed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL DEFAULT 0,
                start_ts INTEGER,
                end_ts INTEGER,
                error TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                library_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )

        face_library_columns = _existing_columns(conn, "face_library_jobs")
        if "action" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN action TEXT NOT NULL DEFAULT 'rebuild'")
        if "status" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'")
        if "message" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN message TEXT NOT NULL DEFAULT ''")
        if "stage" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN stage TEXT NOT NULL DEFAULT ''")
        if "processed" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN processed INTEGER NOT NULL DEFAULT 0")
        if "total" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN total INTEGER NOT NULL DEFAULT 0")
        if "created_ts" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN created_ts INTEGER NOT NULL DEFAULT 0")
        if "start_ts" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN start_ts INTEGER")
        if "end_ts" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN end_ts INTEGER")
        if "error" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN error TEXT NOT NULL DEFAULT ''")
        if "result_json" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'")
        if "library_json" not in face_library_columns:
            conn.execute("ALTER TABLE face_library_jobs ADD COLUMN library_json TEXT NOT NULL DEFAULT '{}'")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_face_library_jobs_status ON face_library_jobs(status)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_face_library_jobs_created_ts ON face_library_jobs(created_ts DESC)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_auth_sessions (
                owner_key TEXT PRIMARY KEY,
                owner_ip TEXT,
                username TEXT NOT NULL DEFAULT '',
                access_token TEXT NOT NULL DEFAULT '',
                refresh_token TEXT NOT NULL DEFAULT '',
                token_type TEXT NOT NULL DEFAULT 'Bearer',
                expires_in INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER,
                authenticated_ts INTEGER,
                updated_ts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                is_mock INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatch_auth_owner_ip_updated_ts ON dispatch_auth_sessions(owner_ip, updated_ts DESC)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_queue (
                id TEXT PRIMARY KEY,
                owner_key TEXT,
                owner_ip TEXT,
                source_job_id TEXT NOT NULL DEFAULT '',
                source_asset_id TEXT NOT NULL DEFAULT '',
                source_job_type TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                asset_name TEXT NOT NULL DEFAULT '',
                face_index INTEGER NOT NULL DEFAULT 0,
                person_name TEXT NOT NULL DEFAULT '',
                person_id_no TEXT NOT NULL DEFAULT '',
                person_phone TEXT NOT NULL DEFAULT '',
                similarity_score REAL NOT NULL DEFAULT 0,
                illegal_type TEXT NOT NULL DEFAULT '',
                sssj_dm TEXT NOT NULL DEFAULT '',
                sssj_mc TEXT NOT NULL DEFAULT '',
                ssfj_dm TEXT NOT NULL DEFAULT '',
                ssfj_mc TEXT NOT NULL DEFAULT '',
                zbpcs_dm TEXT NOT NULL DEFAULT '',
                zbpcs_mc TEXT NOT NULL DEFAULT '',
                dzmc TEXT NOT NULL DEFAULT '',
                rwdyid TEXT NOT NULL DEFAULT '',
                sjcsly TEXT NOT NULL DEFAULT '',
                dispatch_status TEXT NOT NULL DEFAULT 'pending',
                sms_status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT NOT NULL DEFAULT '',
                draft_payload_json TEXT NOT NULL DEFAULT '',
                identity_payload_json TEXT NOT NULL DEFAULT '',
                dispatch_response_json TEXT NOT NULL DEFAULT '',
                sms_preview TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL DEFAULT 0,
                updated_ts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatch_queue_owner_created_ts ON dispatch_queue(owner_key, created_ts DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatch_queue_owner_ip_created_ts ON dispatch_queue(owner_ip, created_ts DESC)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_queue_owner_source_face_person ON dispatch_queue(owner_key, source_job_id, source_asset_id, face_index, person_id_no)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatch_queue_status ON dispatch_queue(dispatch_status)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_records (
                id TEXT PRIMARY KEY,
                queue_id TEXT NOT NULL,
                owner_key TEXT,
                owner_ip TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                request_payload_json TEXT NOT NULL DEFAULT '',
                response_payload_json TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatch_records_owner_created_ts ON dispatch_records(owner_key, created_ts DESC)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_sms_records (
                id TEXT PRIMARY KEY,
                queue_id TEXT NOT NULL,
                owner_key TEXT,
                owner_ip TEXT,
                mobile TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                request_payload_json TEXT NOT NULL DEFAULT '',
                response_payload_json TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatch_sms_records_owner_created_ts ON dispatch_sms_records(owner_key, created_ts DESC)"
        )

        from shared.task_queue import init_task_queue_table
        init_task_queue_table(conn)

        conn.commit()


def save_job(job: dict[str, Any]) -> None:
    zip_paths = _extract_zip_paths(job)
    payload = {
        "job_type": job.get("job_type", "database"),
        "id": job.get("id", ""),
        "source_name": job.get("source_name", ""),
        "source_type": job.get("source_type", ""),
        "source_path": job.get("source_path", ""),
        "temp_dir": job.get("temp_dir", ""),
        "frame_interval": job.get("frame_interval"),
        "status": job.get("status", ""),
        "message": job.get("message", ""),
        "total": int(job.get("total") or 0),
        "processed": int(job.get("processed") or 0),
        "kept": int(job.get("kept") or 0),
        "notfound": int(job.get("notfound") or 0),
        "failed": int(job.get("failed") or 0),
        "downloaded": int(job.get("downloaded") or 0),
        "start_ts": job.get("start_ts"),
        "end_ts": job.get("end_ts"),
        "owner_key": job.get("owner_key", ""),
        "owner_ip": job.get("owner_ip", ""),
        "conf_thresh": job.get("conf_thresh"),
        "batch_size": job.get("batch_size"),
        "imgsz": job.get("imgsz"),
        "classes_raw": job.get("classes_raw", ""),
        "model_key": job.get("model_key", MODEL_DEFAULT),
        "zip_paths_json": json.dumps(zip_paths, ensure_ascii=False),
        "result_dir": job.get("result_dir", ""),
        "result_manifest_path": job.get("result_manifest_path", ""),
        "identity_result_path": job.get("identity_result_path", ""),
        "identity_summary_json": json.dumps(job.get("identity_summary") or {}, ensure_ascii=False),
        "summary_text": job.get("summary_text", ""),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                job_type, id, source_name, source_type, source_path, temp_dir, frame_interval,
                status, message, total, processed, kept, notfound, failed,
                downloaded, start_ts, end_ts, owner_key, owner_ip, conf_thresh, batch_size,
                imgsz, classes_raw, model_key, zip_paths_json, result_dir, result_manifest_path,
                identity_result_path, identity_summary_json, summary_text
            )
            VALUES (
                :job_type, :id, :source_name, :source_type, :source_path, :temp_dir, :frame_interval,
                :status, :message, :total, :processed, :kept, :notfound, :failed,
                :downloaded, :start_ts, :end_ts, :owner_key, :owner_ip, :conf_thresh, :batch_size,
                :imgsz, :classes_raw, :model_key, :zip_paths_json, :result_dir, :result_manifest_path,
                :identity_result_path, :identity_summary_json, :summary_text
            )
            ON CONFLICT(id) DO UPDATE SET
                job_type = excluded.job_type,
                source_name = excluded.source_name,
                source_type = excluded.source_type,
                source_path = excluded.source_path,
                temp_dir = excluded.temp_dir,
                frame_interval = excluded.frame_interval,
                status = excluded.status,
                message = excluded.message,
                total = excluded.total,
                processed = excluded.processed,
                kept = excluded.kept,
                notfound = excluded.notfound,
                failed = excluded.failed,
                downloaded = excluded.downloaded,
                start_ts = excluded.start_ts,
                end_ts = excluded.end_ts,
                owner_key = excluded.owner_key,
                owner_ip = excluded.owner_ip,
                conf_thresh = excluded.conf_thresh,
                batch_size = excluded.batch_size,
                imgsz = excluded.imgsz,
                classes_raw = excluded.classes_raw,
                model_key = excluded.model_key,
                zip_paths_json = excluded.zip_paths_json,
                result_dir = excluded.result_dir,
                result_manifest_path = excluded.result_manifest_path,
                identity_result_path = excluded.identity_result_path,
                identity_summary_json = excluded.identity_summary_json,
                summary_text = excluded.summary_text
            """,
            payload,
        )
        conn.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def list_active_jobs(
    owner_key: str,
    owner_ip: str,
    limit: int = 20,
    job_type: str | None = None,
) -> list[dict[str, Any]]:
    if not owner_key and not owner_ip:
        return []

    safe_limit = max(1, min(int(limit or 20), 200))
    query = """
        SELECT *
        FROM jobs
        WHERE status IN ('queued', 'running')
          AND (
                owner_key = ?
             OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
          )
    """
    params: list[Any] = [owner_key, owner_ip]
    if job_type:
        query += " AND job_type = ?"
        params.append(job_type)
    query += """
        ORDER BY start_ts DESC, id DESC
        LIMIT ?
    """
    params.append(safe_limit)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_job(row) for row in rows if row is not None]


def save_dataset(dataset: dict[str, Any]) -> None:
    payload = {
        "id": dataset.get("id", ""),
        "name": dataset.get("name", ""),
        "notes": dataset.get("notes", ""),
        "class_names_json": json.dumps(dataset.get("class_names") or [], ensure_ascii=False),
        "status": dataset.get("status", "draft"),
        "image_count": int(dataset.get("image_count") or 0),
        "labeled_count": int(dataset.get("labeled_count") or 0),
        "reviewed_count": int(dataset.get("reviewed_count") or 0),
        "version_count": int(dataset.get("version_count") or 0),
        "root_dir": dataset.get("root_dir", ""),
        "created_ts": int(dataset.get("created_ts") or 0),
        "updated_ts": int(dataset.get("updated_ts") or 0),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO datasets (
                id, name, notes, class_names_json, status, image_count, labeled_count,
                reviewed_count, version_count, root_dir, created_ts, updated_ts
            )
            VALUES (
                :id, :name, :notes, :class_names_json, :status, :image_count, :labeled_count,
                :reviewed_count, :version_count, :root_dir, :created_ts, :updated_ts
            )
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                notes = excluded.notes,
                class_names_json = excluded.class_names_json,
                status = excluded.status,
                image_count = excluded.image_count,
                labeled_count = excluded.labeled_count,
                reviewed_count = excluded.reviewed_count,
                version_count = excluded.version_count,
                root_dir = excluded.root_dir,
                created_ts = excluded.created_ts,
                updated_ts = excluded.updated_ts
            """,
            payload,
        )
        conn.commit()


def get_dataset(dataset_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    return _row_to_dataset(row)


def save_dataset_asset(asset: dict[str, Any]) -> None:
    payload = {
        "id": asset.get("id", ""),
        "dataset_id": asset.get("dataset_id", ""),
        "filename": asset.get("filename", ""),
        "origin_name": asset.get("origin_name", ""),
        "source_type": asset.get("source_type", "zip"),
        "source_job_id": asset.get("source_job_id", ""),
        "source_asset_id": asset.get("source_asset_id", ""),
        "file_path": asset.get("file_path", ""),
        "width": int(asset.get("width") or 0),
        "height": int(asset.get("height") or 0),
        "size_bytes": int(asset.get("size_bytes") or 0),
        "created_ts": int(asset.get("created_ts") or 0),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO dataset_assets (
                id, dataset_id, filename, origin_name, source_type, source_job_id, source_asset_id, file_path,
                width, height, size_bytes, created_ts
            )
            VALUES (
                :id, :dataset_id, :filename, :origin_name, :source_type, :source_job_id, :source_asset_id, :file_path,
                :width, :height, :size_bytes, :created_ts
            )
            ON CONFLICT(id) DO UPDATE SET
                dataset_id = excluded.dataset_id,
                filename = excluded.filename,
                origin_name = excluded.origin_name,
                source_type = excluded.source_type,
                source_job_id = excluded.source_job_id,
                source_asset_id = excluded.source_asset_id,
                file_path = excluded.file_path,
                width = excluded.width,
                height = excluded.height,
                size_bytes = excluded.size_bytes,
                created_ts = excluded.created_ts
            """,
            payload,
        )
        conn.commit()


def count_dataset_assets(dataset_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM dataset_assets WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()
    return int(row["total"] if row is not None else 0)


def list_dataset_assets(dataset_id: str, limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 500))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM dataset_assets
            WHERE dataset_id = ?
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (dataset_id, safe_limit),
        ).fetchall()
    return [_row_to_dataset_asset(row) for row in rows if row is not None]


def get_dataset_asset(dataset_id: str, asset_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM dataset_assets
            WHERE dataset_id = ? AND id = ?
            LIMIT 1
            """,
            (dataset_id, asset_id),
        ).fetchone()
    return _row_to_dataset_asset(row)


def list_datasets(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 500))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM datasets
            ORDER BY updated_ts DESC, created_ts DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [_row_to_dataset(row) for row in rows if row is not None]


def save_train_job(job: dict[str, Any]) -> None:
    payload = {
        "id": job.get("id", ""),
        "dataset_id": job.get("dataset_id", ""),
        "dataset_name": job.get("dataset_name", ""),
        "status": job.get("status", "queued"),
        "message": job.get("message", ""),
        "base_model": job.get("base_model", ""),
        "base_model_path": job.get("base_model_path", ""),
        "preset_key": job.get("preset_key", "quick"),
        "epochs": int(job.get("epochs") or 0),
        "imgsz": int(job.get("imgsz") or 0),
        "batch_size": int(job.get("batch_size") or 0),
        "confirmed_only": 1 if job.get("confirmed_only") else 0,
        "run_dir": job.get("run_dir", ""),
        "log_path": job.get("log_path", ""),
        "manifest_path": job.get("manifest_path", ""),
        "artifact_dir": job.get("artifact_dir", ""),
        "created_ts": int(job.get("created_ts") or 0),
        "start_ts": job.get("start_ts"),
        "end_ts": job.get("end_ts"),
        "owner_key": job.get("owner_key", ""),
        "owner_ip": job.get("owner_ip", ""),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO train_jobs (
                id, dataset_id, dataset_name, status, message, base_model, base_model_path, preset_key,
                epochs, imgsz, batch_size, confirmed_only, run_dir, log_path, manifest_path, artifact_dir,
                created_ts, start_ts, end_ts, owner_key, owner_ip
            )
            VALUES (
                :id, :dataset_id, :dataset_name, :status, :message, :base_model, :base_model_path, :preset_key,
                :epochs, :imgsz, :batch_size, :confirmed_only, :run_dir, :log_path, :manifest_path, :artifact_dir,
                :created_ts, :start_ts, :end_ts, :owner_key, :owner_ip
            )
            ON CONFLICT(id) DO UPDATE SET
                dataset_id = excluded.dataset_id,
                dataset_name = excluded.dataset_name,
                status = excluded.status,
                message = excluded.message,
                base_model = excluded.base_model,
                base_model_path = excluded.base_model_path,
                preset_key = excluded.preset_key,
                epochs = excluded.epochs,
                imgsz = excluded.imgsz,
                batch_size = excluded.batch_size,
                confirmed_only = excluded.confirmed_only,
                run_dir = excluded.run_dir,
                log_path = excluded.log_path,
                manifest_path = excluded.manifest_path,
                artifact_dir = excluded.artifact_dir,
                created_ts = excluded.created_ts,
                start_ts = excluded.start_ts,
                end_ts = excluded.end_ts,
                owner_key = excluded.owner_key,
                owner_ip = excluded.owner_ip
            """,
            payload,
        )
        conn.commit()


def get_train_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM train_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_train_job(row)


def list_train_jobs(owner_key: str, owner_ip: str, limit: int = 20) -> list[dict[str, Any]]:
    if not owner_key and not owner_ip:
        return []

    safe_limit = max(1, min(int(limit or 20), 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM train_jobs
            WHERE owner_key = ?
               OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (owner_key, owner_ip, safe_limit),
        ).fetchall()
    return [_row_to_train_job(row) for row in rows if row is not None]


def save_auto_annotate_job(job: dict[str, Any]) -> None:
    payload = {
        "id": job.get("id", ""),
        "dataset_id": job.get("dataset_id", ""),
        "dataset_name": job.get("dataset_name", ""),
        "status": job.get("status", "queued"),
        "message": job.get("message", ""),
        "model_key": job.get("model_key", ""),
        "conf_thresh": float(job.get("conf_thresh") or 0.25),
        "imgsz": int(job.get("imgsz") or 640),
        "prompt_classes": job.get("prompt_classes", ""),
        "class_mapping": job.get("class_mapping", ""),
        "overwrite": 1 if job.get("overwrite") else 0,
        "total": int(job.get("total") or 0),
        "processed": int(job.get("processed") or 0),
        "updated": int(job.get("updated") or 0),
        "skipped_existing": int(job.get("skipped_existing") or 0),
        "no_detection": int(job.get("no_detection") or 0),
        "created_ts": int(job.get("created_ts") or 0),
        "start_ts": job.get("start_ts"),
        "end_ts": job.get("end_ts"),
        "owner_key": job.get("owner_key", ""),
        "owner_ip": job.get("owner_ip", ""),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auto_annotate_jobs (
                id, dataset_id, dataset_name, status, message, model_key, conf_thresh, imgsz,
                prompt_classes, class_mapping, overwrite, total, processed, updated,
                skipped_existing, no_detection, created_ts, start_ts, end_ts, owner_key, owner_ip
            )
            VALUES (
                :id, :dataset_id, :dataset_name, :status, :message, :model_key, :conf_thresh, :imgsz,
                :prompt_classes, :class_mapping, :overwrite, :total, :processed, :updated,
                :skipped_existing, :no_detection, :created_ts, :start_ts, :end_ts, :owner_key, :owner_ip
            )
            ON CONFLICT(id) DO UPDATE SET
                dataset_id = excluded.dataset_id,
                dataset_name = excluded.dataset_name,
                status = excluded.status,
                message = excluded.message,
                model_key = excluded.model_key,
                conf_thresh = excluded.conf_thresh,
                imgsz = excluded.imgsz,
                prompt_classes = excluded.prompt_classes,
                class_mapping = excluded.class_mapping,
                overwrite = excluded.overwrite,
                total = excluded.total,
                processed = excluded.processed,
                updated = excluded.updated,
                skipped_existing = excluded.skipped_existing,
                no_detection = excluded.no_detection,
                created_ts = excluded.created_ts,
                start_ts = excluded.start_ts,
                end_ts = excluded.end_ts,
                owner_key = excluded.owner_key,
                owner_ip = excluded.owner_ip
            """,
            payload,
        )
        conn.commit()


def get_auto_annotate_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM auto_annotate_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_auto_annotate_job(row)


def list_auto_annotate_jobs(owner_key: str, owner_ip: str, limit: int = 20) -> list[dict[str, Any]]:
    if not owner_key and not owner_ip:
        return []

    safe_limit = max(1, min(int(limit or 20), 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM auto_annotate_jobs
            WHERE owner_key = ?
               OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (owner_key, owner_ip, safe_limit),
        ).fetchall()
    return [_row_to_auto_annotate_job(row) for row in rows if row is not None]


def save_face_library_job(job: dict[str, Any]) -> None:
    payload = {
        "id": job.get("id", ""),
        "action": job.get("action", "rebuild"),
        "status": job.get("status", "queued"),
        "message": job.get("message", ""),
        "stage": job.get("stage", ""),
        "processed": int(job.get("processed") or 0),
        "total": int(job.get("total") or 0),
        "created_ts": int(job.get("created_ts") or job.get("start_ts") or 0),
        "start_ts": job.get("start_ts"),
        "end_ts": job.get("end_ts"),
        "error": job.get("error", ""),
        "result_json": json.dumps(job.get("result") or {}, ensure_ascii=False),
        "library_json": json.dumps(job.get("library") or {}, ensure_ascii=False),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO face_library_jobs (
                id, action, status, message, stage, processed, total, created_ts,
                start_ts, end_ts, error, result_json, library_json
            )
            VALUES (
                :id, :action, :status, :message, :stage, :processed, :total, :created_ts,
                :start_ts, :end_ts, :error, :result_json, :library_json
            )
            ON CONFLICT(id) DO UPDATE SET
                action = excluded.action,
                status = excluded.status,
                message = excluded.message,
                stage = excluded.stage,
                processed = excluded.processed,
                total = excluded.total,
                created_ts = excluded.created_ts,
                start_ts = excluded.start_ts,
                end_ts = excluded.end_ts,
                error = excluded.error,
                result_json = excluded.result_json,
                library_json = excluded.library_json
            """,
            payload,
        )
        conn.commit()


def get_face_library_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM face_library_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_face_library_job(row)


def get_active_face_library_job() -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM face_library_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_ts ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_face_library_job(row)


def list_face_library_jobs(limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM face_library_jobs
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [_row_to_face_library_job(row) for row in rows if row is not None]


def list_jobs(owner_key: str, owner_ip: str, limit: int = 50) -> list[dict[str, Any]]:
    if not owner_key and not owner_ip:
        return []

    safe_limit = max(1, min(int(limit or 50), 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE owner_key = ?
               OR (COALESCE(owner_key, '') = '' AND owner_ip = ?)
            ORDER BY start_ts DESC
            LIMIT ?
            """,
            (owner_key, owner_ip, safe_limit),
        ).fetchall()
    return [_row_to_job(row) for row in rows if row is not None]


def list_all_jobs(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 50), 500))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY start_ts DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [_row_to_job(row) for row in rows if row is not None]


def cleanup_old_jobs(days: int = 7) -> int:
    cutoff = int(time.time()) - max(days, 0) * 24 * 60 * 60
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, zip_paths_json, result_dir, source_path, temp_dir
            FROM jobs
            WHERE end_ts IS NOT NULL AND end_ts < ?
            """,
            (cutoff,),
        ).fetchall()

        delete_ids = []
        for row in rows:
            delete_ids.append(row["id"])
            try:
                zip_paths = json.loads(row["zip_paths_json"] or "[]")
            except Exception:
                zip_paths = []
            for path in zip_paths:
                if path and os.path.isfile(path):
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        pass
                    except Exception as exc:
                        logger.warning("failed to remove zip file %s: %s", path, exc)
            result_dir = row["result_dir"]
            if result_dir and os.path.isdir(result_dir):
                try:
                    shutil.rmtree(result_dir, ignore_errors=False)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("failed to remove result dir %s: %s", result_dir, exc)
            temp_dir = row["temp_dir"]
            if temp_dir and os.path.isdir(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=False)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("failed to remove temp dir %s: %s", temp_dir, exc)
            source_path = row["source_path"]
            if source_path and os.path.isfile(source_path):
                try:
                    os.remove(source_path)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("failed to remove source file %s: %s", source_path, exc)

        if delete_ids:
            conn.executemany("DELETE FROM jobs WHERE id = ?", [(job_id,) for job_id in delete_ids])
            conn.commit()

    return len(delete_ids)


def mark_running_jobs_interrupted(job_types: list[str] | None = None) -> int:
    now = int(time.time())
    safe_job_types = [str(item).strip() for item in (job_types or []) if str(item).strip()]
    where = "status = 'running'"
    params: list[Any] = [now]
    if safe_job_types:
        placeholders = ", ".join("?" for _ in safe_job_types)
        where += f" AND job_type IN ({placeholders})"
        params.extend(safe_job_types)

    with _connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE jobs
            SET status = 'interrupted',
                end_ts = COALESCE(end_ts, ?),
                message = CASE
                    WHEN message IS NULL OR message = '' THEN 'service restarted before job completed'
                    ELSE message
                END
            WHERE {where}
            """,
            params,
        )
        conn.commit()
        return cursor.rowcount
