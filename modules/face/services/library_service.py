from __future__ import annotations

import base64
import json
import os
import pickle
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

import cv2
import numpy as np

from shared.config.config import (
    FACE_DATA_DIR,
    FACE_MATCH_TOP_K,
    FACE_MODEL_DET,
    FACE_MODEL_REC,
    FACE_SIMILARITY_THR,
    POSTGRES_ENABLED,
    POSTGRES_FACE_QUERY_PATH,
    logger,
)
from shared.db.postgres import get_postgres_connection, postgres_configured
from modules.face.services.identity_service import (
    extract_best_face_embedding,
    extract_probe_embeddings,
    face_models_ready,
    get_face_models,
    load_image,
)
from modules.face.services.vector_store import VectorIndex


PHOTO_DIR = os.path.join(FACE_DATA_DIR, "photos")
FEATURE_DIR = os.path.join(FACE_DATA_DIR, "features")
DB_CACHE_FILE = os.path.join(FACE_DATA_DIR, "person_db.pkl")
META_FILE = os.path.join(FACE_DATA_DIR, "meta.json")

DEFAULT_QUERY_SQL = """
SELECT
    bzr."zjlx",
    bzr."zjhm",
    bzr."xm",
    tdrz."xp"
FROM "sample_schema"."face_persons" bzr
LEFT JOIN "sample_schema"."face_photos" tdrz
    ON bzr."zjhm" = tdrz."gmsfhm"
WHERE bzr."sflg" = 1
  AND bzr."deleteflag" = 0
"""


@dataclass
class PersonRecord:
    zjlx: str
    zjhm: str
    xm: str
    photo_path: Optional[str] = None
    embedding: Optional[np.ndarray] = None


_CACHE_LOCK = threading.Lock()
_PERSON_CACHE: list[PersonRecord] | None = None
_MATRIX_CACHE: np.ndarray | None = None
_VECTOR_INDEX: VectorIndex | None = None
_CACHE_MTIME: float | None = None


def _report(progress_cb, **payload) -> None:
    if callable(progress_cb):
        try:
            progress_cb(payload)
        except Exception:
            pass


def _ensure_dirs() -> None:
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(FEATURE_DIR, exist_ok=True)


def _cleanup_path(path: str) -> None:
    if not path:
        return
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _make_stage_root(prefix: str) -> str:
    stage_root = os.path.join(FACE_DATA_DIR, f"_{prefix}_{uuid4().hex}")
    os.makedirs(stage_root, exist_ok=True)
    return stage_root


def _save_person_db_to_path(persons: list["PersonRecord"], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(persons, fh)


def _save_meta_to_path(meta: dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def _commit_face_library_stage(
    *,
    stage_photo_dir: str | None = None,
    stage_feature_dir: str | None = None,
    stage_db_path: str | None = None,
    stage_meta_path: str | None = None,
) -> None:
    swaps: list[tuple[str, str | None]] = []
    success = False

    def _swap_path(src: str | None, dst: str) -> None:
        if not src or not os.path.exists(src):
            return
        backup = None
        if os.path.exists(dst):
            backup = dst + f".bak_{uuid4().hex}"
            shutil.move(dst, backup)
        shutil.move(src, dst)
        swaps.append((dst, backup))

    try:
        _swap_path(stage_photo_dir, PHOTO_DIR)
        _swap_path(stage_feature_dir, FEATURE_DIR)
        _swap_path(stage_db_path, DB_CACHE_FILE)
        _swap_path(stage_meta_path, META_FILE)
        _invalidate_cache()
        success = True
    finally:
        if success:
            for _dst, backup in swaps:
                if backup:
                    _cleanup_path(backup)
        else:
            for dst, backup in reversed(swaps):
                _cleanup_path(dst)
                if backup and os.path.exists(backup):
                    shutil.move(backup, dst)
            _invalidate_cache()


def _load_meta() -> dict[str, Any]:
    if not os.path.isfile(META_FILE):
        return {}
    try:
        with open(META_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_meta(meta: dict[str, Any]) -> None:
    _ensure_dirs()
    with open(META_FILE, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def _invalidate_cache() -> None:
    global _PERSON_CACHE, _MATRIX_CACHE, _VECTOR_INDEX, _CACHE_MTIME
    with _CACHE_LOCK:
        _PERSON_CACHE = None
        _MATRIX_CACHE = None
        _VECTOR_INDEX = None
        _CACHE_MTIME = None


def _load_query_sql() -> str:
    if POSTGRES_FACE_QUERY_PATH and os.path.isfile(POSTGRES_FACE_QUERY_PATH):
        try:
            with open(POSTGRES_FACE_QUERY_PATH, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                return text
            logger.warning("PostgreSQL face query file is empty, falling back to built-in SQL: %s", POSTGRES_FACE_QUERY_PATH)
        except Exception as exc:
            logger.warning("failed to read PostgreSQL face query file %s, falling back to built-in SQL: %s", POSTGRES_FACE_QUERY_PATH, exc)
    elif POSTGRES_FACE_QUERY_PATH:
        logger.warning("PostgreSQL face query file not found, falling back to built-in SQL: %s", POSTGRES_FACE_QUERY_PATH)
    return DEFAULT_QUERY_SQL.strip()


def _decode_photo(raw: Any) -> Optional[np.ndarray]:
    if raw is None:
        return None
    if isinstance(raw, memoryview):
        raw = bytes(raw)
    if isinstance(raw, str):
        try:
            raw = base64.b64decode(raw)
        except Exception:
            return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _save_person_db(persons: list[PersonRecord]) -> None:
    _ensure_dirs()
    with open(DB_CACHE_FILE, "wb") as fh:
        pickle.dump(persons, fh)
    _invalidate_cache()


class _CompatUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if name == "PersonRecord":
            return PersonRecord
        return super().find_class(module, name)


def _load_person_db() -> list[PersonRecord]:
    with open(DB_CACHE_FILE, "rb") as fh:
        return _CompatUnpickler(fh).load()


def _person_payload(person: PersonRecord, score: float | None = None) -> dict[str, Any]:
    payload = {
        "name": person.xm,
        "id_number": person.zjhm,
        "id_type": person.zjlx,
        "photo_path": person.photo_path,
    }
    if score is not None:
        payload["score"] = round(float(score), 4)
    return payload


def _load_cached_matrix() -> tuple[list[PersonRecord], np.ndarray]:
    if not os.path.isfile(DB_CACHE_FILE):
        return [], np.empty((0, 512), dtype=np.float32)

    mtime = os.path.getmtime(DB_CACHE_FILE)
    global _PERSON_CACHE, _MATRIX_CACHE, _VECTOR_INDEX, _CACHE_MTIME
    with _CACHE_LOCK:
        if _PERSON_CACHE is not None and _MATRIX_CACHE is not None and _CACHE_MTIME == mtime:
            return _PERSON_CACHE, _MATRIX_CACHE

        persons = _load_person_db()
        valid = [person for person in persons if getattr(person, "embedding", None) is not None]
        matrix = np.stack([person.embedding for person in valid]).astype(np.float32) if valid else np.empty((0, 512), dtype=np.float32)
        _PERSON_CACHE = valid
        _MATRIX_CACHE = matrix
        # Build vector index for fast search
        vi = VectorIndex(dim=512)
        vi.build(matrix)
        _VECTOR_INDEX = vi
        _CACHE_MTIME = mtime
        return valid, matrix


def get_face_library_status() -> dict[str, Any]:
    _ensure_dirs()
    meta = _load_meta()
    photo_count = len([name for name in os.listdir(PHOTO_DIR)]) if os.path.isdir(PHOTO_DIR) else 0
    feature_count = len([name for name in os.listdir(FEATURE_DIR) if name.lower().endswith(".npy")]) if os.path.isdir(FEATURE_DIR) else 0
    cache_exists = os.path.isfile(DB_CACHE_FILE)
    valid_persons = 0
    if cache_exists:
        try:
            persons = _load_person_db()
            valid_persons = sum(1 for person in persons if getattr(person, "embedding", None) is not None)
        except Exception:
            valid_persons = 0

    models_ready = face_models_ready()
    return {
        "ready": bool(models_ready and cache_exists and valid_persons > 0),
        "models_ready": models_ready,
        "det_model_path": FACE_MODEL_DET,
        "rec_model_path": FACE_MODEL_REC,
        "cache_exists": cache_exists,
        "person_db_path": DB_CACHE_FILE,
        "photo_dir": PHOTO_DIR,
        "feature_dir": FEATURE_DIR,
        "photo_count": photo_count,
        "feature_count": feature_count,
        "valid_person_count": valid_persons,
        "last_sync_ts": meta.get("last_sync_ts"),
        "last_rebuild_ts": meta.get("last_rebuild_ts"),
        "last_sync_rows": meta.get("last_sync_rows", 0),
        "sql_enabled": POSTGRES_ENABLED,
        "sql_configured": postgres_configured(),
    }


def list_persons(page: int = 1, page_size: int = 12, keyword: str = "") -> dict[str, Any]:
    """Return a paginated list of persons from the cached person_db."""
    if not os.path.isfile(DB_CACHE_FILE):
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0}
    try:
        persons = _load_person_db()
    except Exception:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0}

    keyword = (keyword or "").strip().lower()
    if keyword:
        persons = [p for p in persons if keyword in (p.xm or "").lower() or keyword in (p.zjhm or "").lower()]

    total = len(persons)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    start = (page - 1) * page_size
    sliced = persons[start : start + page_size]

    items = []
    for p in sliced:
        has_embedding = getattr(p, "embedding", None) is not None
        has_photo = bool(p.photo_path and os.path.isfile(p.photo_path))
        items.append({
            "id": p.zjhm,
            "name": p.xm,
            "id_number": p.zjhm,
            "id_type": p.zjlx,
            "has_photo": has_photo,
            "has_feature": has_embedding,
            "status": "valid" if has_embedding else "no_feature",
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


def get_face_library_photo_path(person_id: str) -> str | None:
    person_id = os.path.basename((person_id or "").strip())
    if not person_id:
        return None
    for ext in (".jpg", ".jpeg", ".png"):
        candidate = os.path.join(PHOTO_DIR, person_id + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def rebuild_face_library(progress_cb=None) -> dict[str, Any]:
    _ensure_dirs()
    _report(progress_cb, stage="prepare", message="Preparing local face feature rebuild", processed=0, total=0)

    if os.path.isfile(DB_CACHE_FILE):
        persons = _load_person_db()
    else:
        persons = []
        for filename in sorted(os.listdir(PHOTO_DIR)):
            full_path = os.path.join(PHOTO_DIR, filename)
            if not os.path.isfile(full_path):
                continue
            person_id, _ext = os.path.splitext(filename)
            persons.append(PersonRecord(zjlx="", zjhm=person_id, xm=person_id, photo_path=full_path))

    if not persons:
        raise RuntimeError("no cached face photos found; sync the face library first")

    stage_root = _make_stage_root("face_rebuild")
    stage_feature_dir = os.path.join(stage_root, "features")
    os.makedirs(stage_feature_dir, exist_ok=True)
    stage_db_path = os.path.join(stage_root, "person_db.pkl")
    stage_meta_path = os.path.join(stage_root, "meta.json")

    _report(progress_cb, stage="load_models", message="Loading face models", processed=0, total=len(persons))
    detector, recognizer = get_face_models()
    success = 0
    failed = 0
    total = len(persons)
    try:
        for index, person in enumerate(persons, 1):
            if not person.photo_path:
                person.photo_path = get_face_library_photo_path(person.zjhm)
            if not person.photo_path or not os.path.isfile(person.photo_path):
                failed += 1
                _report(progress_cb, stage="extract", message=f"Rebuilding features {index}/{total}", processed=index, total=total)
                continue
            img = load_image(person.photo_path)
            if img is None:
                failed += 1
                _report(progress_cb, stage="extract", message=f"Rebuilding features {index}/{total}", processed=index, total=total)
                continue
            embedding, _info = extract_best_face_embedding(img, detector, recognizer, use_enhance=True)
            if embedding is None:
                failed += 1
                _report(progress_cb, stage="extract", message=f"Rebuilding features {index}/{total}", processed=index, total=total)
                continue
            person.embedding = embedding
            np.save(os.path.join(stage_feature_dir, f"{person.zjhm}.npy"), embedding)
            success += 1
            _report(progress_cb, stage="extract", message=f"Rebuilding features {index}/{total}", processed=index, total=total)

        _save_person_db_to_path(persons, stage_db_path)
        meta = _load_meta()
        meta["last_rebuild_ts"] = int(time.time())
        meta["valid_person_count"] = success
        _save_meta_to_path(meta, stage_meta_path)
        _commit_face_library_stage(
            stage_feature_dir=stage_feature_dir,
            stage_db_path=stage_db_path,
            stage_meta_path=stage_meta_path,
        )
        _report(progress_cb, stage="complete", message="Face feature rebuild completed", processed=total, total=total)
        return {"ok": True, "processed": len(persons), "success": success, "failed": failed}
    finally:
        _cleanup_path(stage_root)


def sync_face_library(progress_cb=None) -> dict[str, Any]:
    if not POSTGRES_ENABLED:
        raise RuntimeError("PostgreSQL sync is disabled by POSTGRES_ENABLED")
    if not postgres_configured():
        raise RuntimeError("PostgreSQL connection is not fully configured")

    try:
        import psycopg2
        import psycopg2.extras
    except Exception as exc:
        raise RuntimeError(f"psycopg2-binary is not installed: {exc}") from exc

    _report(progress_cb, stage="connect", message="Connecting to PostgreSQL", processed=0, total=0)
    with get_postgres_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _report(progress_cb, stage="query", message="Executing face library SQL", processed=0, total=0)
            cur.execute(_load_query_sql())
            rows = cur.fetchall()

    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        person_id = row.get("zjhm") or ""
        if not person_id:
            continue
        if person_id not in seen:
            seen[person_id] = dict(row)
        elif seen[person_id].get("xp") is None and row.get("xp") is not None:
            seen[person_id] = dict(row)

    _ensure_dirs()
    stage_root = _make_stage_root("face_sync")
    stage_photo_dir = os.path.join(stage_root, "photos")
    stage_feature_dir = os.path.join(stage_root, "features")
    os.makedirs(stage_photo_dir, exist_ok=True)
    os.makedirs(stage_feature_dir, exist_ok=True)
    stage_db_path = os.path.join(stage_root, "person_db.pkl")
    stage_meta_path = os.path.join(stage_root, "meta.json")

    _report(progress_cb, stage="prepare_files", message="Preparing local face library cache", processed=0, total=len(seen))
    persons: list[PersonRecord] = []
    saved = 0
    dedup_rows = list(seen.values())
    total = len(dedup_rows)
    try:
        for index, row in enumerate(dedup_rows, 1):
            person = PersonRecord(zjlx=row.get("zjlx") or "", zjhm=row.get("zjhm") or "", xm=row.get("xm") or "")
            img = _decode_photo(row.get("xp"))
            if img is not None:
                stage_photo_path = os.path.join(stage_photo_dir, f"{person.zjhm}.jpg")
                cv2.imwrite(stage_photo_path, img)
                person.photo_path = os.path.join(PHOTO_DIR, f"{person.zjhm}.jpg")
                saved += 1
            persons.append(person)
            _report(progress_cb, stage="save_photos", message=f"Saving face photos {index}/{total}", processed=index, total=total)

        _report(progress_cb, stage="load_models", message="Loading face models", processed=0, total=len(persons))
        detector, recognizer = get_face_models()
        success = 0
        for index, person in enumerate(persons, 1):
            if not person.photo_path:
                _report(progress_cb, stage="extract", message=f"Extracting face features {index}/{len(persons)}", processed=index, total=len(persons))
                continue
            stage_photo_path = os.path.join(stage_photo_dir, f"{person.zjhm}.jpg")
            img = load_image(stage_photo_path)
            if img is None:
                _report(progress_cb, stage="extract", message=f"Extracting face features {index}/{len(persons)}", processed=index, total=len(persons))
                continue
            embedding, _info = extract_best_face_embedding(img, detector, recognizer, use_enhance=True)
            if embedding is None:
                _report(progress_cb, stage="extract", message=f"Extracting face features {index}/{len(persons)}", processed=index, total=len(persons))
                continue
            person.embedding = embedding
            np.save(os.path.join(stage_feature_dir, f"{person.zjhm}.npy"), embedding)
            success += 1
            _report(progress_cb, stage="extract", message=f"Extracting face features {index}/{len(persons)}", processed=index, total=len(persons))

        _save_person_db_to_path(persons, stage_db_path)
        now = int(time.time())
        _save_meta_to_path(
            {
                "last_sync_ts": now,
                "last_rebuild_ts": now,
                "last_sync_rows": len(rows),
                "saved_photo_count": saved,
                "valid_person_count": success,
            },
            stage_meta_path,
        )
        _commit_face_library_stage(
            stage_photo_dir=stage_photo_dir,
            stage_feature_dir=stage_feature_dir,
            stage_db_path=stage_db_path,
            stage_meta_path=stage_meta_path,
        )
        _report(progress_cb, stage="complete", message="Face library sync completed", processed=len(persons), total=len(persons))
        return {"ok": True, "rows": len(rows), "saved_photos": saved, "valid_person_count": success}
    finally:
        _cleanup_path(stage_root)


def identify_image_path(image_path: str, top_k: int | None = None) -> dict[str, Any]:
    top_k = max(1, int(top_k or FACE_MATCH_TOP_K))
    status = get_face_library_status()
    if not status["ready"]:
        return {"status": "library_unavailable", "error": "face library is not ready", "face_count": 0, "faces": []}

    img = load_image(image_path)
    if img is None:
        return {"status": "error", "error": f"cannot read image: {image_path}", "face_count": 0, "faces": []}

    detector, recognizer = get_face_models()
    faces = extract_probe_embeddings(img, detector, recognizer, use_enhance=True)
    if not faces:
        return {"status": "no_face", "face_count": 0, "faces": []}

    persons, db_matrix = _load_cached_matrix()
    if db_matrix.size == 0:
        return {"status": "library_unavailable", "error": "face library has no valid embeddings", "face_count": 0, "faces": []}

    # Use VectorIndex (hnswlib or numpy fallback) for fast search
    vi = _VECTOR_INDEX
    face_results = []
    overall_status = "no_match"
    for embedding, info in faces:
        top_indexes, scores = vi.query(embedding, k=top_k)
        matches = []
        for idx, score in zip(top_indexes, scores):
            score = float(score)
            if score >= FACE_SIMILARITY_THR:
                matches.append(_person_payload(persons[int(idx)], score))

        face_status = "matched" if matches else ("low_quality" if info.get("quality") == "low_quality" else "no_match")
        if face_status == "matched":
            overall_status = "matched"
        elif overall_status != "matched" and face_status == "low_quality":
            overall_status = "low_quality"

        face_results.append(
            {
                "status": face_status,
                "bbox": [round(float(v), 2) for v in info["bbox"]],
                "face_size": info.get("face_size"),
                "det_score": info.get("det_score"),
                "blur_score": info.get("blur_score"),
                "quality": info.get("quality"),
                "used_align": info.get("used_align"),
                "top_matches": matches,
            }
        )

    return {"status": overall_status, "face_count": len(face_results), "faces": face_results}


def identify_image_paths(image_paths: list[str], top_k: int | None = None) -> list[dict[str, Any]]:
    results = []
    for image_path in image_paths:
        results.append(identify_image_path(image_path, top_k=top_k))
    return results
