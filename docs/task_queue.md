# Task Queue Notes

Vigil CV uses a lightweight SQLite-backed task queue for long-running work. The web process records a task and returns quickly; `worker.py` claims pending tasks and performs the heavy work outside the request path.

## Why it exists

- Avoid browser timeouts for training, uploads, batch detection, and face-library rebuilds.
- Keep task state durable across web-process restarts.
- Limit CPU-heavy jobs to the worker process.
- Make progress and failure state queryable from the diagnostics tab.

## Components

- `shared/task_queue.py`: queue table creation, submit, claim, complete, fail, stale-task reset.
- `worker.py`: polling loop and task handlers.
- `modules/diagnostics/`: read-only queue diagnostics for operators.
- `tests/test_task_queue*.py`: unit coverage for queue behavior and diagnostics payloads.

## Operational Defaults

SQLite is appropriate for a single-node private deployment and keeps the public demo simple. If the system later needs multiple workers across multiple machines, the queue boundary can be replaced with Redis/Celery or another broker without changing the UI workflow.
