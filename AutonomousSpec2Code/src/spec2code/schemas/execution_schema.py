"""
Pillar 1 & 3: Strict Pydantic Schemas for AST Static Validation and Sandboxed Test Execution.

Models the structured outputs of:
- `ASTValidationResult`: Syntax validity, forbidden import/call violations, type-hint & docstring checks
- `SandboxExecutionResult`: Subprocess exit codes, pass/fail counts, duration, and structured failure summaries
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ASTViolation(BaseModel):
    """
    A single static analysis or security violation detected in generated Python code.
    """

    filepath: str = Field(..., description="File where the violation occurred.")
    line_number: int | None = Field(default=None, description="1-based line number of the issue, if applicable.")
    violation_type: str = Field(
        ...,
        description="Category of issue (e.g., 'SyntaxError', 'ForbiddenImport', 'ForbiddenCall', 'StyleWarning').",
    )
    message: str = Field(..., description="Detailed description of the violation.")
    is_blocking: bool = Field(
        default=True,
        description="If True, blocks sandbox execution and forces an immediate FSM transition to REPAIR_CODE.",
    )


class ASTValidationResult(BaseModel):
    """
    Aggregate result of running static AST analysis across all candidate Python files.
    """

    passed: bool = Field(..., description="True if no blocking AST violations were found.")
    violations: list[ASTViolation] = Field(default_factory=list, description="All blocking and non-blocking findings.")
    public_functions_count: int = Field(default=0, description="Number of public functions/methods inspected.")
    type_hint_coverage_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of public functions/methods that include return or parameter type annotations.",
    )
    docstring_coverage_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of classes and public functions/methods with docstrings.",
    )

    def format_feedback_for_llm(self) -> str:
        """
        Formats blocking AST errors into a clean prompt section for the Repair Agent.
        """
        if self.passed and not self.violations:
            return "AST Validation Passed with 0 violations."
        lines = ["AST Static Analysis Findings:"]
        for v in self.violations:
            prefix = "[BLOCKING]" if v.is_blocking else "[WARNING]"
            loc = f"{v.filepath}:{v.line_number}" if v.line_number else v.filepath
            lines.append(f"- {prefix} ({v.violation_type}) at {loc}: {v.message}")
        return "\n".join(lines)


class SandboxExecutionResult(BaseModel):
    """
    Structured output from running `pytest` inside the isolated temporary directory sandbox.
    """

    all_passed: bool = Field(..., description="True if exit_code == 0 and passed_count > 0 and failed_count == 0.")
    timed_out: bool = Field(default=False, description="True if execution exceeded the sandbox timeout limit.")
    exit_code: int = Field(..., description="Subprocess return code from pytest.")
    passed_count: int = Field(default=0, ge=0, description="Number of passing test cases.")
    failed_count: int = Field(default=0, ge=0, description="Number of failing or erroring test cases.")
    acceptance_passed: bool = Field(
        default=False,
        description="True if all spec-provided acceptance tests in test_acceptance.py passed.",
    )
    agent_tests_passed: bool = Field(
        default=False,
        description="True if all agent-generated tests in test_agent_generated.py passed.",
    )
    duration_ms: float = Field(..., ge=0.0, description="Wall-clock execution time in milliseconds.")
    stdout: str = Field(default="", description="Captured standard output from pytest.")
    stderr: str = Field(default="", description="Captured standard error from pytest.")
    failure_summary: str = Field(
        default="",
        description="Concise extracted traceback / assertion failure details for the FSM Repair Agent.",
    )