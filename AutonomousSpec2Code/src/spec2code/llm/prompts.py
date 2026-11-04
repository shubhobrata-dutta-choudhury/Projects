"""
System and User Prompt Templates for the three specialized Agent Personas:
1. Code Generator Agent (`CodeGenerationResponse`)
2. Self-Correction Debugger & Repair Agent (`RepairPatchResponse`)
3. Rubric-based LLM-as-a-Judge Evaluator (`LLMJudgeEvaluation`)
"""

from __future__ import annotations

import json
from spec2code.schemas.execution_schema import ASTValidationResult, SandboxExecutionResult
from spec2code.schemas.spec_schema import FeatureSpec

GENERATOR_SYSTEM_PROMPT = """You are a Principal Python Software Engineer in an Autonomous Spec-to-Code pipeline.
Your task is to synthesize clean, well-typed, well-documented Python implementation code and an accompanying pytest suite that strictly conforms to the provided FeatureSpec.

CRITICAL RULES:
1. You MUST respond ONLY with a valid JSON object matching the `CodeGenerationResponse` Pydantic schema.
2. Only import modules listed in `constraints.allowed_imports` inside the target implementation file.
3. Never use forbidden constructs (`eval`, `exec`, `open`, `os`, `subprocess`, `sys`).
4. Include complete Python type annotations and docstrings on all classes and public functions/methods.
5. In `agent_test_op`, create `test_agent_generated.py` with thorough boundary and edge-case tests.
"""

REPAIR_SYSTEM_PROMPT = """You are an Autonomous Python Debugging & Program Repair Agent operating inside a Finite State Machine loop.
Your previous code attempt failed either Static AST Verification or Sandboxed Pytest Execution.

CRITICAL RULES:
1. Analyze the exact AST violation or pytest traceback in `failure_root_cause`.
2. Formulate a minimal, surgical fix in `fix_strategy`.
3. Output a valid JSON object matching the `RepairPatchResponse` Pydantic schema.
4. Ensure all SpecConstraints (`allowed_imports`, `time_complexity`, `require_type_hints`, `require_docstrings`) remain satisfied.
"""

JUDGE_SYSTEM_PROMPT = """You are an impartial, Principal-level LLM-as-a-Judge Evaluator benchmarking autonomous code synthesis.
Evaluate the generated Python implementation and agent-generated test suite against the original FeatureSpec across 4 rubric dimensions:
1. `spec_compliance` (35% weight)
2. `algorithmic_efficiency` (30% weight)
3. `code_readability_and_typing` (20% weight)
4. `test_suite_quality` (15% weight)


CRITICAL CALIBRATION RULE:
For every rubric dimension, you MUST write a detailed, evidence-based `chain_of_thought_critique` citing specific functions, complexity behaviors, or edge cases BEFORE assigning an integer `score` from 1 to 5.
Respond ONLY with a valid JSON object matching the `LLMJudgeEvaluation` Pydantic schema.
"""


def build_generation_user_prompt(spec: FeatureSpec, schema_json: dict) -> str:
    return (
        f"### FEATURE SPECIFICATION\n"
        f"{spec.model_dump_json(indent=2)}\n\n"
        f"### REQUIRED OUTPUT JSON SCHEMA ('CodeGenerationResponse')\n"
        f"{json.dumps(schema_json, indent=2)}\n"
    )


def build_repair_user_prompt(
    spec: FeatureSpec,
    current_files: dict[str, str],
    ast_result: ASTValidationResult | None,
    sandbox_result: SandboxExecutionResult | None,
    attempt_number: int,
    schema_json: dict,
) -> str:
    files_dump = "\n\n".join(
        f"--- FILE: {fname} ---\n```python\n{content}\n```"
        for fname, content in current_files.items()
    )
    ast_feedback = ast_result.format_feedback_for_llm() if ast_result else "Not run."
    sandbox_feedback = (
        f"Exit Code: {sandbox_result.exit_code} | Passed: {sandbox_result.passed_count} | Failed: {sandbox_result.failed_count}\n"
        f"Failure Summary:\n{sandbox_result.failure_summary}"
        if sandbox_result
        else "Sandbox not executed due to blocking AST error."
    )

    return (
        f"### SELF-CORRECTION REPAIR ATTEMPT #{attempt_number}\n"
        f"Spec ID: {spec.spec_id} ({spec.title})\n"
        f"Target Filename: {spec.target_filename}\n"
        f"Constraints: {spec.constraints.model_dump_json()}\n\n"
        f"### CURRENT WORKSPACE FILES\n{files_dump}\n\n"
        f"### DIAGNOSTIC FEEDBACK\n"
        f"1. {ast_feedback}\n\n"
        f"2. Sandbox Pytest Feedback:\n{sandbox_feedback}\n\n"
        f"### REQUIRED OUTPUT JSON SCHEMA ('RepairPatchResponse')\n"
        f"{json.dumps(schema_json, indent=2)}\n"
    )


def build_judge_user_prompt(
    spec: FeatureSpec,
    final_files: dict[str, str],
    ast_result: ASTValidationResult,
    sandbox_result: SandboxExecutionResult | None,
    schema_json: dict,
) -> str:
    impl_code = final_files.get(spec.target_filename, "")
    agent_tests = final_files.get("test_agent_generated.py", "")
    test_summary = (
        f"All Passed: {sandbox_result.all_passed}, Passed: {sandbox_result.passed_count}, Failed: {sandbox_result.failed_count}"
        if sandbox_result
        else "Sandbox did not run."
    )
    return (
        f"### FEATURE SPECIFICATION\n{spec.model_dump_json(indent=2)}\n\n"
        f"### GENERATED IMPLEMENTATION ('{spec.target_filename}')\n```python\n{impl_code}\n```\n\n"
        f"### AGENT-GENERATED UNIT TESTS ('test_agent_generated.py')\n```python\n{agent_tests}\n```\n\n"
        f"### DETERMINISTIC TELEMETRY\n"
        f"- AST Valid: {ast_result.passed}\n"
        f"- Type Hint Coverage: {ast_result.type_hint_coverage_ratio:.0%}\n"
        f"- Docstring Coverage: {ast_result.docstring_coverage_ratio:.0%}\n"
        f"- Sandbox Test Execution: {test_summary}\n\n"
        f"### REQUIRED OUTPUT JSON SCHEMA ('LLMJudgeEvaluation')\n"
        f"{json.dumps(schema_json, indent=2)}\n"
    )