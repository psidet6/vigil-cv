from __future__ import annotations

from flask import Blueprint, jsonify, request

from shared.config.config import logger
from shared.health import get_health_report
from shared.task_queue_diagnostics import get_task_queue_snapshot


diagnostics_bp = Blueprint("diagnostics", __name__, url_prefix="/diagnostics")


@diagnostics_bp.get("/task-queue")
def task_queue_diagnostics():
    task_type = (request.args.get("task_type") or "").strip() or None
    status = (request.args.get("status") or "").strip() or None
    limit = request.args.get("limit")
    try:
        snapshot = get_task_queue_snapshot(task_type=task_type, status=status, limit=limit)
        health = get_health_report()
    except Exception as exc:
        logger.exception("failed to load task queue diagnostics: %s", exc)
        return jsonify({"ok": False, "error": "failed to load task queue diagnostics"}), 500

    snapshot["health"] = {
        "ok": bool(health.get("ok")),
        "task_queue": (health.get("checks") or {}).get("task_queue") or {},
    }
    return jsonify({"ok": True, **snapshot})
