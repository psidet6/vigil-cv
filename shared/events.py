"""Lightweight in-process event bus for decoupling modules.

Usage::

    from shared.events import on, emit

    # subscriber (e.g. in dispatch module init)
    on("identity_matched", lambda **kw: ingest_to_queue(**kw))

    # publisher (e.g. in face module)
    emit("identity_matched", owner_key=..., items=...)

Events are dispatched synchronously in the caller's thread.
Subscriber exceptions are logged but never propagate to the publisher.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from shared.config.config import logger

_lock = threading.Lock()
_handlers: dict[str, list[Callable[..., Any]]] = {}


def on(event_name: str, handler: Callable[..., Any]) -> None:
    """Register *handler* to be called when *event_name* is emitted."""
    with _lock:
        _handlers.setdefault(event_name, []).append(handler)


def off(event_name: str, handler: Callable[..., Any]) -> None:
    """Remove a previously registered handler (idempotent)."""
    with _lock:
        listeners = _handlers.get(event_name)
        if listeners:
            try:
                listeners.remove(handler)
            except ValueError:
                pass


def emit(event_name: str, **kwargs: Any) -> None:
    """Fire *event_name*, passing *kwargs* to every registered handler.

    Exceptions in individual handlers are logged and swallowed so that one
    broken subscriber cannot break the publisher.
    """
    with _lock:
        listeners = list(_handlers.get(event_name, []))
    for handler in listeners:
        try:
            handler(**kwargs)
        except Exception:
            logger.exception("event handler error for %r", event_name)


def clear(event_name: str | None = None) -> None:
    """Remove all handlers for *event_name*, or all handlers if ``None``."""
    with _lock:
        if event_name is None:
            _handlers.clear()
        else:
            _handlers.pop(event_name, None)
