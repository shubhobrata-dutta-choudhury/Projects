"""Agent-generated edge-case tests for LRUCacheTTL."""
import pytest
from lru_cache_ttl import LRUCacheTTL


def test_overwrite_updates_ttl_and_recency():
    cache = LRUCacheTTL(capacity=2, default_ttl=10.0)
    cache.put('k1', 'v1', now=0.0, ttl=5.0)
    cache.put('k1', 'v2', now=4.0, ttl=20.0)
    assert cache.get('k1', now=10.0) == 'v2'


def test_invalid_init_and_put_ttl():
    with pytest.raises(ValueError):
        LRUCacheTTL(capacity=0, default_ttl=10.0)
    cache = LRUCacheTTL(capacity=2, default_ttl=10.0)
    with pytest.raises(ValueError):
        cache.put('k', 'v', now=0.0, ttl=-1.0)