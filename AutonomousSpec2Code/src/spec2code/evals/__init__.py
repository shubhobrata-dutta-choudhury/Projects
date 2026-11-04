"""
Evaluation & Benchmarking package (Deterministic metrics + LLM-as-a-Judge + Benchmark Runner).
"""

from spec2code.evals.benchmark import BenchmarkRunner, render_markdown_benchmark_report
from spec2code.evals.deterministic import (
    build_spec_evaluation_report,
    compute_deterministic_metrics,
)

__all__ = [
    "BenchmarkRunner",
    "build_spec_evaluation_report",
    "compute_deterministic_metrics",
    "render_markdown_benchmark_report",
]