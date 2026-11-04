"""
Pillar 4: Deterministic Evaluation Metrics Calculator (`src/spec2code/evals/deterministic.py`).

Extracts objective, reproducible metrics from a completed `FSMContext`:
- `passed_at_1` ('Pass@1'): Did the initial code pass AST + all pytest tests without any repair loops?
- `passed_at_k` ('Pass@k'): Did the code converge to 100% passing tests within the allowed retry budget?
- `test_pass_rate`: Fraction of passing pytest cases
- Static quality telemetry: `type_hint_coverage`, `docstring_coverage`, `ast_valid`
"""

from __future__ import annotations

from spec2code.fsm.states import FSMContext, PipelineState
from spec2code.schemas.eval_schema import DeterministicEvalMetrics, SpecEvaluationReport


def compute_deterministic_metrics(ctx: FSMContext) -> DeterministicEvalMetrics:
    """
    Computes `DeterministicEvalMetrics` from the final `FSMContext` of a spec run.
    """
    sandbox = ctx.latest_sandbox_result
    ast_res = ctx.latest_ast_result

    passed_count = sandbox.passed_count if sandbox else 0
    failed_count = sandbox.failed_count if sandbox else 0
    total_tests = passed_count + failed_count
    pass_rate = round(passed_count / total_tests, 4) if total_tests > 0 else 0.0

    passed_at_k = ctx.current_state == PipelineState.COMPLETED and bool(sandbox and sandbox.all_passed)
    passed_at_1 = passed_at_k and ctx.first_attempt_passed and len(ctx.repair_history) == 0

    return DeterministicEvalMetrics(
        spec_id=ctx.spec.spec_id,
        passed_at_1=passed_at_1,
        passed_at_k=passed_at_k,
        total_attempts=max(1, ctx.attempt_number),
        repairs_triggered=len(ctx.repair_history),
        total_tests_passed=passed_count,
        total_tests_failed=failed_count,
        test_pass_rate=pass_rate,
        ast_valid=bool(ast_res and ast_res.passed),
        type_hint_coverage=ast_res.type_hint_coverage_ratio if ast_res else 0.0,
        docstring_coverage=ast_res.docstring_coverage_ratio if ast_res else 0.0,
        total_duration_ms=ctx.total_duration_ms,
    )


def build_spec_evaluation_report(ctx: FSMContext) -> SpecEvaluationReport:
    """
    Combines deterministic execution metrics, LLM-as-a-Judge rubric scores, and the FSM state trace
    into a unified `SpecEvaluationReport`.

    Composite Score Formula (0 - 100):
    - 60% weight: Deterministic execution score (`100.0 * test_pass_rate` if `passed_at_k` else `50.0 * test_pass_rate`)
    - 40% weight: LLM-as-a-Judge `weighted_overall_score` (0 - 100)
            
    """		
    det = compute_deterministic_metrics(ctx)
    assert ctx.judge_evaluation is not None, "FSMContext must have judge_evaluation before building report."

    det_score = (100.0 * det.test_pass_rate) if det.passed_at_k else (50.0 * det.test_pass_rate)
    composite = round(0.60 * det_score + 0.40 * ctx.judge_evaluation.weighted_overall_score, 2)

    transitions = [
        f"{t.from_state.value} -> {t.to_state.value} (Attempt #{t.attempt}: {t.reason})"
        for t in ctx.transition_history
    ]
    repairs = [
        f"Repair #{idx}: [Root Cause] {r.failure_root_cause} | [Fix] {r.fix_strategy}"
        for idx, r in enumerate(ctx.repair_history, start=1)
    ]

    return SpecEvaluationReport(
        spec_id=ctx.spec.spec_id,
        title=ctx.spec.title,
        difficulty=ctx.spec.difficulty,
        final_status=ctx.current_state.value,
        deterministic=det,
        llm_judge=ctx.judge_evaluation,
        state_transitions=transitions,
        repair_history_summaries=repairs,
        composite_score=composite,
    )