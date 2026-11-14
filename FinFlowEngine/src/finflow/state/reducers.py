"""
Custom deterministic reducers for LangGraph state channels.

In parallel fan-out (`Send` API) and retry scenarios, standard `operator.add`
can produce duplicate records if a branch retries or a checkpoint is replayed.
These reducers guarantee idempotent, deterministic state merging.
"""

from __future__ import annotations

from typing import Any


def merge_dict_by_key(
    existing: dict[str, Any] | None,
    updates: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Deterministically merge dictionaries, preserving existing keys and
    updating/inserting new keys from parallel agent branches.
    """
    base: dict[str, Any] = dict(existing) if existing else {}
    if updates:
        base.update(updates)
    return base


def deduplicated_audit_reducer(
    existing: list[dict[str, Any]] | None,
    new_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    Append audit log entries while deduplicating by `event_id` so retried nodes
    do not pollute the state history with identical events.
    """
    result: list[dict[str, Any]] = list(existing) if existing else []
    seen_ids = {item.get("event_id") for item in result if item.get("event_id")}

    for item in new_items or []:
        event_id = item.get("event_id")
        if event_id and event_id in seen_ids:
            continue
        if event_id:
            seen_ids.add(event_id)
        result.append(item)

    return result


def deduplicated_string_list_reducer(
    existing: list[str] | None,
    new_items: list[str] | None,
) -> list[str]:
    """Preserve insertion order while eliminating duplicate string entries."""
    result: list[str] = list(existing) if existing else []
    seen = set(result)
    for item in new_items or []:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
