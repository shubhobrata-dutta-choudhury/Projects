"""
Redis-backed resilience primitives for FinFlow-Engine:
- Durable LangGraph Checkpointing (Redis + Memory fallback)
- Distributed Circuit Breaker (CLOSED -> OPEN -> HALF_OPEN)
- Exponential Backoff with Full Jitter & Error Classification
- Distributed Idempotency Locks & Deduplication
- Deterministic Tool Output Cache
- Redis Streams Event Bus & Dead-Letter Queue (DLQ)
"""
