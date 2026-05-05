import io
import os
import time

from flask import Blueprint, send_file, url_for

from shared.db.sqlite import get_job as get_saved_job
from modules.detection.services.job_service import _summarize, get_job_snapshot


file_bp = Blueprint("file", __name__)


def _resolve_job(job_id: str) -> dict | None:
    job = get_job_snapshot(job_id)
    if job is not None:
        return job
    return get_saved_job(job_id)


def _render_parts_page(job_id: str, parts: list[dict]) -> str:
    links = []
    for part in parts:
        name = part.get("name")
        links.append(
            f"<li><a href='{url_for('file.download_zip_part', job_id=job_id, part=name)}'>{name}</a></li>"
        )
    return """
    <html><head><meta charset='utf-8'><title>下载分片</title></head>
    <body><h3>检测结果较多，已按日期切分为多个 ZIP：</h3>
    <ul>{items}</ul>
    </body></html>
    """.replace("{items}", "\n".join(links))


@file_bp.get("/download/<job_id>")
def download_zip(job_id: str):
    job = _resolve_job(job_id)
    if not job:
        return "job not found", 404

    if job.get("status") != "done":
        return "job not found or not ready", 404

    parts = job.get("zip_parts") or []
    zip_path = job.get("zip_path")
    ts = job.get("end_ts") or int(time.time())

    if zip_path and os.path.isfile(zip_path):
        filename = f"{ts}.zip"
        return send_file(
            zip_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )

    if len(parts) > 1:
        return _render_parts_page(job_id, parts)

    return "file not found", 404


@file_bp.get("/download/<job_id>/<part>")
def download_zip_part(job_id: str, part: str):
    job = _resolve_job(job_id)
    if not job or job.get("status") != "done":
        return "job not found or not ready", 404

    parts = {item["name"]: item["path"] for item in (job.get("zip_parts") or [])}
    path = parts.get(part)
    if not path or not os.path.isfile(path):
        return "file not found", 404

    return send_file(path, mimetype="application/zip", as_attachment=True, download_name=part)


@file_bp.get("/summary/<job_id>")
def download_summary(job_id: str):
    job = _resolve_job(job_id)
    if not job:
        return "job not found", 404

    text = job.get("summary_text") or _summarize(job)
    return send_file(
        io.BytesIO(text.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name="summary.txt",
    )
