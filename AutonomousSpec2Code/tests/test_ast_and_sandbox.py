"""
Unit tests for Pillar 3: Static AST Security Guard & Isolated Subprocess Sandbox Runner.
"""

from __future__ import annotations

from spec2code.sandbox.ast_guard import validate_code_ast
from spec2code.sandbox.runner import SandboxRunner
from spec2code.schemas.spec_schema import SpecConstraints


def test_ast_guard_blocks_forbidden_imports_and_builtins() -> None:
    """Verifies that `os`, `subprocess`, and `eval()` are flagged as blocking AST violations."""
    constraints = SpecConstraints(allowed_imports=["math"])
    unsafe_code = (
        "import os\n"
        "import math\n\n"
        "def compute(x: str) -> int:\n"
        '    """Unsafe function."""\n'
        "    os.system('echo hacked')\n"
        "    return eval(x)\n"
    )
    res = validate_code_ast(
        files={"unsafe_mod.py": unsafe_code},
        constraints=constraints,
        target_filename="unsafe_mod.py",
    )
    assert res.passed is False
    violation_types = {v.violation_type for v in res.violations if v.is_blocking}
    assert "ForbiddenImport" in violation_types
    assert "ForbiddenCall" in violation_types


def test_ast_guard_catches_syntax_errors_and_measures_coverage() -> None:
    """Verifies SyntaxError detection and accurate type-hint/docstring coverage calculation."""
    constraints = SpecConstraints(allowed_imports=["typing"])
    broken_code = "def broken(a: int) -> int\n    return a\n"
    res_broken = validate_code_ast(
        files={"mod.py": broken_code},
        constraints=constraints,
        target_filename="mod.py",
    )
    assert res_broken.passed is False
    assert any(v.violation_type == "SyntaxError" for v in res_broken.violations)

    # 1 typed & documented function, 1 untyped & undocumented function -> 50% coverage
    mixed_code = (
        "def typed_fn(x: int) -> int:\n"
        '    """Properly documented."""\n'
        "    return x + 1\n\n"
        "def untyped_fn(x):\n"
        "    return x * 2\n"
    )
    res_mixed = validate_code_ast(
        files={"mod.py": mixed_code},
        constraints=constraints,
        target_filename="mod.py",
    )
    assert res_mixed.passed is True
    assert res_mixed.public_functions_count == 2
    assert res_mixed.type_hint_coverage_ratio == 0.5
    assert res_mixed.docstring_coverage_ratio == 0.5


def test_sandbox_runner_executes_passing_and_failing_pytest() -> None:
    """Verifies isolated subprocess execution for both passing and failing pytest suites."""
	runner = SandboxRunner(timeout_seconds=5.0)

		passing_files = {
			"calc.py": "def double(x: int) -> int:\n    return x * 2\n",
			"test_acceptance.py": "from calc import double\ndef test_double():\n    assert double(4) == 8\n",
		}
		pass_res = runner.run_pytest_sandbox(passing_files)
		assert pass_res.all_passed is True
		assert pass_res.passed_count == 1
		assert pass_res.failed_count == 0

		failing_files = {
			"calc.py": "def double(x: int) -> int:\n    return x + 2\n",
			"test_acceptance.py": "from calc import double\ndef test_double():\n    assert double(4) == 8\n",
		}
		fail_res = runner.run_pytest_sandbox(failing_files)
		assert fail_res.all_passed is False
		assert fail_res.failed_count == 1
		assert "assert 6 == 8" in fail_res.failure_summary	