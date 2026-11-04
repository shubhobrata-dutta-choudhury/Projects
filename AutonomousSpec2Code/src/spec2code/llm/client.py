"""
Pluggable Structured-Output LLM Client (`src/spec2code/llm/client.py`).

Supports two modes:
1. `openai`: Live API calls to OpenAI or any OpenAI-compatible server (Ollama, Groq, vLLM, Azure)
   with strict Pydantic JSON Schema validation and automatic schema-error retry.
2. `mock`: Built-in Deterministic Educational Simulator that demonstrates:
   - Pass@1 on `spec_03_interval_merger`
   - Realistic bug injection -> Sandbox Pytest Failure -> Root-Cause Diagnosis -> Surgical Patch on `spec_01_rate_limiter` and `spec_02_lru_cache_ttl`
   - Calibrated Chain-of-Thought LLM-as-a-Judge rubric evaluations
"""

from __future__ import annotations

import json
from typing import TypeVar
from pydantic import BaseModel, ValidationError

from spec2code.config import PipelineConfig
from spec2code.llm.prompts import (
    GENERATOR_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    build_generation_user_prompt,
    build_judge_user_prompt,
    build_repair_user_prompt,
)
from spec2code.schemas.code_ops_schema import (
    CodeGenerationResponse,
    FileModification,
    RepairPatchResponse,
    SearchReplacePatch,
)
from spec2code.schemas.eval_schema import LLMJudgeEvaluation, RubricDimensionScore
from spec2code.schemas.execution_schema import ASTValidationResult, SandboxExecutionResult
from spec2code.schemas.spec_schema import FeatureSpec

T = TypeVar("T", bound=BaseModel)


class StructuredLLMClient:
    """
    Unified interface for generating strictly-typed Pydantic responses from an LLM.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def generate_initial_code(self, spec: FeatureSpec) -> CodeGenerationResponse:
        """
        Synthesizes the initial implementation and unit test suite for `spec`.
        """
        if self.config.llm_provider == "mock":
            return self._mock_generate_initial_code(spec)

        user_prompt = build_generation_user_prompt(spec, CodeGenerationResponse.model_json_schema())
        return self._call_openai_structured(
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=CodeGenerationResponse,
            model_name=self.config.model_name,
        )

    def generate_repair_patch(
        self,
        spec: FeatureSpec,
        current_files: dict[str, str],
        ast_result: ASTValidationResult | None,
        sandbox_result: SandboxExecutionResult | None,
        attempt_number: int,
    ) -> RepairPatchResponse:
        """
        Diagnoses AST or Sandbox test failures and produces a structured `RepairPatchResponse`.
        """
        if self.config.llm_provider == "mock":
            return self._mock_generate_repair_patch(
                spec=spec,
                current_files=current_files,
                ast_result=ast_result,
                sandbox_result=sandbox_result,
                attempt_number=attempt_number,
            )

        user_prompt = build_repair_user_prompt(
            spec=spec,
            current_files=current_files,
            ast_result=ast_result,
			ast_result=ast_result,
        sandbox_result=sandbox_result,
        attempt_number=attempt_number,
        schema_json=RepairPatchResponse.model_json_schema(),
    )
    return self._call_openai_structured(
        system_prompt=REPAIR_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=RepairPatchResponse,
        model_name=self.config.model_name,
    )

def evaluate_with_judge(
    self,
    spec: FeatureSpec,
    final_files: dict[str, str],
    ast_result: ASTValidationResult,
    sandbox_result: SandboxExecutionResult | None,
) -> LLMJudgeEvaluation:
    """
    Runs the LLM-as-a-Judge rubric evaluation over the final artifacts.
    """
    if self.config.llm_provider == "mock":
        return self._mock_evaluate_with_judge(spec, final_files, ast_result, sandbox_result)

    user_prompt = build_judge_user_prompt(
        spec=spec,
        final_files=final_files,
        ast_result=ast_result,
        sandbox_result=sandbox_result,
        schema_json=LLMJudgeEvaluation.model_json_schema(),
    )
    return self._call_openai_structured(
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=LLMJudgeEvaluation,
        model_name=self.config.judge_model_name,
    )

def _call_openai_structured(
    self,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    model_name: str,
) -> T:
    """
    Calls an OpenAI-compatible Chat Completions endpoint and validates the JSON output
    against `response_model` with automatic Pydantic validation error feedback retry.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The 'openai' package is required when SPEC2CODE_LLM_PROVIDER='openai'. "
            "Install it via `pip install openai` or use SPEC2CODE_LLM_PROVIDER='mock'."
        ) from exc

    client = OpenAI(
        api_key=self.config.openai_api_key,
        base_url=self.config.openai_base_url,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_err: Exception | None = None
    for _ in range(3):
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw_content = completion.choices[0].message.content or "{}"
        try:
            data = json.loads(raw_content)
            return response_model.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as err:
            last_err = err
            messages.append({"role": "assistant", "content": raw_content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your JSON response failed Pydantic schema validation:\n{err}\nPlease output corrected JSON.",
                }
            )

    raise RuntimeError(f"Failed to obtain valid {response_model.__name__} after 3 schema retries: {last_err}")


# ==============================================================================
# DETERMINISTIC EDUCATIONAL SIMULATOR ("mock" mode)
# ==============================================================================

def _mock_generate_initial_code(self, spec: FeatureSpec) -> CodeGenerationResponse:
    """
    Produces realistic initial code. When `simulate_bug_on_first_try` is True:
    - `spec_01_rate_limiter`: Attempt 1 forgets to cap refilled tokens at `self.capacity`
      (a classic token bucket bug caught by `test_continuous_refill_and_cap`).
    - `spec_02_lru_cache_ttl`: Attempt 1 forgets to purge expired entries before evicting the
      LRU item when `len == capacity` (caught by `test_purge_expired_before_lru_eviction`).
    - `spec_03_interval_merger`: Passes on Attempt 1 ('Pass@1') to demonstrate both immediate
      success and multi-step self-correction in benchmark reports.
    """

    inject_bug = self.config.simulate_bug_on_first_try

    if spec.spec_id == "spec_01_rate_limiter":
        refill_line = (
            "            self._tokens = self._tokens + elapsed * self.refill_rate"
            if inject_bug
            else "            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)"
        )
        impl_code = (
            '"""Token Bucket Rate Limiter implementation."""\n\n'
            "class TokenBucketRateLimiter:\n"
            '    """Deterministic Token Bucket Rate Limiter with continuous refill."""\n\n'
            "    def __init__(self, capacity: float, refill_rate: float, initial_time: float = 0.0) -> None:\n"
            "        if capacity <= 0 or refill_rate <= 0:\n"
            '            raise ValueError("capacity and refill_rate must be strictly positive.")\n'
            "        self.capacity: float = float(capacity)\n"
            "        self.refill_rate: float = float(refill_rate)\n"
            "        self._tokens: float = float(capacity)\n"
            "        self._last_time: float = float(initial_time)\n\n"
            "    def _refill(self, now: float) -> None:\n"
            "        if now > self._last_time:\n"
            "            elapsed = now - self._last_time\n"
            f"{refill_line}\n"
            "            self._last_time = float(now)\n\n"
            "    def available_tokens(self, now: float = 0.0) -> float:\n"
            '        """Returns the current number of available tokens at timestamp `now`."""\n'
            "        self._refill(now)\n"
            "        return self._tokens\n\n"
            "    def allow_request(self, tokens: float = 1.0, now: float = 0.0) -> bool:\n"
            '        """Attempts to consume `tokens` at timestamp `now`. Returns True if allowed."""\n'
            "        if tokens <= 0:\n"
            '            raise ValueError("Requested tokens must be > 0.")\n'
            "        self._refill(now)\n"
            "        if self._tokens >= tokens:\n"
            "            self._tokens -= tokens\n"
            "            return True\n"
            "        return False\n"
        )

        test_code = (
            '"""Agent-generated edge-case tests for TokenBucketRateLimiter."""\n\n'
            "import math\n"
            "import pytest\n"
            "from rate_limiter import TokenBucketRateLimiter\n\n"
            "def test_non_monotonic_timestamp_does_not_drain_tokens():\n"
            "    limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0, initial_time=10.0)\n"
            "    assert limiter.allow_request(tokens=2.0, now=10.0) is True\n"
            "    assert math.isclose(limiter.available_tokens(now=5.0), 3.0)\n\n"
            "def test_exact_boundary_consumption():\n"
            "    limiter = TokenBucketRateLimiter(capacity=4.0, refill_rate=2.0, initial_time=0.0)\n"
            "    assert limiter.allow_request(tokens=4.0, now=0.0) is True\n"
            "    assert math.isclose(limiter.available_tokens(now=0.0), 0.0)\n"
            "    assert limiter.allow_request(tokens=1.0, now=0.0) is False\n"
        )

        return CodeGenerationResponse(
            architectural_plan=(
                "Design TokenBucketRateLimiter with O(1) lazy refill calculation on each call; "
                "Track _tokens and _last_time; validate positive capacity, refill_rate, and request tokens;"
            ),
            implementation_op=FileModification(
                action="create",
                filepath=spec.target_filename,
                content=impl_code,
                rationale="Create initial TokenBucketRateLimiter implementation.",
            ),
            agent_test_op=FileModification(
                action="create",
                filepath="test_agent_generated.py",
                content=test_code,
                rationale="Create edge-case tests for non-monotonic timestamps and boundary refills.",
            ),
        )

    if spec.spec_id == "spec_02_lru_cache_ttl":
        eviction_block = (
            "        if len(self._store) >= self.capacity:\n"
            "            self._store.popitem(last=False)\n"
            if inject_bug
            else "        self._purge_expired(now)\n"
            "        if len(self._store) >= self.capacity:\n"
            "            self._store.popitem(last=False)\n"
        )
        impl_code = (
            '"""LRU Cache with per-entry TTL expiration."""\n\n'
            "from collections import OrderedDict\n\n"
            "class LRUCacheTTL:\n"
            '    """O(1) amortized LRU Cache with deterministic TTL expiration using OrderedDict."""\n\n'
            "    def __init__(self, capacity: int, default_ttl: float = 60.0) -> None:\n"
            "        if capacity <= 0 or default_ttl <= 0:\n"
            '            raise ValueError("capacity and default_ttl must be > 0.")\n'
            "        self.capacity: int = int(capacity)\n"
            "        self.default_ttl: float = float(default_ttl)\n"
            "        self._store: OrderedDict[str, tuple[object, float]] = OrderedDict()\n\n"
            "    def _purge_expired(self, now: float) -> None:\n"
            "        expired_keys = [k for k, (_, exp) in self._store.items() if now >= exp]\n"
            "        for k in expired_keys:\n"
            "            del self._store[k]\n\n"
            "    def get(self, key: str, now: float = 0.0) -> object | None:\n"
            '        """Retrieves key value at timestamp `now` if present and not expired."""\n'
            "        if key not in self._store:\n"
            "            return None\n"
            "        value, expires_at = self._store[key]\n"
			"		 if now >= expires_at:
			"			 del self._store[key]
			"			 return None
			"		 self._store.move_to_end(key)
			"		 return value

				def put(self, key: str, value: object, now: float = 0.0, ttl: float | None = None) -> None:
					"""Inserts or updates `key` with `value` and TTL at timestamp `now`."""
					effective_ttl = self.default_ttl if ttl is None else ttl
					if effective_ttl <= 0:
						raise ValueError("ttl must be strictly positive.")
					expires_at = now + effective_ttl
					if key in self._store:
						self._store[key] = (value, expires_at)
						self._store.move_to_end(key)
						return 
				f"{eviction_block}"        
					self._store[key] = (value, expires_at)

				def size(self, now: float = 0.0) -> int:
					"""Returns the number of non-expired entries currently in the cache."""
					self._purge_expired(now)
					return len(self._store)
		)
        test_code = (
            '"""Agent-generated edge-case tests for LRUCacheTTL."""\n\n'
            "import pytest\n"
            "from lru_cache_ttl import LRUCacheTTL\n\n"
            "def test_overwrite_updates_ttl_and_recency():\n"
            "    cache = LRUCacheTTL(capacity=2, default_ttl=10.0)\n"
            "    cache.put('k1', 'v1', now=0.0, ttl=5.0)\n"
            "    cache.put('k1', 'v2', now=4.0, ttl=20.0)\n"
            "    assert cache.get('k1', now=10.0) == 'v2'\n\n"
            "def test_invalid_init_and_put_ttl():\n"
            "    with pytest.raises(ValueError):\n"
            "        LRUCacheTTL(capacity=0, default_ttl=10.0)\n"
            "    cache = LRUCacheTTL(capacity=2, default_ttl=10.0)\n"
            "    with pytest.raises(ValueError):\n"
            "        cache.put('k', 'v', now=0.0, ttl=-1.0)\n"
        )
        return CodeGenerationResponse(
            architectural_plan=(
                "Use collections.OrderedDict to maintain O(1) recency ordering alongside (value, expires_at) tuples. "
                "Validate positive capacity and TTLs."
            ),
            implementation_op=FileModification(
                action="create",
                filepath=spec.target_filename,
                content=impl_code,
                rationale="Create LRUCacheTTL using OrderedDict.",
            ),
            agent_test_op=FileModification(
                action="create",
                filepath="test_agent_generated.py",
                content=test_code,
                rationale="Add tests for key overwrites and invalid TTL error handling.",
            ),
        )

    # Default / spec_03_interval_merger (Passes on Attempt 1)
    impl_code = (
        '"""Weighted Time Interval Merger and Gap Analyzer."""\n\n'
        "def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:\n"
        '    """Merges overlapping or adjacent closed intervals [start, end] in O(N log N) time."""\n'
        "    if not intervals:\n"
        "        return []\n"
        "    for start, end in intervals:\n"
        "        if start > end:\n"
        '            raise ValueError(f"Invalid interval ({start}, {end}): start > end.")\n'
        "    sorted_intervals = sorted(intervals, key=lambda x: (x[0], x[1]))\n"
        "    merged: list[tuple[int, int]] = [sorted_intervals[0]]\n"
        "    for current_start, current_end in sorted_intervals[1:]:\n"
        "        prev_start, prev_end = merged[-1]\n"
        "        if current_start <= prev_end:\n"
        "            merged[-1] = (prev_start, max(prev_end, current_end))\n"
        "        else:\n"
        "            merged.append((current_start, current_end))\n"
        "    return merged\n\n"
        "def total_covered_duration(intervals: list[tuple[int, int]]) -> int:\n"
        '    """Calculates the total continuous duration covered by the merged intervals."""\n'
        "    merged = merge_intervals(intervals)\n"
        "    return sum(end - start for start, end in merged)\n"
    )
    test_code = (
        '"""Agent-generated unit tests for interval_merger."""\n\n'
        "import pytest\n"
        "from interval_merger import merge_intervals, total_covered_duration\n\n"
        "def test_nested_and_negative_intervals():\n"
        "    data = [(-10, -5), (-7, 0), (0, 4), (10, 12)]\n"
        "    assert merge_intervals(data) == [(-10, 4), (10, 12)]\n"
        "    assert total_covered_duration(data) == 14 + 2\n"
    )
    return CodeGenerationResponse(
        architectural_plan=(
            "Validate all intervals for start <= end, sort by (start, end) in O(N log N) time, "
            "and perform a linear scan merging intervals when current_start <= prev_end."
        ),
        implementation_op=FileModification(
            action="create",
            filepath=spec.target_filename,
            content=impl_code,
            rationale="Create clean O(N log N) interval merger implementation.",
        ),
        agent_test_op=FileModification(
            action="create",
            filepath="test_agent_generated.py",
            content=test_code,
            rationale="Test negative coordinates, nested intervals, and touching boundaries.",
        ),
    )


def _mock_generate_repair_patch(
    self,
    spec: FeatureSpec,
    current_files: dict[str, str],
    ast_result: ASTValidationResult | None,
    sandbox_result: SandboxExecutionResult | None,
    attempt_number: int,
) -> RepairPatchResponse:
    """
    Inspects the actual failure in `current_files` and emits a targeted `SearchReplacePatch`
    that fixes the root cause.
    """
    if spec.spec_id == "spec_01_rate_limiter":
        return RepairPatchResponse(
            failure_root_cause=(
                "In `test_continuous_refill_and_cap`, `limiter.available_tokens(now=100.0)` returned 202.0 "
                "instead of 10.0 because `_refill()` added `elapsed * self.refill_rate` without clamping "
                "the accumulated tokens to `self.capacity`."
            ),
            fix_strategy=(
                "Apply a surgical search-and-replace patch in `rate_limiter.py` to wrap the token update "
                "in `min(self.capacity, self._tokens + elapsed * self.refill_rate)`."
            ),
            modifications=[
                FileModification(
                    action="patch",
                    filepath="rate_limiter.py",
                    patches=[
                        SearchReplacePatch(
                            search_block="self._tokens = self._tokens + elapsed * self.refill_rate",
                            replace_block="self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)",
                        )
                    ],
                    rationale="Clamp refilled tokens to `self.capacity` so idle periods never overflow the bucket.",
                )
            ],
        )

    if spec.spec_id == "spec_02_lru_cache_ttl":
        return RepairPatchResponse(
            failure_root_cause=(
                "In `test_purge_expired_before_lru_eviction`, inserting `'new_key'` at `now=10.0` when "
                "`len(self._store) == capacity` immediately evicted `'long_lived'` via `popitem(last=False)` "
                "before purging `'short_lived'` which had already expired at `t=6.0`."
            ),
            fix_strategy=(
                "Patch `LRUCacheTTL.put` in `lru_cache_ttl.py` to invoke `self._purge_expired(now)` "
                "before checking `if len(self._store) >= self.capacity:`."
            ),
            modifications=[
                FileModification(
                    action="patch",
                    filepath="lru_cache_ttl.py",
                    patches=[
                        SearchReplacePatch(
                            search_block="        if len(self._store) >= self.capacity:\n            self._store.popitem(last=False)",
                            replace_block="        self._purge_expired(now)\n        if len(self._store) >= self.capacity:\n            self._store.popitem(last=False)",
                        )
                    ],
                    rationale="Purge expired cache entries prior to evicting valid LRU entries at capacity.",
                )
            ],
        )
        
		# Generic fallback repair for custom specs in mock mode
        target_code = current_files.get(spec.target_filename, "")
        return RepairPatchResponse(
            failure_root_cause=f"Detected failure on attempt #{attempt_number}: {sandbox_result.failure_summary if sandbox_result else 'AST violation'}",
            fix_strategy="Ensure implementation satisfies all acceptance assertions and AST constraints.",
            modifications=[
                FileModification(
                    action="overwrite",
                    filepath=spec.target_filename,
                    content=target_code,
                    rationale="Fallback repair modification.",
                )
            ],
        )

    def _mock_evaluate_with_judge(
        self,
        spec: FeatureSpec,
        final_files: dict[str, str],
        ast_result: ASTValidationResult,
        sandbox_result: SandboxExecutionResult | None,
    ) -> LLMJudgeEvaluation:
        """
        Produces a realistic, calibrated `LLMJudgeEvaluation` grounded in the actual AST
        and sandbox execution telemetry.
        """
        all_passed = bool(sandbox_result and sandbox_result.all_passed and ast_result.passed)
        compliance_score = 5 if all_passed else 2
        efficiency_score = 5 if all_passed else 3
        typing_score = 5 if (ast_result.type_hint_coverage_ratio >= 1.0 and ast_result.docstring_coverage_ratio >= 1.0) else 4
        test_score = 5 if (sandbox_result and sandbox_result.agent_tests_passed and sandbox_result.passed_count >= 4) else 3

        return LLMJudgeEvaluation(
            spec_compliance=RubricDimensionScore(
                dimension="Spec & Constraint Compliance",
                chain_of_thought_critique=(
                    f"Inspected `{spec.target_filename}` against entry points {spec.entry_points} and "
                    f"allowed imports {spec.constraints.allowed_imports}. "
                    f"All acceptance tests passed={all_passed} with 0 forbidden AST constructs."
                ),
                score=compliance_score,
            ),
            algorithmic_efficiency=RubricDimensionScore(
                dimension="Algorithmic Efficiency",
                chain_of_thought_critique=(
                    f"Target complexity is `{spec.constraints.time_complexity}` time and "
                    f"`{spec.constraints.space_complexity}` space. The implementation uses optimal "
                    f"data structures and avoids redundant allocations."
                ),
                score=efficiency_score,
            ),
            code_readability_and_typing=RubricDimensionScore(
                dimension="Code Readability & Typing",
                chain_of_thought_critique=(
                    f"Static AST inspection measured {ast_result.type_hint_coverage_ratio:.0%} type-hint coverage "
                    f"and {ast_result.docstring_coverage_ratio:.0%} docstring coverage across "
                    f"{ast_result.public_functions_count} public methods/functions."
                ),
                score=typing_score,
            ),
            test_suite_quality=RubricDimensionScore(
                dimension="Test Suite Quality",
                chain_of_thought_critique=(
                    "Agent-generated test suite (`test_agent_generated.py`) directly exercises boundary conditions, "
                    "invalid input exceptions (`pytest.raises(ValueError)`), and state invariants."
                ),
                score=test_score,
            ),
            executive_summary=(
                f"The synthesized module `{spec.target_filename}` for '{spec.title}' achieved "
                f"{'full convergence across all acceptance and edge-case tests' if all_passed else 'partial completion'} "
                f"with {ast_result.type_hint_coverage_ratio:.0%} type annotation coverage."
            ),
        )