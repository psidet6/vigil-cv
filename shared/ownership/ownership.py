from __future__ import annotations

import re
from uuid import uuid4

from flask import Request, session


OWNER_SESSION_KEY = "owner_key"
OWNER_HEADER_NAMES = ("X-Vigil-CV-User", "X-Vigil-CV-Owner")


def _owner_ip_from_request(request: Request) -> str:
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or ""


def _stable_owner_from_request(request: Request) -> str:
    for header_name in OWNER_HEADER_NAMES:
        raw_value = str(request.headers.get(header_name, "") or "").strip()
        if not raw_value:
            continue
        normalized = re.sub(r"[^0-9A-Za-z_.@-]+", "_", raw_value.lower()).strip("_")
        if normalized:
            return f"account:{normalized[:96]}"
    return ""


def get_request_owner(request: Request) -> tuple[str, str]:
    owner_ip = _owner_ip_from_request(request)
    stable_owner_key = _stable_owner_from_request(request)
    if stable_owner_key:
        if session.get(OWNER_SESSION_KEY) != stable_owner_key:
            session[OWNER_SESSION_KEY] = stable_owner_key
            session.modified = True
        return stable_owner_key, owner_ip

    owner_key = str(session.get(OWNER_SESSION_KEY) or "").strip()
    if not owner_key:
        owner_key = uuid4().hex
        session[OWNER_SESSION_KEY] = owner_key
        session.modified = True

    return owner_key, owner_ip


def job_matches_owner(job: dict | None, owner_key: str, owner_ip: str) -> bool:
    if not job:
        return False

    stored_owner_key = str(job.get("owner_key") or "").strip()
    if stored_owner_key:
        return bool(owner_key) and stored_owner_key == owner_key

    stored_owner_ip = str(job.get("owner_ip") or "").strip()
    return bool(owner_ip) and stored_owner_ip == owner_ip
