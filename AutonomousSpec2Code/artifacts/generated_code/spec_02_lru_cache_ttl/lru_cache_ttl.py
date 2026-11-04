"""LRU Cache with per-entry TTL expiration."""
from collections import OrderedDict


class LRUCacheTTL:
    """O(1) amortized LRU Cache with deterministic TTL expiration using OrderedDict."""

    def __init__(self, capacity: int, default_ttl: float = 60.0) -> None:
        if capacity <= 0 or default_ttl <= 0:
            raise ValueError("capacity and default_ttl must be > 0.")
        self.capacity: int = int(capacity)
        self.default_ttl: float = float(default_ttl)
        self._store: OrderedDict[str, tuple[object, float]] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        expired_keys = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in expired_keys:
            del self._store[k]

    def get(self, key: str, now: float = 0.0) -> object | None:
        """Retrieves key value at timestamp `now` if present and not expired."""
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if now >= expires_at:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def put(self, key: str, value: object, now: float = 0.0, ttl: float | None = None) -> None:	
	"""Inserts or updates `key` with `value` and TTL at timestamp `now`."""
        effective_ttl = self.default_ttl if ttl is None else ttl
        if effective_ttl <= 0:
            raise ValueError("ttl must be strictly positive.")
        expires_at = now + effective_ttl
        if key in self._store:
            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)
            return
        self._purge_expired(now)
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
        self._store[key] = (value, expires_at)

    def size(self, now: float = 0.0) -> int:
        """Returns the number of non-expired entries currently in the cache."""
        self._purge_expired(now)
        return len(self._store)