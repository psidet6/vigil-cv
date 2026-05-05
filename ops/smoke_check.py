from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass
class SmokeResult:
    name: str
    ok: bool
    detail: str


def _summarize_body(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").replace("\r", " ").replace("\n", " ").strip()
    return text[:180] + ("..." if len(text) > 180 else "")


def check_http_endpoint(base_url: str, path: str, timeout: float) -> SmokeResult:
    url = base_url.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json, text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            body = response.read(4096)
    except HTTPError as exc:
        detail = _summarize_body(exc.read(4096))
        return SmokeResult(path, False, f"HTTP {exc.code}: {detail or exc.reason}")
    except URLError as exc:
        return SmokeResult(path, False, f"request failed: {exc.reason}")
    except Exception as exc:
        return SmokeResult(path, False, f"request failed: {exc}")

    if status != 200:
        return SmokeResult(path, False, f"HTTP {status}: {_summarize_body(body)}")
    return SmokeResult(path, True, f"HTTP {status}")


def check_synthetic_task_queue(db_path: Path | None = None) -> SmokeResult:
    temp_dir: Path | None = None
    if db_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="vigil_cv_queue_smoke_"))
        db_path = temp_dir / "queue.sqlite3"

    from shared import task_queue

    old_db_path = task_queue.SQLITE_DB_PATH
    old_logger_level = task_queue.logger.level
    try:
        task_queue.logger.setLevel(logging.WARNING)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        task_queue.SQLITE_DB_PATH = str(db_path)
        with task_queue._connect() as conn:
            task_queue.init_task_queue_table(conn)
            conn.commit()

        task_id = task_queue.submit_task("smoke", {"job_id": "smoke-job"})
        claimed = task_queue.claim_task("smoke")
        if not claimed or claimed.get("id") != task_id:
            return SmokeResult("synthetic task queue", False, "submitted task was not claimable")

        task_queue.complete_task(task_id, {"checked": True})
        completed = task_queue.get_task(task_id)
        if not completed or completed.get("status") != "completed":
            return SmokeResult("synthetic task queue", False, "claimed task did not complete cleanly")

        return SmokeResult("synthetic task queue", True, f"claimed and completed {task_id}")
    except Exception as exc:
        return SmokeResult("synthetic task queue", False, str(exc))
    finally:
        task_queue.SQLITE_DB_PATH = old_db_path
        task_queue.logger.setLevel(old_logger_level)
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def run_checks(args: argparse.Namespace) -> list[SmokeResult]:
    results: list[SmokeResult] = []
    if not args.queue_only:
        for path in ("/livez", "/healthz", "/diagnostics/task-queue", "/"):
            results.append(check_http_endpoint(args.base_url, path, args.timeout))

    queue_db = Path(args.queue_db).resolve() if args.queue_db else None
    results.append(check_synthetic_task_queue(queue_db))
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local smoke checks for vigil-cv.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001", help="Web service base URL.")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument("--queue-only", action="store_true", help="Skip HTTP endpoints and only test queue claim flow.")
    parser.add_argument("--queue-db", default="", help="Optional SQLite path for the synthetic queue check.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = run_checks(args)
    for result in results:
        prefix = "[OK]" if result.ok else "[FAIL]"
        print(f"{prefix} {result.name}: {result.detail}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
