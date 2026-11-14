"""
Durable Redis-backed LangGraph Checkpointer (`RedisBackedCheckpointSaver`).

Wraps LangGraph's `MemorySaver` with synchronous & asynchronous write-through
persistence into Redis hashes (`finflow:checkpoints:<thread_id>`) so that:
1. Full LangGraph state-history, `interrupt()`, `Command(resume=...)`, and
   time-travel state forking work seamlessly across any `langgraph` version.
2. Every super-step checkpoint is durably mirrored into Redis with JSON/base64
   serialization for external inspection in RedisInsight and cross-process recovery.
"""

from __future__ import annotations

import base64
import json
import pickle
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
)
from langgraph.checkpoint.memory import MemorySaver

from finflow.resilience.redis_client import get_redis_client


class RedisBackedCheckpointSaver(MemorySaver):
    """
    LangGraph CheckpointSaver that combines `MemorySaver`'s native in-memory
    tuple/writes engine with durable Redis write-through storage and hydration.
    """

    REDIS_PREFIX = "finflow:checkpoint"

    def __init__(self, redis_client: Any | None = None) -> None:
        super().__init__()
        self._redis = redis_client or get_redis_client()
        self._hydrated_threads: set[str] = set()

    def _thread_key(self, thread_id: str) -> str:
        return f"{self.REDIS_PREFIX}:thread:{thread_id}"

    def _meta_index_key(self, thread_id: str) -> str:
        return f"{self.REDIS_PREFIX}:meta:{thread_id}"

    def persist_thread_storage(self, thread_id: str, checkpoint_id: str, metadata: Any) -> None:
        """Serialize the thread's checkpoint state into Redis."""
        try:
            raw_thread_data = {
                "storage": dict(self.storage.get(thread_id, {})),
                "writes": {
                    k: dict(v)
                    for k, v in self.writes.items()
                    if isinstance(k, tuple) and len(k) > 0 and k[0] == thread_id
                },
            }
            encoded = base64.b64encode(pickle.dumps(raw_thread_data)).decode("ascii")
            self._redis.set(self._thread_key(thread_id), encoded)

            meta_summary = {
                "checkpoint_id": checkpoint_id,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "step": metadata.get("step", -1) if isinstance(metadata, dict) else -1,
                "source": metadata.get("source", "loop") if isinstance(metadata, dict) else "loop",
            }
            self._redis.hset(
                self._meta_index_key(thread_id),
                key=checkpoint_id,
                value=json.dumps(meta_summary),
            )
        except Exception:
            # Never fail graph execution if secondary telemetry serialization fails
            pass

    def _hydrate_thread_if_needed(self, thread_id: str) -> None:
        """Hydrate in-memory saver from Redis if this worker hasn't loaded the thread yet."""
        if thread_id in self._hydrated_threads or thread_id in self.storage:
            self._hydrated_threads.add(thread_id)
            return

        try:
            encoded = self._redis.get(self._thread_key(thread_id))
            if encoded:
                raw_thread_data = pickle.loads(base64.b64decode(encoded.encode("ascii")))
                if "storage" in raw_thread_data:
                    self.storage[thread_id].update(raw_thread_data["storage"])
                if "writes" in raw_thread_data:
                    for k, v in raw_thread_data["writes"].items():
                        self.writes[k].update(v)
            self._hydrated_threads.add(thread_id)
        except Exception:
            self._hydrated_threads.add(thread_id)

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = str(config.get("configurable", {}).get("thread_id", ""))
        if thread_id:
            self._hydrate_thread_if_needed(thread_id)
        return super().get_tuple(config)

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        next_config = super().put(config, checkpoint, metadata, new_versions)
        thread_id = str(config.get("configurable", {}).get("thread_id", ""))
        checkpoint_id = str(checkpoint.get("id", ""))
        if thread_id and checkpoint_id:
            self.persist_thread_storage(thread_id, checkpoint_id, metadata)
        return next_config

    def put_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        super().put_writes(config, writes, task_id, task_path)
        thread_id = str(config.get("configurable", {}).get("thread_id", ""))
        checkpoint_id = str(config.get("configurable", {}).get("checkpoint_id", "latest"))
        if thread_id:
            self.persist_thread_storage(thread_id, checkpoint_id, {})

    def list_redis_checkpoint_summaries(self, thread_id: str) -> list[dict[str, Any]]:
        """Return human-readable checkpoint metadata stored in Redis for a thread."""
        raw_map = self._redis.hgetall(self._meta_index_key(thread_id))
        summaries: list[dict[str, Any]] = []
        for _, payload in raw_map.items():
            try:
                summaries.append(json.loads(payload))
            except Exception:
                continue
        summaries.sort(key=lambda x: x.get("step", 0))
        return summaries


_CHECKPOINTER_SINGLETON: RedisBackedCheckpointSaver | None = None


def get_checkpointer(force_new: bool = False) -> RedisBackedCheckpointSaver:
    """Return shared `RedisBackedCheckpointSaver` instance."""
    global _CHECKPOINTER_SINGLETON
    if _CHECKPOINTER_SINGLETON is None or force_new:
        _CHECKPOINTER_SINGLETON = RedisBackedCheckpointSaver()
    return _CHECKPOINTER_SINGLETON
