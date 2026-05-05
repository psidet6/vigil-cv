import time
from uuid import uuid4

import requests

from shared.config.config import (
    DISPATCH_AUTH_URL,
    DISPATCH_CLIENT_ID,
    DISPATCH_CLIENT_SECRET,
    DISPATCH_GRANT_TYPE,
    DISPATCH_MOCK_MODE,
    logger,
)
from modules.dispatch.services.store_service import (
    get_dispatch_auth_session,
    save_dispatch_auth_session,
)


def get_dispatch_auth_status(owner_key: str) -> dict:
    session_item = get_dispatch_auth_session(owner_key)
    now = int(time.time())
    if not session_item:
        return {
            "authenticated": False,
            "status": "pending",
            "expires_in": 0,
            "expires_at": None,
            "updated_ts": None,
            "username": "",
            "token_type": "Bearer",
            "is_mock": False,
            "last_error": "",
        }

    expires_at = session_item.get("expires_at")
    remaining = 0
    if expires_at:
        remaining = max(0, int(expires_at) - now)
    authenticated = bool(session_item.get("access_token")) and (
        not expires_at or remaining > 0
    )
    status = "expired" if session_item.get("access_token") and not authenticated else session_item.get("status", "pending")
    return {
        "authenticated": authenticated,
        "status": status,
        "expires_in": remaining,
        "expires_at": expires_at,
        "updated_ts": session_item.get("updated_ts"),
        "authenticated_ts": session_item.get("authenticated_ts"),
        "username": session_item.get("username", ""),
        "token_type": session_item.get("token_type", "Bearer"),
        "is_mock": bool(session_item.get("is_mock")),
        "last_error": session_item.get("last_error", ""),
    }


def authenticate_dispatch_platform(
    owner_key: str,
    owner_ip: str,
    username: str,
    password: str,
) -> dict:
    username = str(username or "").strip()
    password = str(password or "").strip()
    if not username or not password:
        raise ValueError("username and password are required")

    now = int(time.time())
    if DISPATCH_MOCK_MODE:
        token = "mock-" + uuid4().hex
        session_item = {
            "owner_key": owner_key,
            "owner_ip": owner_ip,
            "username": username,
            "access_token": token,
            "refresh_token": "",
            "token_type": "Bearer",
            "expires_in": 3600,
            "expires_at": now + 3600,
            "authenticated_ts": now,
            "updated_ts": now,
            "status": "authenticated",
            "is_mock": True,
            "last_error": "",
        }
        save_dispatch_auth_session(session_item)
        return get_dispatch_auth_status(owner_key)

    try:
        response = requests.post(
            DISPATCH_AUTH_URL,
            params={
                "client_id": DISPATCH_CLIENT_ID,
                "client_secret": DISPATCH_CLIENT_SECRET,
                "grant_type": DISPATCH_GRANT_TYPE,
                "username": username,
                "password": password,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
    except Exception as exc:
        logger.exception("dispatch auth request failed: %s", exc)
        session_item = {
            "owner_key": owner_key,
            "owner_ip": owner_ip,
            "username": username,
            "access_token": "",
            "refresh_token": "",
            "token_type": "Bearer",
            "expires_in": 0,
            "expires_at": None,
            "authenticated_ts": None,
            "updated_ts": now,
            "status": "error",
            "is_mock": False,
            "last_error": str(exc),
        }
        save_dispatch_auth_session(session_item)
        raise RuntimeError(f"dispatch auth request failed: {exc}") from exc

    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code >= 400 or not payload.get("access_token"):
        error_message = payload.get("error_description") or payload.get("message") or response.text or "auth failed"
        session_item = {
            "owner_key": owner_key,
            "owner_ip": owner_ip,
            "username": username,
            "access_token": "",
            "refresh_token": "",
            "token_type": "Bearer",
            "expires_in": 0,
            "expires_at": None,
            "authenticated_ts": None,
            "updated_ts": now,
            "status": "error",
            "is_mock": False,
            "last_error": str(error_message),
        }
        save_dispatch_auth_session(session_item)
        raise RuntimeError(str(error_message))

    expires_in = int(payload.get("expires_in") or 0)
    session_item = {
        "owner_key": owner_key,
        "owner_ip": owner_ip,
        "username": username,
        "access_token": payload.get("access_token", ""),
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "expires_in": expires_in,
        "expires_at": now + expires_in if expires_in else None,
        "authenticated_ts": now,
        "updated_ts": now,
        "status": "authenticated",
        "is_mock": False,
        "last_error": "",
    }
    save_dispatch_auth_session(session_item)
    return get_dispatch_auth_status(owner_key)


def get_valid_dispatch_token(owner_key: str) -> tuple[str, dict]:
    session_item = get_dispatch_auth_session(owner_key)
    status = get_dispatch_auth_status(owner_key)
    if not session_item or not status.get("authenticated"):
        raise RuntimeError("dispatch platform is not authenticated")
    return str(session_item.get("access_token") or ""), status
