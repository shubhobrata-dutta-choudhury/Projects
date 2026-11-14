# Langfuse Observability and Automated Evaluation Architecture in `finflow-engine`

`finflow-engine` integrates **Langfuse** for enterprise-grade LLM tracing, prompt version management, token cost accounting, and automated evaluation scoring.

---

## 1. Core Observability Components

### A. Langfuse Client & Tracer (`src/finflow/observability/langfuse_client.py`)
- Wraps the Langfuse Python SDK with robust fallback logging when offline.
- Manages root traces per thread (`thread_id`) and hierarchical child spans for each agent node (`planner`, `analyze_asset`, `risk_compliance_gate`, `synthesizer`, `critic_auditor`).

### B. Prompt Management Registry (`src/finflow/observability/prompt_registry.py`)
- Fetches versioned production prompts from Langfuse (`get_prompt`).
- Maintains local versioned fallback templates (`LOCAL_PROMPTS`) so agents operate reliably offline or during unit tests.

### C. Automated Evaluators & Score Reporting (`src/finflow/observability/evaluators.py`)
- Computes objective quality scores on every workflow run and reports them directly to Langfuse (`tracer.record_score(...)`):
  1. **`numerical_groundedness`** (0.0 - 1.0): Verifies that canonical spot prices, VaR figures, and SEC metrics cited in memos match exact tool outputs.
  2. **`compliance_gate_adherence`** (0.0 - 1.0): Tracks whether regulatory policy breaches correctly triggered Human-in-the-Loop review.
  3. **`resilience_recovery_health`** (0.0 - 1.0): Measures self-correction efficiency and retry recovery success.

---

## 2. Telemetry & Cost Accounting
Every LLM generation records:
- Input & output token counts
- Estimated USD cost based on model tiers (`primary_model` vs `fallback_model`)
- Prompt name and version tag
- Output preview snippets for auditability
