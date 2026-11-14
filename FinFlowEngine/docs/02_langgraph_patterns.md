# Advanced LangGraph Orchestration Patterns in `finflow-engine`

`finflow-engine` leverages state-of-the-art **LangGraph** orchestration paradigms to manage multi-agent financial workflows, parallel worker execution, human-in-the-gate interventions, and cyclical self-correction loops.

---

## 1. Core LangGraph Topologies
+-------------------+
                    |   START (Node)    |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    |   planner_node    |
                    +---------+---------+
                              | (Fan-Out: Send)
     +------------------------+------------------------+
     |                        |                        |
     v                        v                        v
+-----------------+      +-----------------+      +-----------------+
| analyze_asset   |      | analyze_asset   |      | analyze_asset   |
| [NVDA Worker]   |      | [MSFT Worker]   |      | [AAPL Worker]   |
+--------+--------+      +--------+--------+      +--------+--------+
|                        |                        |
+------------------------+------------------------+
| (Fan-In Aggregate)
v
+-------------------+
| risk_compliance   |
|      _gate        |
+---------+---------+
|
+--------------+--------------+ (Interrupt if Breach)
|                             |
v (Approved)                  v (Rejected -> END)
+-------------------+         +-------------------+
| synthesizer_node  |         |     end       |
+---------+---------+         +-------------------+
|
v
+-------------------+
|  critic_auditor   |
+---------+---------+
|
+--------+--------+ (Discrepancies found? Revision <= 3)
|                 |
v (Loop Back)     v (Grounded / Max Revisions)
+-------------------+   +-------------------+
| synthesizer_node  |   |      end      |
+-------------------+   +-------------------+


---

## 2. Key Orchestration Patterns Implemented

### A. Dynamic Fan-Out Map (`Send` API)
Instead of hardcoding a static number of asset analysis nodes, the Planner Agent dynamically inspects the user mandate and returns a list of LangGraph `Send` objects in `continue_to_asset_analysis(state)`:
```python
return [
    Send("analyze_asset", AssetSubTaskState(thread_id=thread_id, ticker=alloc["ticker"], ...))
    for alloc in allocations
]
This enables parallel execution of quantitative VaR calculations and SEC fundamental extraction across multiple tickers.

B. Human-in-the-Loop (HITL) Compliance Interrupts
When the Portfolio Risk & Compliance Gate (risk_compliance_gate_node) detects a Value-at-Risk breach, concentration limit violation, or OFAC sanctions match, it suspends execution using LangGraph's native interrupt() primitive:

Python
human_decision_payload = interrupt({
    "interrupt_type": "COMPLIANCE_GATE_REVIEW",
    "policy_violations": risk_report["policy_violations"],
    "weighted_portfolio_var_95_pct": risk_report["weighted_portfolio_var_95_pct"],
})
This pauses the workflow, persists all state into Redis via RedisBackedCheckpointSaver, and awaits an external REST API call (POST /api/v1/workflow/resume) with a LangGraph Command(resume=human_review) payload.

C. Cyclical Self-Correction Reflection Loop
The Critic & Hallucination Auditor (critic_auditor_node) cross-checks every numerical figure, spot price, VaR percentage, and SEC risk factor in the generated memo against ground-truth tool payloads. If discrepancies are detected and revision_count <= 3, the graph routes back to the synthesizer node for self-correction:

Python
def check_critic_reflection_routing(state: FinFlowState) -> Literal["synthesizer", "__end__"]:
    audit = state.get("critic_audit") or {}
    is_grounded = bool(audit.get("is_grounded", True))
    revision_count = int(state.get("revision_count", 1))
    
    if not is_grounded and revision_count <= 3:
        return "synthesizer"
    return END
