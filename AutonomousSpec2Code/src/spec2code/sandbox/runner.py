"""
Pillar 3: Isolated Subprocess Pytest Sandbox Runner (`src/spec2code/sandbox/runner.py`).

Executes validated Python files inside a fresh `tempfile.TemporaryDirectory`:
- Strips sensitive environment variables (like API keys) before invoking the child process
- Enforces a hard wall-clock timeout (`timeout_seconds`) to catch infinite loops
- Parses `pytest` output to extract deterministic counts (`passed_count`, `failed_count`,
  `acceptance_passed`, `agent_tests_passed`) and concise failure tracebacks for self-correction.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from spec2code.schemas.execution_schema import SandboxExecutionResult


class SandboxRunner:
    """
    Executes generated code and test suites inside an isolated temporary directory.
    """

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run_pytest_sandbox(
        self,
        files: dict[str, str],
        persist_dir: Path | None = None,
    ) -> SandboxExecutionResult:
        """
        Writes `files` (mapping of relative filename -> source code) into an isolated directory,
        executes `python -m pytest -v --tb=short`, and returns a validated `SandboxExecutionResult`.

        If `persist_dir` is provided, also copies the latest files there so the user can inspect
        the final generated artifacts after the pipeline finishes.
        """
        with tempfile.TemporaryDirectory(prefix="spec2code_sandbox_") as tmp_dir:
            sandbox_path = Path(tmp_dir)

            for filename, content in files.items():
                safe_name = Path(filename).name
                (sandbox_path / safe_name).write_text(content, encoding="utf-8")

            if persist_dir is not None:
                persist_dir.mkdir(parents=True, exist_ok=True)
                for filename, content in files.items():
                    safe_name = Path(filename).name
                    (persist_dir / safe_name).write_text(content, encoding="utf-8")

            # Build sanitized environment variables (strip API keys from sandboxed child process)
            clean_env = {
                k: v
                for k, v in os.environ.items()
                if not any(secret in k.upper() for secret in ("API_KEY", "SECRET", "TOKEN", "PASSWORD"))
            }
            clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
            clean_env["PYTHONPATH"] = str(sandbox_path)

            cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-v",
                "--tb=short",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ]

            start_ts = time.perf_counter()
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(sandbox_path),
                    env=clean_env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                duration_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
            except subprocess.TimeoutExpired as exc:
                duration_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
                raw_out = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                raw_err = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                return SandboxExecutionResult(
                    all_passed=False,
                    timed_out=True,
                    exit_code=124,
                    passed_count=0,
                    failed_count=1,
                    acceptance_passed=False,
                    agent_tests_passed=False,
                    duration_ms=duration_ms,
                    stdout=raw_out,
                    stderr=raw_err,
                    failure_summary=f"Sandbox Execution Timed Out after {self.timeout_seconds}s (possible infinite loop).",
                )

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            combined = stdout + ("\n" + stderr if stderr else "")

            passed_count, failed_count = _parse_pytest_counts(combined)
            acceptance_failed = "test_acceptance.py::" in combined and any(
                line.startswith("FAILED test_acceptance.py") or ("test_acceptance.py::" in line and "FAILED" in line)
                for line in combined.splitlines()
            )
            agent_failed = "test_agent_generated.py::" in combined and any(
                line.startswith("FAILED test_agent_generated.py") or ("test_agent_generated.py::" in line and "FAILED" in line)
                for line in combined.splitlines()
            )

            all_passed = completed.returncode == 0 and passed_count > 0 and failed_count == 0
            acceptance_passed = all_passed or (not acceptance_failed and "test_acceptance.py::" in combined and completed.returncode in (0, 1))
            agent_tests_passed = all_passed or (not agent_failed and "test_agent_generated.py::" in combined and completed.returncode in (0, 1))

            failure_summary = "" if all_passed else _extract_failure_summary(combined)

            return SandboxExecutionResult(
                all_passed=all_passed,
                timed_out=False,
                exit_code=completed.returncode,
                passed_count=passed_count,
                failed_count=failed_count,
                acceptance_passed=acceptance_passed,
                agent_tests_passed=agent_tests_passed,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
                failure_summary=failure_summary,
            )

def _parse_pytest_counts(output: str) -> tuple[int, int]:
	"""
	Extracts `(passed_count, failed_count)` from pytest summary line (e.g. `4 passed, 1 failed in 0.03s`).
	"""
	passed = 0
	failed = 0

	pass_match = re.search(r"(\d+)\s+passed", output)
    if pass_match:
        passed = int(pass_match.group(1))

    fail_match = re.search(r"(\d+)\s+failed", output)
    if fail_match:
        failed += int(fail_match.group(1))

    err_match = re.search(r"(\d+)\s+error", output)
    if err_match:
        failed += int(err_match.group(1))

    return passed, failed


def _extract_failure_summary(output: str) -> str:
    """
    Extracts the `=== FAILURES ===` or `=== ERRORS ===` section from pytest output
    so the Repair Agent receives focused, high-signal diagnostic context.
    """
    lines = output.splitlines()
    capture = False
    extracted: list[str] = []

    for line in lines:
        if "=== FAILURES ===" in line or "=== ERRORS ===" in line:
            capture = True
        if capture:
            extracted.append(line)

    if extracted:
        return "\n".join(extracted[-60:])
    # Fallback to last 40 lines of output
    return "\n".join(lines[-40:])