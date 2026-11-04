"""
Pillar 2: Finite State Machine (FSM) State Definitions & Execution Context (`src/spec2code/fsm/states.py`).

Why use an explicit FSM instead of a simple `while` loop?
1. Deterministic Transition Rules: Only valid state transitions (defined in `ALLOWED_TRANSITIONS`) are permitted.
2. Full Observability & Auditability: Every state transition records a `StateTransitionRecord` with timing,
   attempt count, and transition reason-making debugging agent behavior transparent.
3. Separation of Static vs. Dynamic Failure Loops: If `STATIC_AST_CHECK` fails, the FSM transitions directly
   to `DIAGNOSE_AND_REPAIR` without wasting time or risking security in `EXECUTE_SANDBOX_TESTS`.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field
from spec2code.schemas.code_ops_schema import RepairPatchResponse
from spec2code.schemas.eval_schema import LLMJudgeEvaluation
from spec2code.schemas.execution_schema import ASTValidationResult, SandboxExecutionResult
from spec2code.schemas.spec_schema import FeatureSpec


class PipelineState(str, Enum):
    """
    Discrete states of the Autonomous Spec-to-Code Finite State Machine.
    """

    INGEST_SPEC = "INGEST_SPEC"
    GENERATE_CODE = "GENERATE_CODE"
    STATIC_AST_CHECK = "STATIC_AST_CHECK"
    EXECUTE_SANDBOX_TESTS = "EXECUTE_SANDBOX_TESTS"
    DIAGNOSE_AND_REPAIR = "DIAGNOSE_AND_REPAIR"
    EVALUATE_QUALITY = "EVALUATE_QUALITY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    PipelineState.INGEST_SPEC: {PipelineState.GENERATE_CODE, PipelineState.FAILED},
    PipelineState.GENERATE_CODE: {PipelineState.STATIC_AST_CHECK, PipelineState.FAILED},
    PipelineState.STATIC_AST_CHECK: {
        PipelineState.EXECUTE_SANDBOX_TESTS,
        PipelineState.DIAGNOSE_AND_REPAIR,
        PipelineState.EVALUATE_QUALITY,
    },
    PipelineState.EXECUTE_SANDBOX_TESTS: {
        PipelineState.EVALUATE_QUALITY,
        PipelineState.DIAGNOSE_AND_REPAIR,
    },
    PipelineState.DIAGNOSE_AND_REPAIR: {
        PipelineState.STATIC_AST_CHECK,
        PipelineState.EVALUATE_QUALITY,
        PipelineState.FAILED,
    },
    PipelineState.EVALUATE_QUALITY: {
        PipelineState.COMPLETED,
        PipelineState.FAILED,
    },
    PipelineState.COMPLETED: set(),
    PipelineState.FAILED: set(),
}


class StateTransitionRecord(BaseModel):
    """
    Audit log entry capturing a single transition in the FSM.
    """

    from_state: PipelineState
    to_state: PipelineState
    attempt: int
    reason: str
    duration_ms: float = 0.0


class FSMContext(BaseModel):
    """
    Mutable state container carried across the Finite State Machine lifecycle for a single spec run.
    """

    spec: FeatureSpec
    current_state: PipelineState = PipelineState.INGEST_SPEC
    attempt_number: int = 0
    max_retries: int = 3
    workspace_files: dict[str, str] = Field(default_factory=dict)
    architectural_plan: str = ""
    latest_ast_result: ASTValidationResult | None = None
    latest_sandbox_result: SandboxExecutionResult | None = None
    first_attempt_passed: bool = False
    repair_history: list[RepairPatchResponse] = Field(default_factory=list)
    transition_history: list[StateTransitionRecord] = Field(default_factory=list)
    judge_evaluation: LLMJudgeEvaluation | None = None
    total_duration_ms: float = 0.0

    def transition_to(self, next_state: PipelineState, reason: str, duration_ms: float = 0.0) -> None:
        """
        Validates and records a state transition in the FSM.
        Raises `ValueError` if the transition violates `ALLOWED_TRANSITIONS`.
        """
        allowed = ALLOWED_TRANSITIONS.get(self.current_state, set())
        if next_state not in allowed:
            raise ValueError(
                f"Invalid FSM transition: {self.current_state.value} -> {next_state.value}. "
                f"Allowed targets: {[s.value for s in allowed]}"
            )
        self.transition_history.append(
            StateTransitionRecord(
                from_state=self.current_state,
                from_state=self.current_state,
                to_state=next_state,
                attempt=self.attempt_number,
                reason=reason,
                duration_ms=round(duration_ms, 2),
            )
        )
        self.current_state = next_state