"""
Redis Streams Lifecycle Event Bus & Dead-Letter Queue (DLQ) Manager.

Publishes real-time workflow telemetry events to `finflow:events:stream` and
captures unrecoverable workflow payloads in `finflow:dlq:stream` for post-mortem
inspection and automated replay.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from finflow.resilience.redis_client import get_redis_client


class RedisEventBusAndDLQ:
    """
    Manages Redis Streams for both real-time workflow lifecycle events and
    unrecoverable Dead-Letter Queue (DLQ) failure records.
    """

    EVENT_STREAM_KEY = "finflow:events:stream"
    DLQ_STREAM_KEY = "finflow:dlq:stream"

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client or get_redis_client()

    def publish_event(
        self,
        thread_id: str,
        event_type: str,
        node: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Append a structured workflow lifecycle event to the Redis Stream."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_id": thread_id,
            "event_type": event_type,
            "node": node,
            "payload": json.dumps(payload or {}, default=str),
        }
        return str(self._redis.xadd(self.EVENT_STREAM_KEY, record, maxlen=5000))

    def push_to_dlq(
        self,
        thread_id: str,
        failed_node: str,
        error_type: str,
        error_message: str,
        state_snapshot: dict[str, Any],
    ) -> str:
        """Route an unrecoverable workflow execution failure to the Redis Dead-Letter Queue."""
        dlq_entry = {
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "thread_id": thread_id,
            "failed_node": failed_node,
            "error_type": error_type,
            "error_message": error_message,
            "state_snapshot": json.dumps(state_snapshot, default=str),
        }
        entry_id = str(self._redis.xadd(self.DLQ_STREAM_KEY, dlq_entry, maxlen=1000))
        self.publish_event(
            thread_id=thread_id,
            event_type="workflow.routed_to_dlq",
            node=failed_node,
            payload={"dlq_entry_id": entry_id, "error_type": error_type},
        )
        return entry_id

    def list_dlq_entries(self, count: int = 50) -> list[dict[str, Any]]:
        """Retrieve Dead-Letter Queue entries for operator inspection or replay."""
        raw_entries = self._redis.xrange(self.DLQ_STREAM_KEY, count=count)
        parsed: list[dict[str, Any]] = []
        for entry_id, fields in raw_entries:
            item = dict(fields)
            item["dlq_id"] = entry_id
            if "state_snapshot" in item and isinstance(item["state_snapshot"], str):
                try:
                    item["state_snapshot"] = json.loads(item["state_snapshot"])
                except Exception:
                    pass
            parsed.append(item)
        return parsed

    def list_lifecycle_events(self, thread_id: str | None = None, count: int = 100) -> list[dict[str, Any]]:
        """Read recent workflow lifecycle events from `finflow:events:stream`."""
        raw_entries = self._redis.xrange(self.EVENT_STREAM_KEY, count=count)
        events: list[dict[str, Any]] = []
        for entry_id, fields in raw_entries:
            if thread_id and fields.get("thread_id") != thread_id:
                continue
            item = dict(fields)
            item["stream_id"] = entry_id
            if "payload" in item and isinstance(item["payload"], str):
                try:
                    item["payload"] = json.loads(item["payload"])
                except Exception:
                    pass
            events.append(item)
        return events
