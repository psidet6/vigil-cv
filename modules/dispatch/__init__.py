"""Dispatch module package."""

from shared.events import on


def _on_identity_matched(*, owner_key, owner_ip, job, items, result, **_kw):
    """Subscribe to face identity events and ingest into dispatch queue."""
    from modules.dispatch.services.queue_service import ingest_identity_results

    flow = ingest_identity_results(owner_key, owner_ip, job, items)
    # Write back into the caller-provided dict so face route can read counts.
    result.update(flow)


on("identity_matched", _on_identity_matched)