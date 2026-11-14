"""
Command Line Interface (CLI) for FinFlow-Engine using Typer.

Enables operators to run multi-agent workflows, test chaos recovery, and inspect
the Redis Dead-Letter Queue (DLQ) directly from the terminal.
"""

from __future__ import annotations

import json
import typer

from finflow.graph.runner import run_finflow_workflow
from finflow.resilience.dlq import RedisEventBusAndDLQ

app = typer.Typer(help="FinFlow-Engine Resilient Multi-Agent Financial Workflow CLI")


@app.command("run")
def run_workflow_cli(
    query: str = typer.Option(..., "--query", "-q", help="User investment mandate query."),
    capital: float = typer.Option(5_000_000.0, "--capital", "-c", help="Total capital in USD."),
    scenario: str = typer.Option("baseline", "--scenario", "-s", help="Macro scenario (baseline, hawkish_rate_shock, stagflation, liquidity_crunch)."),
    chaos: bool = typer.Option(False, "--chaos", help="Enable chaos fault injection and retry recovery."),
    thread_id: str | None = typer.Option(None, "--thread-id", "-t", help="Optional persistent thread ID."),
) -> None:
    """Run a financial workflow execution from the command line."""
    typer.echo(f"Running FinFlow workflow for query: '{query}' (Capital: ${capital:,.2f}, Scenario: {scenario})")
    try:
        result = run_finflow_workflow(
            user_query=query,
            total_capital_usd=capital,
            macro_scenario=scenario,
            chaos_mode=chaos,
            thread_id=thread_id,
        )
        typer.echo("\n--- Workflow Execution Result Summary ---")
        typer.echo(
            json.dumps(
                {
                    "status": result.get("workflow_status"),
                    "thread_id": result.get("thread_id"),
                    "allocations": result.get("allocations"),
                    "portfolio_risk": result.get("portfolio_risk"),
                    "evaluation_scores": result.get("evaluation_scores"),
                },
                indent=2,
                default=str,
            )
        )

        memo = result.get("final_memo") or result.get("draft_memo")
        if memo:
            typer.echo("\n--- Executive Memo Preview ---")
            typer.echo(memo[:800] + "\n... [truncated] ...")
    except Exception as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("dlq")
def list_dlq_cli(
    count: int = typer.Option(20, "--count", "-n", help="Number of DLQ entries to display."),
) -> None:
    """Inspect unrecoverable failures in the Redis Dead-Letter Queue."""
    bus = RedisEventBusAndDLQ()
    entries = bus.list_dlq_entries(count=count)
    if not entries:
        typer.echo("Redis Dead-Letter Queue is empty (0 failures).")
        return
    typer.echo(f"Found {len(entries)} DLQ entry/entries:")
    typer.echo(json.dumps(entries, indent=2, default=str))


if __name__ == "__main__":
    app()
