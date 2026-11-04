"""
Pillar 2: Finite State Machine (FSM) Orchestrator (`src/spec2code/fsm/engine.py`).

Executes the deterministic state graph for a `FeatureSpec`:
1. `INGEST_SPEC` -> Compiles the spec's acceptance tests into `test_acceptance.py`
2. `GENERATE_CODE` -> Invokes the Generator Agent to produce `CodeGenerationResponse`
3. `STATIC_AST_CHECK` -> Validates syntax, security policy, and type-hint/docstring telemetry
   - On blocking AST violation: transitions directly to `DIAGNOSE_AND_REPAIR` (if retry budget remains)
   - On AST pass: transitions to `EXECUTE_SANDBOX_TESTS`
4. `EXECUTE_SANDBOX_TESTS` -> Runs isolated `pytest` subprocess
   - On 100% pass: transitions to `EVALUATE_QUALITY`
   - On test failure: transitions to `DIAGNOSE_AND_REPAIR` (if retry budget remains) or `EVALUATE_QUALITY`
5. `DIAGNOSE_AND_REPAIR` -> Invokes the Repair Agent with tracebacks/AST violations, applies `FileModification` patches,
   and transitions back to `STATIC_AST_CHECK`
6. `EVALUATE_QUALITY` -> Runs LLM-as-a-Judge rubric evaluation and transitions to terminal state (`COMPLETED` or `FAILED`).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from spec2code.config import PipelineConfig
from spec2code.fsm.states import FSMContext, PipelineState
from spec2code.llm.client import StructuredLLMClient
from spec2code.sandbox.ast_guard import validate_code_ast
from spec2code.sandbox.runner import SandboxRunner
from spec2code.schemas.spec_schema import FeatureSpec


class SpecToCodeFSMEngine:
    """
    Finite State Machine engine that drives autonomous code generation, sandbox verification,
    self-correction loops, and quality evaluation.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        llm_client: StructuredLLMClient | None = None,
        sandbox_runner: SandboxRunner | None = None,
        on_transition: Callable[[FSMContext], None] | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.llm_client = llm_client or StructuredLLMClient(self.config)
        self.sandbox_runner = sandbox_runner or SandboxRunner(
            timeout_seconds=self.config.sandbox_timeout_seconds
        )
        self.on_transition = on_transition

    def run(self, spec: FeatureSpec, artifacts_dir: Path | None = None) -> FSMContext:
        """
        Executes the FSM loop until a terminal state ('COMPLETED' or 'FAILED') is reached.
        """
        ctx = FSMContext(
            spec=spec,
            current_state=PipelineState.INGEST_SPEC,
            max_retries=self.config.max_retries,
        )
        pipeline_start = time.perf_counter()

        while ctx.current_state not in (PipelineState.COMPLETED, PipelineState.FAILED):
            state_start = time.perf_counter()

            if ctx.current_state == PipelineState.INGEST_SPEC:
                self._handle_ingest_spec(ctx, state_start)

            elif ctx.current_state == PipelineState.GENERATE_CODE:
                self._handle_generate_code(ctx, state_start)

            elif ctx.current_state == PipelineState.STATIC_AST_CHECK:
                self._handle_static_ast_check(ctx, state_start)

            elif ctx.current_state == PipelineState.EXECUTE_SANDBOX_TESTS:
                self._handle_execute_sandbox_tests(ctx, state_start, artifacts_dir)

            elif ctx.current_state == PipelineState.DIAGNOSE_AND_REPAIR:
                self._handle_diagnose_and_repair(ctx, state_start)

            elif ctx.current_state == PipelineState.EVALUATE_QUALITY:
                self._handle_evaluate_quality(ctx, state_start)

            if self.on_transition is not None:
                self.on_transition(ctx)

        ctx.total_duration_ms = round((time.perf_counter() - pipeline_start) * 1000.0, 2)
        return ctx

    def _handle_ingest_spec(self, ctx: FSMContext, state_start: float) -> None:
        acceptance_test_source = ctx.spec.render_acceptance_pytest_file()
        ctx.workspace_files["test_acceptance.py"] = acceptance_test_source
        elapsed = (time.perf_counter() - state_start) * 1000.0
        ctx.transition_to(
            PipelineState.GENERATE_CODE,
            reason=f"Ingested '{ctx.spec.spec_id}' and compiled {len(ctx.spec.acceptance_tests)} acceptance tests.",
            duration_ms=elapsed,
        )

    def _handle_generate_code(self, ctx: FSMContext, state_start: float) -> None:
        ctx.attempt_number = 1
        gen_response = self.llm_client.generate_initial_code(ctx.spec)
        ctx.architectural_plan = gen_response.architectural_plan

        # Apply structured file operations
        ctx.workspace_files[gen_response.implementation_op.filepath] = gen_response.implementation_op.apply()
        ctx.workspace_files[gen_response.agent_test_op.filepath] = gen_response.agent_test_op.apply()

        elapsed = (time.perf_counter() - state_start) * 1000.0
        ctx.transition_to(
            PipelineState.STATIC_AST_CHECK,
            reason=f"Generated initial '{ctx.spec.target_filename}' and 'test_agent_generated.py' (Attempt #1).",
            duration_ms=elapsed,
        )

    def _handle_static_ast_check(self, ctx: FSMContext, state_start: float) -> None:
        ast_result = validate_code_ast(
            files=ctx.workspace_files,
            constraints=ctx.spec.constraints,
            target_filename=ctx.spec.target_filename,
        )
        ctx.latest_ast_result = ast_result
        elapsed = (time.perf_counter() - state_start) * 1000.0

        if ast_result.passed:
            ctx.transition_to(
                PipelineState.EXECUTE_SANDBOX_TESTS,
                reason=(
                    f"AST validation passed (Type hints: {ast_result.type_hint_coverage_ratio:.0%}, "
                    f"Docstrings: {ast_result.docstring_coverage_ratio:.0%})."
                ),
                duration_ms=elapsed,
            )
            return

        # Blocking AST violation detected
        repairs_used = ctx.attempt_number - 1
        if repairs_used < ctx.max_retries:
            ctx.transition_to(
                PipelineState.DIAGNOSE_AND_REPAIR,
                reason=f"Blocking AST violation detected on Attempt #{ctx.attempt_number}; routing directly to repair.",
                duration_ms=elapsed,
            )
        else:
            ctx.transition_to(
                PipelineState.EVALUATE_QUALITY,
                reason=f"Blocking AST violation persisted and max_retries ({ctx.max_retries}) exhausted.",
                duration_ms=elapsed,
            )

    def _handle_execute_sandbox_tests(
        self,
        ctx: FSMContext,
        state_start: float,
        artifacts_dir: Path | None,
    ) -> None:
	
		persist_target = (artifacts_dir / ctx.spec.spec_id) if artifacts_dir else None
			sandbox_result = self.sandbox_runner.run_pytest_sandbox(
				files=ctx.workspace_files,
				persist_dir=persist_target,
			)
			ctx.latest_sandbox_result = sandbox_result
			elapsed = (time.perf_counter() - state_start) * 1000.0

			if sandbox_result.all_passed:
				if ctx.attempt_number == 1:
					ctx.first_attempt_passed = True
				ctx.transition_to(
					PipelineState.EVALUATE_QUALITY,
					reason=f"All {sandbox_result.passed_count} sandbox pytest tests passed on Attempt #{ctx.attempt_number}!",
					duration_ms=elapsed,
				)
				return

			repairs_used = ctx.attempt_number - 1
			if repairs_used < ctx.max_retries:
				ctx.transition_to(
					PipelineState.DIAGNOSE_AND_REPAIR,
					reason=(
						f"Sandbox tests failed ({sandbox_result.failed_count} failed, "
						f"{sandbox_result.passed_count} passed) on Attempt #{ctx.attempt_number}."
					),
					duration_ms=elapsed,
				)
			else:
				ctx.transition_to(
					PipelineState.EVALUATE_QUALITY,
					reason=f"Sandbox tests failed and retry budget ({ctx.max_retries}) exhausted.",
					duration_ms=elapsed,
				)

		def _handle_diagnose_and_repair(self, ctx: FSMContext, state_start: float) -> None:
			ctx.attempt_number += 1
			repair_response = self.llm_client.generate_repair_patch(
				spec=ctx.spec,
				current_files=ctx.workspace_files,
				ast_result=ctx.latest_ast_result,
				sandbox_result=ctx.latest_sandbox_result,
				attempt_number=ctx.attempt_number,
			)
			ctx.repair_history.append(repair_response)

        # Apply structured modifications (patch or overwrite)
        for mod in repair_response.modifications:
            existing = ctx.workspace_files.get(mod.filepath)
            ctx.workspace_files[mod.filepath] = mod.apply(existing_content=existing)

        elapsed = (time.perf_counter() - state_start) * 1000.0
        ctx.transition_to(
            PipelineState.STATIC_AST_CHECK,
            reason=f"Applied {len(repair_response.modifications)} repair patch(es) for Attempt #{ctx.attempt_number}.",
            duration_ms=elapsed,
        )

    def _handle_evaluate_quality(self, ctx: FSMContext, state_start: float) -> None:
        assert ctx.latest_ast_result is not None
        judge_eval = self.llm_client.evaluate_with_judge(
            spec=ctx.spec,
            final_files=ctx.workspace_files,
            ast_result=ctx.latest_ast_result,
            sandbox_result=ctx.latest_sandbox_result,
        )
        ctx.judge_evaluation = judge_eval
        elapsed = (time.perf_counter() - state_start) * 1000.0

        converged = bool(
            ctx.latest_ast_result.passed
            and ctx.latest_sandbox_result is not None
            and ctx.latest_sandbox_result.all_passed
        )
        terminal_state = PipelineState.COMPLETED if converged else PipelineState.FAILED
        ctx.transition_to(
            terminal_state,
            reason=(
                f"Evaluation complete (LLM-as-a-Judge score: {judge_eval.weighted_overall_score}/100, "
                f"Terminal status: {terminal_state.value})."
            ),
            duration_ms=elapsed,
        )