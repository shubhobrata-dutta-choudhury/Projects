"""
Integration tests for Pillar 2 (FSM Self-Correction Loop) & Pillar 4 (Deterministic + LLM-as-a-Judge Benchmark Suite).
"""

from __future__ import annotations

import pytest
from spec2code.config import PipelineConfig
from spec2code.evals.benchmark import BenchmarkRunner, render_markdown_benchmark_report
from spec2code.evals.deterministic import build_spec_evaluation_report
from spec2code.fsm.engine import SpecToCodeFSMEngine
from spec2code.fsm.states import FSMContext, PipelineState
from spec2code.ingest.parser import parse_spec_file


def test_fsm_rejects_illegal_state_transition() -> None:
    """Ensures FSMContext enforces the strict state transition graph."""
    spec = parse_spec_file("specs/03_interval_merger.json")
    ctx = FSMContext(spec=spec)
    with pytest.raises(ValueError, match="Invalid FSM transition"):
        # Cannot jump directly from INGEST_SPEC to COMPLETED
        ctx.transition_to(PipelineState.COMPLETED, reason="Illegal shortcut")


def test_fsm_self_correction_loop_repairs_rate_limiter() -> None:
    """
    Verifies that in educational mock mode (`simulate_bug_on_first_try=True`),
    `01_rate_limiter.json` fails on Attempt #1, routes through `DIAGNOSE_AND_REPAIR`,
    applies the surgical `SearchReplacePatch`, and converges to `COMPLETED` on Attempt #2.
    """
    spec = parse_spec_file("specs/01_rate_limiter.json")
    config = PipelineConfig(llm_provider="mock", max_retries=3, simulate_bug_on_first_try=True)
    engine = SpecToCodeFSMEngine(config=config)

    ctx = engine.run(spec)
    assert ctx.current_state == PipelineState.COMPLETED
    assert ctx.attempt_number == 2
    assert ctx.first_attempt_passed is False
    assert len(ctx.repair_history) == 1

    visited_states = [t.to_state for t in ctx.transition_history]
    assert PipelineState.DIAGNOSE_AND_REPAIR in visited_states

    report = build_spec_evaluation_report(ctx)
    assert report.deterministic.passed_at_1 is False
    assert report.deterministic.passed_at_k is True
    assert report.deterministic.test_pass_rate == 1.0
    assert report.llm_judge.weighted_overall_score == 100.0
    assert report.composite_score == 100.0


def test_full_benchmark_suite_and_report_generation() -> None:
    """
    Runs the full 3-spec benchmark suite (JSON + Markdown specs) and verifies:
    - `spec_03_interval_merger` passes on Attempt #1 (`Pass@1`)
    - `spec_01_rate_limiter` and `spec_02_lru_cache_ttl` recover via self-correction (`Pass@k = 100%`)
    - `self_correction_recovery_rate == 1.0`
    """
    config = PipelineConfig(llm_provider="mock", max_retries=3, simulate_bug_on_first_try=True)
    runner = BenchmarkRunner(config=config)

    suite = runner.run_suite(
        [
            "specs/01_rate_limiter.json",
            "specs/02_lru_cache_ttl.md",
            "specs/03_interval_merger.json",
        ]
    )

    assert suite.total_specs == 3
    assert suite.pass_at_1_rate == pytest.approx(1 / 3, rel=1e-2)
    assert suite.pass_at_k_rate == 1.0
    assert suite.self_correction_recovery_rate == 1.0
    assert suite.average_llm_judge_score == 100.0
    assert suite.average_composite_score == 100.0

    md = render_markdown_benchmark_report(suite)
    assert "# Autonomous Spec-to-Code Benchmark Report" in md
    assert "spec_01_rate_limiter" in md
    assert "spec_02_lru_cache_ttl" in md
    assert "spec_03_interval_merger" in md