# CentOS Stream 10 Offline Docker Deploy

This sanitized deployment uses PostgreSQL as the only external database.
The Docker image no longer packages an external database client bundle.

## Build On An Online Machine

```bash
docker build --platform linux/amd64 -f ops/Dockerfile -t vigil-cv:centos-stream10 .
docker save -o vigil-cv-centos-stream10.tar vigil-cv:centos-stream10
sha256sum vigil-cv-centos-stream10.tar
```

PowerShell:

```powershell
docker build --platform linux/amd64 -f ops/Dockerfile -t vigil-cv:centos-stream10 .
docker save -o .\vigil-cv-centos-stream10.tar vigil-cv:centos-stream10
Get-FileHash .\vigil-cv-centos-stream10.tar -Algorithm SHA256
```

## Files To Transfer

- `vigil-cv-centos-stream10.tar`
- `compose.yaml`
- `.env` based on `.env.example`
- optional `data/` directory if preserving history/caches

## Configure `.env`

Set PostgreSQL once:

```text
POSTGRES_ENABLED=true
POSTGRES_HOST=postgres.example.com
POSTGRES_PORT=5432
POSTGRES_DB=vigil_cv
POSTGRES_USER=app_user
POSTGRES_PASSWORD=CHANGE_ME
```

These flows all use the same connection:

- batch image URL query
- SMS outbox insert when `DISPATCH_MOCK_MODE=false`
- dispatch person context lookup
- face-library sync

Set the table and column names if your migrated schema differs from the
defaults:

```text
POSTGRES_SOURCE_IMAGE_TABLE=sample_schema.source_image_table
POSTGRES_IMAGE_URL_COLUMN=image_url
POSTGRES_IMAGE_TIME_COLUMN=capture_time
POSTGRES_IMAGE_HOUR_COLUMN=capture_hour
POSTGRES_PERSON_CONTEXT_TABLE=sample_schema.person_context
POSTGRES_PERSON_ID_COLUMN=gmsfhm
POSTGRES_SMS_OUTBOX_TABLE=sample_schema.sms_outbox
POSTGRES_FACE_QUERY_PATH=/app/modules/face/sql/face_library.sql
```

## Load And Start Offline

```bash
docker load -i vigil-cv-centos-stream10.tar
docker compose --env-file .env -f compose.yaml up -d
docker compose --env-file .env -f compose.yaml logs -f app
```

Health check:

```bash
curl http://127.0.0.1:5001/healthz
```
