"""Auto-generated acceptance test suite for spec_02_lru_cache_ttl: LRU Cache with TTL Expiration."""
import pytest
import math
import time
from lru_cache_ttl import *

# [test_lru_eviction_and_recency] Verifies standard LRU eviction order when entries have not expired.
def test_lru_eviction_and_recency():
    """Verifies standard LRU eviction order when entries have not expired."""
    cache = LRUCacheTTL(capacity=2, default_ttl=100.0)
    cache.put("a", 1, now=0.0)
    cache.put("b", 2, now=1.0)
    assert cache.get("a", now=2.0) == 1  # 'a' is now most recently used
    cache.put("c", 3, now=3.0)           # 'b' should be evicted
    assert cache.get("b", now=4.0) is None
    assert cache.get("a", now=4.0) == 1
    assert cache.get("c", now=4.0) == 3

# [test_ttl_expiration_and_boundary] Verifies that an item expires at exact boundary now >= inserted + ttl.
def test_ttl_expiration_and_boundary():
    """Verifies that an item expires at exact boundary now >= inserted + ttl."""
    cache = LRUCacheTTL(capacity=2, default_ttl=10.0)
    cache.put("session", "xyz", now=5.0, ttl=10.0)
    assert cache.get("session", now=14.9) == "xyz"
    assert cache.get("session", now=15.0) is None
    assert cache.size(now=15.0) == 0

# [test_purge_expired_before_lru_eviction] Verifies that expired items are purged before evicting valid LRU items on put.
def test_purge_expired_before_lru_eviction():
    """Verifies that expired items are purged before evicting valid LRU items on put."""
    cache = LRUCacheTTL(capacity=2, default_ttl=10.0)
    cache.put("long_lived", "keep_me", now=0.0, ttl=100.0)
    cache.put("short_lived", "expire_me", now=1.0, ttl=5.0)
    # Access short_lived at t=2.0 so 'long_lived' becomes the oldest accessed item
    assert cache.get("short_lived", now=2.0) == "expire_me"
    # At t=10.0, 'short_lived' is expired (expired at 6.0). Inserting 'new_key' must NOT evict 'long_lived'!
    cache.put("new_key", "fresh", now=10.0, ttl=50.0)
    assert cache.get("long_lived", now=10.0) == "keep_me"
    assert cache.get("new_key", now=10.0) == "fresh"
    assert cache.size(now=10.0) == 2