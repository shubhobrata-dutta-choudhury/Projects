"""
Pillar 1 & 4: Strict Pydantic Schemas for Dual Evaluation (Deterministic + LLM-as-a-Judge) & Benchmarking.

Best Practice Demonstrated:
In LLM-as-a-Judge evaluations, forcing the model to generate `chain_of_thought_critique`
BEFORE emitting integer scores (`score_1_to_5`) significantly improves calibration and reliability.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class RubricDimensionScore(BaseModel):
    """
    A single dimension of the LLM-as-a-Judge rubric.
    """

    dimension: str = Field(..., description="Name of the rubric dimension (e.g., 'Spec & Constraint Compliance').")
    chain_of_thought_critique: str = Field(
        ...,
        min_length=10,
        description="Evidence-based analysis of the code for this dimension BEFORE assigning a score.",
    )
    score: int = Field(
        ...,
        ge=1,
        le=5,
        description="Integer score from 1 (Poor/Violates Spec) to 5 (Exemplary Production Quality).",
    )


class LLMJudgeEvaluation(BaseModel):
    """
    Structured output schema emitted by the LLM-as-a-Judge Evaluator.
    """

    spec_compliance: RubricDimensionScore = Field(
        ...,
        description="Did the implementation satisfy all entry points, edge cases, and architectural constraints?",
    )
    algorithmic_efficiency: RubricDimensionScore = Field(
        ...,
        description="Does the time and space complexity match the optimal target defined in SpecConstraints?",
    )
    code_readability_and_typing: RubricDimensionScore = Field(
        ...,
        description="Are variable names clear, functions modular, and Python type hints/docstrings complete?",
    )
    test_suite_quality: RubricDimensionScore = Field(
        ...,
        description="Did the agent write meaningful edge-case and boundary unit tests in test_agent_generated.py?",
    )
    executive_summary: str = Field(
        ...,
        min_length=15,
        description="Overall qualitative summary of strengths and remaining improvement opportunities.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def weighted_overall_score(self) -> float:
        """
        Computes a normalized 0.0 - 100.0 quality score from the four 1-5 rubric dimensions.
        Weights:
        - Spec Compliance: 35%
        - Algorithmic Efficiency: 30%
        - Code Readability & Typing: 20%
        - Test Suite Quality: 15%
        """
        raw = (
            self.spec_compliance.score * 0.35
            + self.algorithmic_efficiency.score * 0.30
            + self.code_readability_and_typing.score * 0.20
            + self.test_suite_quality.score * 0.15
        )
        # Convert 1..5 scale to 20..100 scale
        return round(raw * 20.0, 2)


class DeterministicEvalMetrics(BaseModel):
    """
    Objective, deterministic execution metrics collected during the FSM run.
    """

    spec_id: str = Field(..., description="Identifier of the evaluated specification.")
    passed_at_1: bool = Field(
        ...,
        description="Pass@1: True if the initial generated code passed both AST and all pytest suites on Attempt 1 (0 repairs).",
    )
    passed_at_k: bool = Field(
        ...,
        description="Pass@k: True if the code converged to 100% passing tests within the allowed retry budget.",
    )
    total_attempts: int = Field(..., ge=1, description="Total generation + repair attempts executed (1 = no repairs needed).")
    repairs_triggered: int = Field(..., ge=0, description="Number of self-correction repair loops executed.")
    total_tests_passed: int = Field(..., ge=0, description="Final count of passing pytest tests.")
    total_tests_failed: int = Field(..., ge=0, description="Final count of failing pytest tests.")
    test_pass_rate: float = Field(..., ge=0.0, le=1.0, description="Ratio of passing tests to total tests run.")
    ast_valid: bool = Field(..., description="True if final code passed all static AST security and syntax checks.")
    type_hint_coverage: float = Field(..., ge=0.0, le=1.0, description="Ratio of public functions with type hints.")
    docstring_coverage: float = Field(..., ge=0.0, le=1.0, description="Ratio of classes/functions with docstrings.")
    total_duration_ms: float = Field(..., ge=0.0, description="Total wall-clock time across all FSM states in ms.")


class SpecEvaluationReport(BaseModel):
    """
    Combined evaluation report for a single FeatureSpec run (Deterministic + LLM-as-a-Judge + FSM Trace).
    """

    spec_id: str
    title: str
    difficulty: str
    final_status: str = Field(..., description="'COMPLETED' or 'FAILED'")
    deterministic: DeterministicEvalMetrics
    llm_judge: LLMJudgeEvaluation
    state_transitions: list[str] = Field(
        default_factory=list,
        description="Ordered trace of FSM states visited (e.g. INGEST_SPEC -> GENERATE_CODE -> ...).",
    )
    repair_history_summaries: list[str] = Field(
        default_factory=list,
        description="Summaries of each bug diagnosed and fixed during self-correction.",
    )
    composite_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Combined score: 60% deterministic Pass/Test rate + 40% LLM-as-a-Judge rubric score.",
    )


class BenchmarkSuiteReport(BaseModel):
    """
    Aggregated benchmark results across multiple feature specifications.
    """

    total_specs: int
    pass_at_1_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of specs passing on first attempt.")
    pass_at_k_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of specs passing after self-correction.")
    self_correction_recovery_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of initially failing specs that were successfully repaired by the FSM loop.",
    )
    average_attempts_to_pass: float = Field(..., ge=0.0, description="Mean number of attempts for passing specs.")
    average_llm_judge_score: float = Field(..., ge=0.0, le=100.0, description="Mean LLM-as-a-Judge score (0-100).")
    average_composite_score: float = Field(..., ge=0.0, le=100.0, description="Mean composite score across all specs.")
    spec_reports: list[SpecEvaluationReport]