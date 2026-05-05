# Windows 10 Offline Install

This note describes a sanitized Windows 10 offline setup. Database-backed
features use PostgreSQL only; no external database client bundle is required.

## Required Files

- project source
- `requirements.txt`
- `requirements.lock`
- `requirements-dev.txt` if tests are needed
- `wheels/clip-1.0-py3-none-any.whl`
- `static/dist/tailwind.css`
- required model binaries under `model/`

## Create Environment

```powershell
uv venv .venv --python 3.12
```

Or with standard Python:

```powershell
py -3.12 -m venv .venv
```

## Install Dependencies

Runtime:

```powershell
uv pip install --python .\.venv\Scripts\python.exe --no-index --find-links .\wheels -r requirements.txt
```

Development and tests:

```powershell
uv pip install --python .\.venv\Scripts\python.exe --no-index --find-links .\wheels -r requirements-dev.txt
```

Pinned runtime set:

```powershell
uv pip install --python .\.venv\Scripts\python.exe --no-index --find-links .\wheels -r requirements.lock
```

## Configure PostgreSQL

Copy `ops/app.env.local.example` to `app.env`, then replace:

```text
POSTGRES_ENABLED=true
POSTGRES_HOST=postgres.example.com
POSTGRES_PORT=5432
POSTGRES_DB=vigil_cv
POSTGRES_USER=app_user
POSTGRES_PASSWORD=CHANGE_ME
```

The same PostgreSQL connection is used for image URL queries, SMS outbox
inserts, dispatch person context, and face-library sync.

If PostgreSQL identifiers were created with quoted uppercase names, set:

```text
POSTGRES_QUOTE_IDENTIFIERS=true
```

For public/demo use, keep:

```text
POSTGRES_ENABLED=false
DISPATCH_MOCK_MODE=true
```

## Start

```powershell
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5001/`.
