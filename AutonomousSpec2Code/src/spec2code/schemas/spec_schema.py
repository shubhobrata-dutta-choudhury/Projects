"""
Pillar 1: Strict Pydantic Schemas for Feature Specifications.

Defines the structured contract for feature specs ingested from either JSON or Markdown.
Every spec must clearly declare:
- What file to generate (`target_filename`)
- What interfaces/signatures are required (`requirements`)
- What architectural/complexity constraints apply (`constraints`)
- Executable acceptance tests (`acceptance_tests`) that the sandbox will run
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class AcceptanceTestCase(BaseModel):
    """
    Represents a deterministic acceptance test defined in the specification.
    """

    test_id: str = Field(..., min_length=1, description="Unique identifier for the test case (e.g., 'test_basic_limit').")
    description: str = Field(..., min_length=3, description="Human-readable explanation of what this test verifies.")
    test_code: str = Field(
        ...,
        min_length=10,
        description="Valid Python pytest function or assertion block to verify the requirement.",
    )

    @field_validator("test_code")
    @classmethod
    def ensure_test_function_or_assert(cls, v: str) -> str:
        stripped = v.strip()
        if "assert " not in stripped and "pytest.raises" not in stripped:
            raise ValueError("acceptance test_code must contain at least one 'assert' statement or 'pytest.raises' check.")
        return stripped


class SpecConstraints(BaseModel):
    """
    Non-functional and architectural constraints that both the AST Guard and LLM-as-a-Judge verify.
    """

    time_complexity: str = Field(
        default="Not specified",
        description="Expected Big-O time complexity (e.g., 'O(1) amortized per operation').",
    )
    space_complexity: str = Field(
        default="Not specified",
        description="Expected Big-O space complexity (e.g., 'O(N) where N is capacity').",
    )
    allowed_imports: list[str] = Field(
        default_factory=lambda: ["typing", "dataclasses", "collections", "time", "math", "heapq", "enum", "functools", "itertools"],
        description="Standard library modules permitted in the generated implementation.",
    )
    forbidden_constructs: list[str] = Field(
        default_factory=lambda: ["eval", "exec", "os.system", "subprocess", "open"],
        description="Constructs or calls strictly forbidden in the implementation.",
    )
    require_type_hints: bool = Field(
        default=True,
        description="Whether all public functions/methods must include Python type annotations.",
    )
    require_docstrings: bool = Field(
        default=True,
        description="Whether classes and public functions must include descriptive docstrings.",
    )


class FeatureSpec(BaseModel):
    """
    Canonical representation of a Feature Specification after parsing from JSON or Markdown.
    """

    spec_id: str = Field(..., min_length=2, description="Unique identifier for the specification (e.g. 'spec_01_rate_limiter').")
    title: str = Field(..., min_length=3, description="Human-readable title of the feature.")
    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium",
        description="Difficulty tier used for benchmarking breakdowns.",
    )
    description: str = Field(..., min_length=10, description="Detailed problem statement and behavioral specification.")
    target_filename: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_]+\.py$",
        description="Target Python module filename to generate (must be a valid .py module identifier).",
    )
    entry_points: list[str] = Field(
        ...,
        min_length=1,
        description="List of required function or class signatures (e.g., 'class TokenBucketRateLimiter:').",
    )
    edge_cases: list[str] = Field(
        default_factory=list,
        description="Specific edge cases the implementation must handle properly.",
    )
    constraints: SpecConstraints = Field(
        default_factory=SpecConstraints,
        description="Complexity, library, and style constraints.",
    )
    acceptance_tests: list[AcceptanceTestCase] = Field(
        ...,
        min_length=1,
        description="List of deterministic acceptance tests that must pass in the sandbox.",
    )

    def render_acceptance_pytest_file(self) -> str:
        """
        Compiles all `acceptance_tests` into a standalone pytest file (`test_acceptance.py`)
        that imports everything from `target_filename`.
        """
        module_name = self.target_filename[:-3]
        lines = [
            f'"""Auto-generated acceptance test suite for {self.spec_id}: {self.title}."""',
            "import pytest",
            "import math",
            "import time",
            f"from {module_name} import *",
            "",
        ]
        for idx, tc in enumerate(self.acceptance_tests, start=1):
            code = tc.test_code.strip()
            if code.startswith("def test_"):
                lines.append(f"# [{tc.test_id}] {tc.description}")
                lines.append(code)
                lines.append("")
            else:
                fn_name = tc.test_id if tc.test_id.startswith("test_") else f"test_{tc.test_id}_{idx}"
                lines.append(f"def {fn_name}():")
                lines.append(f'    """{tc.description}"""')
                for stmt in code.splitlines():
                    lines.append(f"    {stmt}")
                lines.append("")
        return "\n".join(lines)