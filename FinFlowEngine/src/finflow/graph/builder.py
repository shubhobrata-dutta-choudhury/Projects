"""
LangGraph StateGraph Workflow Builder for FinFlow-Engine.

Assembles the multi-agent graph topology:
planner -> [analyze_asset (Fan-Out Send)] -> risk_compliance_gate -> synthesizer -> critic_auditor -> (Loop or END)
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from finflow.agents.nodes import (
    analyze_asset_worker_node,
    critic_auditor_node,
    planner_node,
    risk_compliance_gate_node,
    synthesizer_node,
)
from finflow.resilience.checkpointer import get_checkpointer
from finflow.state.schemas import AssetSubTaskState, FinFlowState


def continue_to_asset_analysis(state: FinFlowState) -> list[Send]:
    """Dynamic fan-out router: dispatches `analyze_asset_worker_node` for each ticker."""
    allocations = state.get("allocations", [])
    thread_id = state.get("thread_id", "default-thread")
    macro_scenario = state.get("macro_scenario", "baseline")
    chaos_mode = bool(state.get("chaos_mode", False))

    return [
        Send(
            "analyze_asset",
            AssetSubTaskState(
                thread_id=thread_id,
                ticker=str(alloc["ticker"]),
                macro_scenario=macro_scenario,
                chaos_mode=chaos_mode,
            ),
        )
        for alloc in allocations
    ]


def check_critic_reflection_routing(state: FinFlowState) -> Literal["synthesizer", "__end__"]:
    """
    If the Critic Auditor finds discrepancies and revision count is within bounds,
    route back to `synthesizer` for self-correction. Otherwise, finish workflow.
    """
    audit = state.get("critic_audit") or {}
    is_grounded = bool(audit.get("is_grounded", True))
    revision_count = int(state.get("revision_count", 1))
    status = state.get("workflow_status", "")

    if status == "COMPLETED_REJECTED" or status == "COMPLETED_APPROVED":
        return END

    if not is_grounded and revision_count <= 3:
        return "synthesizer"
    return END


def check_compliance_routing(state: FinFlowState) -> Literal["synthesizer", "__end__"]:
    """If compliance gate rejected the trade, terminate workflow early."""
    risk_report = state.get("portfolio_risk") or {}
    status = risk_report.get("compliance_status", "APPROVED")
    if status == "REJECTED" or state.get("workflow_status") == "COMPLETED_REJECTED":
        return END
    return "synthesizer"


def build_finflow_graph() -> Any:
    """Compile and return the executable LangGraph workflow."""
    workflow = StateGraph(FinFlowState)

    # Add nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("analyze_asset", analyze_asset_worker_node)
    workflow.add_node("risk_compliance_gate", risk_compliance_gate_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("critic_auditor", critic_auditor_node)

    # Edges & Routing
    workflow.add_edge(START, "planner")
    workflow.add_conditional_edges("planner", continue_to_asset_analysis, ["analyze_asset"])
    workflow.add_edge("analyze_asset", "risk_compliance_gate")

    workflow.add_conditional_edges(
        "risk_compliance_gate",
        check_compliance_routing,
        {
            "synthesizer": "synthesizer",
            END: END,
        },
    )

    workflow.add_edge("synthesizer", "critic_auditor")

    workflow.add_conditional_edges(
        "critic_auditor",
        check_critic_reflection_routing,
        {
            "synthesizer": "synthesizer",
            END: END,
        },
    )

    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)


# Compiled global graph instance
compiled_graph = build_finflow_graph()
