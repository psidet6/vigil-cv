from __future__ import annotations

from datetime import datetime
import re
from typing import Any, List, Tuple

from shared.config.config import (
    POSTGRES_CONNECT_TIMEOUT,
    POSTGRES_DB,
    POSTGRES_ENABLED,
    POSTGRES_HOST,
    POSTGRES_IMAGE_HOUR_COLUMN,
    POSTGRES_IMAGE_TIME_COLUMN,
    POSTGRES_IMAGE_URL_COLUMN,
    POSTGRES_PASSWORD,
    POSTGRES_PERSON_CONTEXT_TABLE,
    POSTGRES_PERSON_ID_COLUMN,
    POSTGRES_PORT,
    POSTGRES_QUOTE_IDENTIFIERS,
    POSTGRES_SMS_OUTBOX_TABLE,
    POSTGRES_SMS_TIME_SQL,
    POSTGRES_SOURCE_IMAGE_TABLE,
    POSTGRES_USER,
)


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SMS_TIME_SQL_ALLOWLIST = {
    "NOW()",
    "CURRENT_TIMESTAMP",
    "LOCALTIMESTAMP",
    "CLOCK_TIMESTAMP()",
}


def postgres_configured() -> bool:
    return bool(POSTGRES_HOST and POSTGRES_DB and POSTGRES_USER)


def postgres_enabled() -> bool:
    return bool(POSTGRES_ENABLED)


def _ensure_postgres_ready() -> None:
    if not postgres_enabled():
        raise RuntimeError("PostgreSQL data source is disabled by POSTGRES_ENABLED")
    if not postgres_configured():
        raise RuntimeError("PostgreSQL connection is not fully configured")


def get_postgres_connection():
    _ensure_postgres_ready()
    try:
        import psycopg2
    except Exception as exc:
        raise RuntimeError(f"psycopg2-binary is not installed: {exc}") from exc

    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=POSTGRES_CONNECT_TIMEOUT,
    )


def _sql_identifier_path(value: str) -> str:
    raw_parts = [part.strip() for part in str(value or "").split(".") if part.strip()]
    if not raw_parts or any(not _IDENT_RE.match(part) for part in raw_parts):
        raise ValueError(f"invalid PostgreSQL identifier: {value!r}")
    if POSTGRES_QUOTE_IDENTIFIERS:
        return ".".join(f'"{part}"' for part in raw_parts)
    return ".".join(raw_parts)


def _sms_time_sql() -> str:
    value = str(POSTGRES_SMS_TIME_SQL or "NOW()").strip()
    normalized = re.sub(r"\s+", "", value.upper())
    if normalized not in _SMS_TIME_SQL_ALLOWLIST:
        raise ValueError(
            "POSTGRES_SMS_TIME_SQL must be one of: "
            + ", ".join(sorted(_SMS_TIME_SQL_ALLOWLIST))
        )
    return value


def build_query_and_params(
    kssj: str,
    jssj: str,
    hours: List[str],
    model_key: str,
) -> tuple[str, list[Any]]:
    del model_key
    table = _sql_identifier_path(POSTGRES_SOURCE_IMAGE_TABLE)
    url_col = _sql_identifier_path(POSTGRES_IMAGE_URL_COLUMN)
    time_col = _sql_identifier_path(POSTGRES_IMAGE_TIME_COLUMN)

    sql = (
        f"SELECT {url_col} AS image_url, {time_col} AS capture_time "
        f"FROM {table} "
        f"WHERE {time_col} BETWEEN %s AND %s"
    )
    params: list[Any] = [kssj, jssj]

    normalized_hours = [str(hour).zfill(2) for hour in (hours or []) if str(hour).strip()]
    if normalized_hours:
        hour_col = _sql_identifier_path(POSTGRES_IMAGE_HOUR_COLUMN)
        sql += f" AND LPAD(CAST({hour_col} AS TEXT), 2, '0') = ANY(%s)"
        params.append(normalized_hours)

    sql += f" ORDER BY {time_col} ASC"
    return sql, params


def _normalize_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value else ""


def fetch_image_urls(
    kssj: str,
    jssj: str,
    hours: List[str],
    model_key: str,
) -> List[Tuple[str, str]]:
    sql, params = build_query_and_params(kssj, jssj, hours, model_key)
    try:
        import psycopg2.extras
    except Exception as exc:
        raise RuntimeError(f"psycopg2-binary is not installed: {exc}") from exc

    with get_postgres_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

    output: List[Tuple[str, str]] = []
    for row in rows:
        url = str(row.get("image_url") or "").strip()
        if not url:
            continue
        output.append((url, _normalize_time(row.get("capture_time"))))
    return output


def fetch_dispatch_person_context(id_number: str) -> dict:
    safe_id_number = str(id_number or "").strip()
    if not safe_id_number:
        return {}

    try:
        import psycopg2.extras
    except Exception as exc:
        raise RuntimeError(f"psycopg2-binary is not installed: {exc}") from exc

    table = _sql_identifier_path(POSTGRES_PERSON_CONTEXT_TABLE)
    id_column = _sql_identifier_path(POSTGRES_PERSON_ID_COLUMN)
    sql = f"""
        SELECT
            xm,
            lxdh,
            ds,
            dsmc,
            ssxq,
            ssxqmc,
            pcs,
            pcsmc,
            dz
        FROM {table}
        WHERE {id_column} = %s
        LIMIT 1
    """

    with get_postgres_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(sql, (safe_id_number,))
            row = cursor.fetchone()

    if not row:
        return {}

    keys = ["xm", "lxdh", "ds", "dsmc", "ssxq", "ssxqmc", "pcs", "pcsmc", "dz"]
    return {
        key: (str(row.get(key)).strip() if row.get(key) is not None else "")
        for key in keys
    }


def insert_sms_queue_record(payload: dict) -> None:
    table = _sql_identifier_path(POSTGRES_SMS_OUTBOX_TABLE)
    sql = f"""
        INSERT INTO {table} (
            mobile, content, deadtime, status, eid, userid, password, userport
        ) VALUES (
            %s, %s, {_sms_time_sql()}, %s, %s, %s, %s, %s
        )
    """
    params = (
        str(payload.get("mobile", "") or "").strip(),
        str(payload.get("content", "") or "").strip(),
        str(payload.get("status", "0") or "0").strip(),
        str(payload.get("eid", "") or "").strip(),
        str(payload.get("userid", "") or "").strip(),
        str(payload.get("password", "") or "").strip(),
        str(payload.get("userport", "") or "").strip(),
    )
    with get_postgres_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()
