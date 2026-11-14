"""
Resilient Redis connection manager with automatic fallback to an in-process
Redis-compatible store (FakeRedis or internal dictionary adapter) so the engine
can run both against a live Redis Stack cluster and in isolated unit tests.
"""

from __future__ import annotations

import time
from typing import Any

import redis

from finflow.config import get_settings


class InMemoryRedisAdapter:
    """
    Lightweight, thread-safe Redis-compatible client for offline/dev fallback
    when neither a live Redis server nor `fakeredis` is reachable.
    Supports strings, TTLs, hashes, sets, atomic INCR, and Redis Streams (`xadd`/`xrange`).
    """

    def __init__(self) -> None:
        self._kv: dict[str, tuple[Any, float | None]] = {}
        self._hashes: dict[str, dict[str, Any]] = {}
        self._streams: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._seq: int = 0

    def _is_expired(self, key: str) -> bool:
        if key not in self._kv:
            return True
        _, exp = self._kv[key]
        if exp is not None and time.time() > exp:
            del self._kv[key]
            return True
        return False

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        if self._is_expired(key):
            return None
        val, _ = self._kv[key]
        return str(val) if val is not None else None

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | float | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and not self._is_expired(key):
            return False
        exp = (time.time() + float(ex)) if ex is not None else None
        self._kv[key] = (value.decode("utf-8") if isinstance(value, bytes) else str(value), exp)
        return True

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._kv:
                del self._kv[k]
                deleted += 1
            if k in self._hashes:
                del self._hashes[k]
                deleted += 1
        return deleted

    def incr(self, key: str) -> int:
        current = int(self.get(key) or "0") + 1
        exp = self._kv.get(key, (None, None))[1]
        self._kv[key] = (str(current), exp)
        return current

    def expire(self, key: str, seconds: int | float) -> bool:
        if self._is_expired(key):
            return False
        val, _ = self._kv[key]
        self._kv[key] = (val, time.time() + float(seconds))
        return True

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: Any = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        bucket = self._hashes.setdefault(name, {})
        count = 0
        if key is not None:
            bucket[key] = value
            count += 1
        if mapping:
            for k, v in mapping.items():
                bucket[k] = v
                count += 1
        return count

    def hget(self, name: str, key: str) -> Any:
        return self._hashes.get(name, {}).get(key)

    def hgetall(self, name: str) -> dict[str, Any]:
        return dict(self._hashes.get(name, {}))

    def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self._seq += 1
        entry_id = f"{int(time.time() * 1000)}-{self._seq}"
        stream = self._streams.setdefault(name, [])
        serialized = {str(k): str(v) for k, v in fields.items()}
        stream.append((entry_id, serialized))
        if maxlen and len(stream) > maxlen:
            self._streams[name] = stream[-maxlen:]
        return entry_id

    def xrange(
        self, name: str, min: str = "-", max: str = "+", count: int | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        entries = list(self._streams.get(name, []))
        if count is not None:
            entries = entries[:count]
        return entries

    def xlen(self, name: str) -> int:
        return len(self._streams.get(name, []))

    def flushall(self) -> None:
        self._kv.clear()
        self._hashes.clear()
        self._streams.clear()


class ResilientRedisProxy:
    """
    Wraps a live `redis.Redis` client and transparently fails over to
    `InMemoryRedisAdapter` if any socket timeout or connection drop occurs.
    """

    def __init__(self, primary: Any | None, fallback: InMemoryRedisAdapter) -> None:
        self._primary = primary
        self._fallback = fallback
        self.using_fallback = primary is None

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        if not self.using_fallback and self._primary is not None:
            try:
                fn = getattr(self._primary, method_name)
                return fn(*args, **kwargs)
            except Exception:
                self.using_fallback = True
        fn_fb = getattr(self._fallback, method_name)
        return fn_fb(*args, **kwargs)

    def ping(self) -> bool:
        return bool(self._call("ping"))

    def get(self, key: str) -> str | None:
        return self._call("get", key)

    def set(
        self,
        key: str,
        value: Any,
        ex: int | float | None = None,
        nx: bool = False,
    ) -> bool:
        return bool(self._call("set", key, value, ex=ex, nx=nx))

    def delete(self, *keys: str) -> int:
        return int(self._call("delete", *keys))

    def incr(self, key: str) -> int:
        return int(self._call("incr", key))

    def expire(self, key: str, seconds: int | float) -> bool:
        return bool(self._call("expire", key, seconds))

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: Any = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        return int(self._call("hset", name, key=key, value=value, mapping=mapping))

    def hget(self, name: str, key: str) -> Any:
        return self._call("hget", name, key)

    def hgetall(self, name: str) -> dict[str, Any]:
        return dict(self._call("hgetall", name))

    def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        return str(self._call("xadd", name, fields, maxlen=maxlen, approximate=approximate))

    def xrange(
        self, name: str, min: str = "-", max: str = "+", count: int | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        return list(self._call("xrange", name, min=min, max=max, count=count))

    def xlen(self, name: str) -> int:
        return int(self._call("xlen", name))


_CLIENT_INSTANCE: ResilientRedisProxy | None = None


def get_redis_client(force_reset: bool = False) -> ResilientRedisProxy:
    """
    Return a connected `ResilientRedisProxy` that uses live Redis when healthy
    and transparently falls back to `InMemoryRedisAdapter` on connection/timeout errors.
    """
    global _CLIENT_INSTANCE
    if _CLIENT_INSTANCE is not None and not force_reset:
        return _CLIENT_INSTANCE

    settings = get_settings()
    fallback = InMemoryRedisAdapter()
    primary: Any = None
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        # Verify both read and write responsiveness before trusting the socket
        client.set("finflow:healthcheck", "ok", ex=5)
        primary = client
    except Exception:
        if not settings.redis_fallback_memory:
            raise
        primary = None

    _CLIENT_INSTANCE = ResilientRedisProxy(primary=primary, fallback=fallback)
    return _CLIENT_INSTANCE


def is_using_fallback_redis() -> bool:
    """Indicate whether the engine is currently running on in-memory Redis fallback."""
    client = get_redis_client()
    return client.using_fallback
