"""
Pillar 4: Multi-Spec Benchmark Runner & Markdown/JSON Report Generator (`src/spec2code/evals/benchmark.py`).

Executes the FSM pipeline across a directory or list of specification files, aggregates:
- `Pass@1` Rate (Immediate accuracy without self-correction)
- `Pass@k` Rate (Final accuracy after up to $k$ self-correction repair loops)
- `Self-Correction Recovery Rate` (% of initially failing specs that the FSM successfully repaired)
- `Average LLM-as-a-Judge Score` and `Composite Score`
And exports human-readable Markdown (`benchmark_report.md`) and machine-readable JSON (`benchmark_report.json`).
"""

from __future__ import annotations

from pathlib import Path

from spec2code.config import PipelineConfig
from spec2code.evals.deterministic import build_spec_evaluation_report
from spec2code.fsm.engine import SpecToCodeFSMEngine
from spec2code.ingest.parser import parse_spec_file
from spec2code.schemas.eval_schema import BenchmarkSuiteReport, SpecEvaluationReport


class BenchmarkRunner:
    """
    Runs a suite of feature specifications through the `SpecToCodeFSMEngine` and produces
    a `BenchmarkSuiteReport`.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        engine: SpecToCodeFSMEngine | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.engine = engine or SpecToCodeFSMEngine(config=self.config)

    def run_suite(
        self,
        spec_paths: list[str | Path],
        artifacts_dir: Path | None = None,
    ) -> BenchmarkSuiteReport:
        """
        Executes each specification file in `spec_paths` and aggregates metrics.
        """
        reports: list[SpecEvaluationReport] = []
        for path in spec_paths:
            spec = parse_spec_file(path)
            ctx = self.engine.run(spec, artifacts_dir=artifacts_dir)
            report = build_spec_evaluation_report(ctx)
            reports.append(report)

        total = len(reports)
        if total == 0:
            raise ValueError("No specification files provided to BenchmarkRunner.run_suite().")

        pass_1_count = sum(1 for r in reports if r.deterministic.passed_at_1)
        pass_k_count = sum(1 for r in reports if r.deterministic.passed_at_k)
        initially_failed = total - pass_1_count
        recovered_count = sum(
            1
            for r in reports
            if not r.deterministic.passed_at_1 and r.deterministic.passed_at_k
        )
        recovery_rate = round(recovered_count / initially_failed, 4) if initially_failed > 0 else 1.0

        passing_attempts = [r.deterministic.total_attempts for r in reports if r.deterministic.passed_at_k]
        avg_attempts = round(sum(passing_attempts) / len(passing_attempts), 2) if passing_attempts else 0.0
        avg_judge = round(sum(r.llm_judge.weighted_overall_score for r in reports) / total, 2)
        avg_composite = round(sum(r.composite_score for r in reports) / total, 2)

        return BenchmarkSuiteReport(
            total_specs=total,
            pass_at_1_rate=round(pass_1_count / total, 4),
            pass_at_k_rate=round(pass_k_count / total, 4),
            self_correction_recovery_rate=recovery_rate,
            average_attempts_to_pass=avg_attempts,
            average_llm_judge_score=avg_judge,
            average_composite_score=avg_composite,
            spec_reports=reports,
        )


def render_markdown_benchmark_report(suite: BenchmarkSuiteReport) -> str:
    """
    Renders a rich, educational Markdown report detailing aggregate benchmark metrics,
    per-spec deterministic vs. LLM-as-a-Judge scores, FSM state traces, and self-correction root causes.
    """
    lines = [
        "# Autonomous Spec-to-Code Benchmark Report",
        "",
        "## 1. Executive Summary & Aggregate Metrics",
        "",
        "| Metric | Value | Description |",
        "| :--- | :--- | :--- |",
        f"| **Total Specifications Evaluated** | `{suite.total_specs}` | JSON & Markdown feature specs ingested |",
        f"| **Pass@1 Rate (Zero-Shot)** | `{suite.pass_at_1_rate:.1%}` | Passed AST & all Pytest suites on Attempt #1 |",
        f"| **Pass@k Rate (With Self-Correction)** | `{suite.pass_at_k_rate:.1%}` | Passed within allowed FSM repair budget |",
        f"| **Self-Correction Recovery Rate** | `{suite.self_correction_recovery_rate:.1%}` | Initially failing specs fixed by the Repair Agent |",
        f"| **Avg Attempts to Converge** | `{suite.average_attempts_to_pass:.2f}` | Mean attempts across passing specifications |",
        f"| **Avg LLM-as-a-Judge Rubric Score** | `{suite.average_llm_judge_score:.1f} / 100` | Weighted score across 4 qualitative rubric dimensions |",
        f"| **Avg Composite Benchmark Score** | `{suite.average_composite_score:.1f} / 100` | 60% Deterministic Execution + 40% LLM-as-a-Judge |",
        "",
        "## 2. Per-Specification Breakdown",
        "",
        "| Spec ID | Title | Difficulty | Status | Pass@1 | Pass@k | Attempts | Tests (P/F) | Judge Score | Composite |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in suite.spec_reports:
        d = r.deterministic
        p1 = "Yes" if d.passed_at_1 else "No"
        pk = "Yes" if d.passed_at_k else "No"
        tests_str = f"{d.total_tests_passed}P / {d.total_tests_failed}F"
        lines.append(
            f"| `{r.spec_id}` | {r.title} | `{r.difficulty}` | **{r.final_status}** | "
            f"{p1} | {pk} | {d.total_attempts} | {tests_str} | "
            f"`{r.llm_judge.weighted_overall_score:.1f}` | **{r.composite_score:.1f}** |"
        )

    lines.append("")
    lines.append("## 3. Deep-Dive: FSM Self-Correction Traces & LLM-as-a-Judge Critiques")
    lines.append("")

    for r in suite.spec_reports:
        lines.append(f"### `{r.spec_id}` — {r.title}")
        lines.append("")
        lines.append(
            f"- **Final Status**: `{r.final_status}` | **Total Duration**: `{r.deterministic.total_duration_ms:.1f} ms`\n"
            f"- **Type-Hint Coverage**: `{r.deterministic.type_hint_coverage:.0%}`\n"
            f"- **Docstring Coverage**: `{r.deterministic.docstring_coverage:.0%}`"
        )
        lines.append("")
        lines.append("#### Finite State Machine (FSM) Transition Trace")
        for idx, step in enumerate(r.state_transitions, start=1):
            lines.append(f"{idx}. `{step}`")
        lines.append("")
            
        if r.repair_history_summaries:
            lines.append("#### Self-Correction Root-Cause Diagnosis & Repair")
            for rep in r.repair_history_summaries:
                lines.append(f"- {rep}")
            lines.append("")

        j = r.llm_judge
        lines.append(f"#### LLM-as-a-Judge Rubric Evaluation (`{j.weighted_overall_score:.1f}` / 100)")
        lines.append(f"- **Spec & Constraint Compliance ({j.spec_compliance.score}/5)**: {j.spec_compliance.chain_of_thought_critique}")
        lines.append(f"- **Algorithmic Efficiency ({j.algorithmic_efficiency.score}/5)**: {j.algorithmic_efficiency.chain_of_thought_critique}")
        lines.append(f"- **Code Readability & Typing ({j.code_readability_and_typing.score}/5)**: ")
        lines.append(f"{j.code_readability_and_typing.chain_of_thought_critique}")
        lines.append(f"- **Test Suite Quality ({j.test_suite_quality.score}/5)**: {j.test_suite_quality.chain_of_thought_critique}")
        lines.append(f"- **Executive Summary**: *{j.executive_summary}*")
        lines.append("")

    return "\n".join(lines)