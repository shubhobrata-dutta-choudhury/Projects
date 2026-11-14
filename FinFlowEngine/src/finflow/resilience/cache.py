"""
Redis Cache-Aside Decorator for Financial Domain Tools.

Caches deterministic market data and SEC fundamental lookups in Redis with
configurable market-aware TTLs, returning `(result, cache_hit_bool)` metadata
for Langfuse telemetry.
"""

from __future__ import annotations

import functools
import hashlib
import json
from typing import Any, Callable

from finflow.config import get_settings
from finflow.resilience.redis_client import get_redis_client


def redis_cached_tool(namespace: str, ttl_seconds: int | None = None) -> Callable[..., Any]:
    """
    Decorator that caches JSON-serializable tool outputs in Redis under
    `finflow:cache:<namespace>:<sha256_args>`.

    Note: If `chaos_mode=True` is passed in kwargs, caching is bypassed so fault
    injection and retry recovery can be tested deterministically.
    """

    def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            chaos_mode = bool(kwargs.get("chaos_mode", False))
            redis_client = get_redis_client()
            settings = get_settings()
            ttl = ttl_seconds or settings.cache_ttl_seconds

            key_material = json.dumps(
                {"args": args, "kwargs": {k: v for k, v in sorted(kwargs.items()) if k != "chaos_mode"}},
                sort_keys=True,
                default=str,
            )
            digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:20]
            cache_key = f"finflow:cache:{namespace}:{digest}"

            if not chaos_mode:
                cached_raw = redis_client.get(cache_key)
                if cached_raw:
                    try:
                        data = json.loads(cached_raw)
                        if isinstance(data, dict):
                            data["_cache_hit"] = True
                            return data
                    except Exception:
                        pass

            result = fn(*args, **kwargs)
            if isinstance(result, dict):
                to_cache = dict(result)
                to_cache.pop("_cache_hit", None)
                redis_client.set(cache_key, json.dumps(to_cache), ex=ttl)
                result["_cache_hit"] = False
            return result

        return wrapper

    return decorator
