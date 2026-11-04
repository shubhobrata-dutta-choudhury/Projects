"""
Command-Line Interface (`spec2code.cli`) for running single specifications or the full benchmark suite.

Usage Examples:
1. Run full benchmark suite over `specs/` (using educational mock simulator by default):
   `python -m spec2code.cli benchmark --specs-dir specs --output-dir artifacts`

2. Run a single specification file and print its FSM trace + evaluation:
   `python -m spec2code.cli run specs/01_rate_limiter.json`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spec2code.config import PipelineConfig
from spec2code.evals.benchmark import BenchmarkRunner, render_markdown_benchmark_report
from spec2code.evals.deterministic import build_spec_evaluation_report
from spec2code.fsm.engine import SpecToCodeFSMEngine
from spec2code.ingest.parser import parse_spec_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spec2code",
        description="Autonomous Spec-to-Code Pipeline with FSM Self-Correction & Dual Evals",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: `run` (single spec)
    run_parser = subparsers.add_parser("run", help="Run the FSM pipeline on a single .json or .md spec file.")
    run_parser.add_argument("spec_path", type=str, help="Path to the .json or .md specification file.")
    run_parser.add_argument("--provider", choices=["mock", "openai"], default=None, help="Override LLM provider.")
    run_parser.add_argument("--max-retries", type=int, default=3, help="Maximum self-correction repair attempts.")
    run_parser.add_argument("--no-bug-sim", action="store_true", help="Disable initial bug injection in mock mode.")
    run_parser.add_argument("--artifacts-dir", type=str, default="artifacts", help="Directory to persist generated code.")

    # Subcommand: `benchmark` (multi-spec benchmark suite)
    bench_parser = subparsers.add_parser("benchmark", help="Run all specs in a directory and generate benchmark reports.")
    bench_parser.add_argument("--specs-dir", type=str, default="specs", help="Directory containing .json and .md specs.")
    bench_parser.add_argument("--output-dir", type=str, default="artifacts", help="Directory to write benchmark reports and code.")
    bench_parser.add_argument("--provider", choices=["mock", "openai"], default=None, help="Override LLM provider.")
    bench_parser.add_argument("--max-retries", type=int, default=3, help="Maximum self-correction repair attempts.")
    bench_parser.add_argument("--no-bug-sim", action="store_true", help="Disable initial bug injection in mock mode.")

    args = parser.parse_args(argv)

    config = PipelineConfig(
        max_retries=args.max_retries,
        simulate_bug_on_first_try=not getattr(args, "no_bug_sim", False),
    )
    if args.provider:
        config.llm_provider = args.provider

    if args.command == "run":
        spec = parse_spec_file(args.spec_path)
        print(f"=== Running Autonomous Spec-to-Code FSM for '{spec.spec_id}' ({spec.title}) ===")
        engine = SpecToCodeFSMEngine(
            config=config,
            on_transition=lambda ctx: print(
                f"  [FSM] {ctx.transition_history[-1].from_state.value} -> "
                f"{ctx.transition_history[-1].to_state.value} "
                f"(Attempt #{ctx.transition_history[-1].attempt}): {ctx.transition_history[-1].reason}"
            ),
        )
        ctx = engine.run(spec, artifacts_dir=Path(args.artifacts_dir))
        report = build_spec_evaluation_report(ctx)
        print("\n=== Evaluation Summary ===")
        print(f"Final Status            : {report.final_status}")
        print(f"Pass@1 / Pass@k         : {report.deterministic.passed_at_1} / {report.deterministic.passed_at_k}")
        print(f"Total Attempts          : {report.deterministic.total_attempts} (Repairs: {report.deterministic.repairs_triggered})")
        print(f"Sandbox Tests           : {report.deterministic.total_tests_passed} Passed, {report.deterministic.total_tests_failed} Failed")
        print(f"LLM-as-a-Judge          : {report.llm_judge.weighted_overall_score:.1f} / 100")
        print(f"Composite Score         : {report.composite_score:.1f} / 100")
        return 0 if report.deterministic.passed_at_k else 1

    if args.command == "benchmark":
        specs_dir = Path(args.specs_dir)
        spec_files = sorted(
            p for p in specs_dir.iterdir() if p.suffix.lower() in (".json", ".md")
        )
        if not spec_files:
            print(f"No .json or .md spec files found in {specs_dir}", file=sys.stderr)
            return 1

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"=== Running Benchmark Suite across {len(spec_files)} specifications (Provider: {config.llm_provider}) ===")
        runner = BenchmarkRunner(config=config)
        suite_report = runner.run_suite(spec_files, artifacts_dir=output_dir / "generated_code")

        md_report = render_markdown_benchmark_report(suite_report)
        md_path = output_dir / "benchmark_report.md"
        json_path = output_dir / "benchmark_report.json"

        md_path.write_text(md_report, encoding="utf-8")
        json_path.write_text(suite_report.model_dump_json(indent=2), encoding="utf-8")

        print(f"\nBenchmark Summary:")
        print(f"  Total Specs                   : {suite_report.total_specs}")
        print(f"  Pass@1 Rate (Zero-Shot)        : {suite_report.pass_at_1_rate:.1%}")
        print(f"  Pass@k Rate (Self-Corrected)  : {suite_report.pass_at_k_rate:.1%}")
        print(f"  Self-Correction Recovery       : {suite_report.self_correction_recovery_rate:.1%}")
        print(f"  Avg Attempts to Pass           : {suite_report.average_attempts_to_pass:.2f}")
        print(f"  Avg LLM-as-a-Judge Score       : {suite_report.average_llm_judge_score:.1f} / 100")
        print(f"  Avg Composite Score            : {suite_report.average_composite_score:.1f} / 100")
        print(f"\nSaved reports to:\n  - {md_path}\n  - {json_path}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())