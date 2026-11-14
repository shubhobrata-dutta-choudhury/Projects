# Redis Resilience, Caching, and Fault-Tolerance Architecture in `finflow-engine`

`finflow-engine` utilizes **Redis Stack** as its central nervous system for state persistence, distributed locking, fault isolation, caching, and stream-based event sourcing.

---

## 1. Resilience Patterns & Key Components

### A. Automatic In-Memory Fallback (`src/finflow/resilience/redis_client.py`)
To ensure high availability and frictionless local development or CI execution, the Redis client wraps live connections in `ResilientRedisProxy`. If a socket timeout or connection drop occurs, or if Redis is unreachable on startup, the engine transparently fails over to `InMemoryRedisAdapter` (a thread-safe, Redis-compatible in-process store supporting TTLs, hashes, sets, atomic INCR, and Redis Streams).

### B. Redis Cache-Aside Decorator (`src/finflow/resilience/cache.py`)
Deterministic quantitative calculations and SEC fundamental lookups are decorated with `@redis_cached_tool`:
- Hashes input arguments into a SHA-256 digest (`finflow:cache:<namespace>:<digest>`).
- Returns cached payloads with `_cache_hit = True` metadata for Langfuse telemetry.
- Bypasses cache when `chaos_mode=True` is requested to test retry recovery.

### C. Durable LangGraph Checkpointer (`src/finflow/resilience/checkpointer.py`)
`RedisBackedCheckpointSaver` wraps LangGraph's `MemorySaver` with synchronous and asynchronous write-through persistence into Redis hashes (`finflow:checkpoint:thread:<thread_id>`), allowing thread suspension, time-travel, and `interrupt()` resumption across distributed worker instances.

### D. Distributed Circuit Breaker (`src/finflow/resilience/circuit_breaker.py`)
Synchronizes circuit health (`CLOSED` -> `OPEN` -> `HALF_OPEN`) across processes via Redis keys. Prevents cascading failures when upstream LLM providers or market data feeds degrade by automatically routing to fallback models.

### E. Dead-Letter Queue (DLQ) & Event Bus (`src/finflow/resilience/dlq.py`)
- **Event Stream (`finflow:events:stream`)**: Appends real-time workflow lifecycle events.
- **DLQ Stream (`finflow:dlq:stream`)**: Captures unrecoverable workflow payloads for post-mortem inspection and automated replay.

### F. Idempotency & Distributed Locking (`src/finflow/resilience/idempotency.py`)
Protects against duplicate financial transaction submissions and redundant LLM executions using atomic Redis distributed locks (`SET NX EX`) and completed result caches (`finflow:idempotency:result:<key>`).
