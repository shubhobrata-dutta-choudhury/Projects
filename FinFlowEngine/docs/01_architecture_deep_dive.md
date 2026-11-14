# Architecture Deep Dive: Resilient Multi-Agent Financial Workflow Engine (`finflow-engine`)

`finflow-engine` is an enterprise-grade, fault-tolerant multi-agent financial orchestration framework built on **LangGraph**, **Langfuse**, **Redis Stack**, and **FastAPI**. It is designed to execute institutional due diligence mandates, risk simulations, and SEC filing extractions with zero single points of failure.

---

## 1. System Architecture Overview
+-------------------------+
                      |   FastAPI / CLI Entry   |
                      +------------+------------+
                                   |
                                   v
                      +-------------------------+
                      |      Runner & Graph     |
                      +------------+------------+
                                   |
               +-------------------+-------------------+
               |                   |                   |
               v                   v                   v
       +---------------+   +---------------+   +---------------+
       | Planner Agent |   | Asset Workers |   | Compliance    |
       | (LangGraph)   |   | (Map / Send)  |   | Gate (HITL)   |
       +---------------+   +---------------+   +---------------+
               ^                   |                   |
               |                   v                   v
               |           +---------------+   +---------------+
               |           | Tools: Quant  |   | Synthesizer & |
               |           | & SEC Filings |   | Critic Auditor|
               |           +---------------+   +---------------+
               |                   |                   |
               +-------------------+-------------------+
                                   |
                                   v
                +-------------------------------------+
                |   Redis Resiliency & Observability  |
                |   - Redis-backed Checkpointer       |
                |   - Distributed Circuit Breakers    |
                |   - Idempotency & Distributed Locks |
                |   - Redis Streams DLQ & Event Bus   |
                |   - Langfuse Tracing & Telemetry    |
                +-------------------------------------+
---

## 2. Core Architectural Layers

### A. Root Infrastructure & Configuration (`src/finflow/config.py`)
- Centralized settings via **Pydantic-Settings** (`FinFlowSettings`) reading from environment variables and `.env` files.
- Configures Redis connection strings, primary/fallback LLM models, Langfuse API keys, cache TTLs, and risk thresholds.

### B. State Management (`src/finflow/state/`)
- **`FinFlowState`**: TypedDict maintaining global workflow context (`user_query`, `allocations`, `quant_reports`, `fundamental_reports`, `portfolio_risk`, `draft_memo`, `final_memo`, `revision_count`, `critic_audit`, `human_review`).
- **`make_audit_entry`**: Structured audit trail appending function for governance compliance.

### C. Resiliency & Fault Tolerance Layer (`src/finflow/resilience/`)
1. **`redis_client.py`**: Resilient connection manager with automated failover to `InMemoryRedisAdapter` when live Redis Stack is unreachable, ensuring local unit tests and offline runs execute smoothly.
2. **`cache.py`**: Cache-aside decorator (`@redis_cached_tool`) caching deterministic market data and SEC fundamentals in Redis with configurable TTLs.
3. **`checkpointer.py`**: Durable `RedisBackedCheckpointSaver` wrapping LangGraph's `MemorySaver` with write-through persistence into Redis hashes and metadata indices.
4. **`circuit_breaker.py`**: Distributed circuit breaker (`CLOSED` -> `OPEN` -> `HALF_OPEN`) synchronized across worker processes via Redis keys.
5. **`dlq.py`**: Redis Streams event bus (`finflow:events:stream`) and Dead-Letter Queue (`finflow:dlq:stream`) capturing unrecoverable failures.
6. **`idempotency.py`**: Atomic distributed execution locks (`SET NX EX`) and completed result caching to prevent duplicate workflow runs.
7. **`retry_policy.py`**: AWS-style Full Jitter exponential backoff with error classification (`TransientAgentError` vs `FatalWorkflowError`).

### D. Quantitative & Financial Tools (`src/finflow/tools/`)
- **`market_data.py`**: Computes parametric 1-day 95% VaR, Expected Shortfall (CVaR), Sharpe/Sortino ratios, and macroeconomic stress loss.
- **`sec_filings.py`**: Extracts balance sheet ratios, P/E multiples, debt-to-equity, and SEC 10-K key risk factors.
- **`portfolio_sim.py`**: Aggregates portfolio VaR, correlation diversification benefits, and compliance gate status.
- **`chaos_injector.py`**: Simulates transient upstream HTTP 429/503 errors and LLM outages for resilience testing.

### E. Multi-Agent Orchestration (`src/finflow/agents/` & `src/finflow/graph/`)
- **Planner Agent**: Decomposes mandate queries into ticker allocation plans.
- **Asset Worker Agents**: Parallel fan-out map execution (`Send`) running quantitative and fundamental analysis per ticker.
- **Risk & Compliance Gatekeeper**: Evaluates portfolio risk limits and triggers native LangGraph `interrupt()` for Human-in-the-Loop review upon breach.
- **Synthesizer Agent**: Compiles executive investment committee memos.
- **Critic & Hallucination Auditor**: Cross-checks all numbers and risk factors against ground-truth tool payloads, triggering self-correction reflection loops if discrepancies are found.
