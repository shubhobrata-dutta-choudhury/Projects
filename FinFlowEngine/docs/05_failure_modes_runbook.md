# Operational Failure Modes & Troubleshooting Runbook (`finflow-engine`)

This runbook outlines operational failure modes, diagnostic procedures, and remediation steps for production deployments of `finflow-engine`.

---

## 1. Upstream LLM / API Rate Limiting & Circuit Breaker Tripping

### Symptoms
- Tool calls or agent generation requests failing with `TransientAgentError` (HTTP 429 Rate-Limit / Upstream Timeout).
- Log warnings: `[CircuitBreaker] Circuit for service 'llm-planner' transitioned from CLOSED to OPEN`.

### Root Cause
Upstream API rate limits exceeded or sustained provider outages triggering the `DistributedCircuitBreaker` failure threshold.

### Remediation Steps
1. Verify Redis connectivity and check current circuit state:
   ```bash
   redis-cli get finflow:cb:state:llm-planner
Inspect Redis DLQ for failed task payloads:

Bash
python -m finflow.api.cli dlq --count 20
If necessary, manually reset the circuit breaker state in Redis:

Bash
redis-cli del finflow:cb:state:llm-planner finflow:cb:failures:llm-planner
2. Redis Connection Drops & Fallback Activation
Symptoms
Log notice: [ResilientRedisProxy] Primary Redis connection failed. Falling back to InMemoryRedisAdapter.

Root Cause
Network partition between the application container and Redis Stack, or Redis server restart.

Remediation Steps
Check Redis service status:

Bash
redis-cli ping
Verify environment configuration (REDIS_URL in .env).

Note that the engine remains fully functional in local in-memory fallback mode for testing and stateless execution, but multi-instance coordination and durable checkpointing require live Redis Stack.

3. Critic Hallucination Detection & Reflection Loop Exhaustion
Symptoms
Workflow execution takes longer than expected or terminates after 3 revision cycles with ungrounded numbers.

Log warning: [CriticAuditor] Critical numerical audit failure. Routing back to synthesizer.

Root Cause
The Synthesizer Agent generated figures (e.g., spot price, VaR percentage) that drifted from ground-truth tool outputs.

Remediation Steps
Inspect the audit trail in the workflow result state to view specific discrepancies.

Check prompt versions in Langfuse to ensure strict prompt instructions (finflow-synthesizer-v4) are enforced.

Enable chaos_mode or review tool caching layers to verify fresh market data retrieval.

4. Human-in-the-Loop (HITL) Compliance Gate Interrupts
Symptoms
Workflow execution suspends and blocks at risk_compliance_gate.

API requests hang waiting for compliance officer sign-off.

Root Cause
Portfolio 95% daily VaR exceeded configured limits (max_portfolio_var_95_pct), single-asset concentration exceeded limits, or sanctions check matched restricted ticker.

Remediation Steps
Inspect policy violation messages in the suspended thread state.

Submit compliance review via the REST API to resume execution:

Bash
curl -X POST "http://localhost:8000/api/v1/workflow/resume" \
     -H "Content-Type: application/json" \
     -d '{"thread_id": "finflow-thread-abc12345", "decision": "APPROVE", "reviewer_id": "senior_risk_officer", "rationale": "Approved after portfolio risk review."}'
5. Redis Dead-Letter Queue (DLQ) Triage
Symptoms
Unhandled worker exceptions or orchestrator crashes caught by the runner.

Root Cause
Severe downstream errors or corrupt task states.

Remediation Steps
List DLQ entries via CLI:

Bash
python -m finflow.api.cli dlq
Inspect error stack traces and state snapshots in the DLQ stream to debug and deploy patches.
