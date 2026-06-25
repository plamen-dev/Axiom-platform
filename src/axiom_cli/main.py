"""Axiom CLI - Command-line interface for the Axiom platform."""

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import UUID

import click
from axiom_core.input_normalization import InputNormalizer, NormalizationReport
from axiom_core.mcp_layer import MCPLayer
from axiom_core.orchestrator import Orchestrator
from axiom_core.persistence import storage
from axiom_core.schemas import JobStatus, PlanStatus
from rich.console import Console
from rich.markup import escape as _rich_escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

console = Console()
_logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Axiom Platform CLI - safety-first Revit automation, inventory, validation, and evidence workflows."""
    pass


@cli.command()
@click.argument("excel_file", type=click.Path(exists=True))
@click.option("--firm-id", default="default", help="Firm identifier")
@click.option("--dry-run", is_flag=True, help="Parse and validate only, don't create job")
def submit(excel_file: str, firm_id: str, dry_run: bool):
    """Submit a new job from an Excel file."""
    console.print(f"\n[bold blue]Axiom Platform[/bold blue] - Submitting job from {excel_file}\n")

    normalizer = InputNormalizer()
    report = normalizer.normalize_excel(excel_file, firm_id)

    if report.warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for warning in report.warnings:
            console.print(f"  - {warning.field}: {warning.message}")

    if report.assumptions:
        console.print("\n[cyan]Assumptions made:[/cyan]")
        for assumption in report.assumptions:
            console.print(f"  - {assumption}")

    if not report.success:
        console.print("\n[red]Normalization failed:[/red]")
        for error in report.errors:
            console.print(f"  - {error.field}: {error.message}")
        return

    if dry_run:
        console.print("\n[green]Dry run - Job validated successfully[/green]")
        _display_normalized_job(report)
        return

    if report.job and report.normalized_job:
        storage.save_job(report.job)
        storage.save_normalized_job(report.normalized_job)

        console.print("\n[green]Job created successfully![/green]")
        console.print(f"Job ID: [bold]{report.job.job_id}[/bold]")

        _display_normalized_job(report)


def _display_normalized_job(report: NormalizationReport):
    """Display the normalized job details."""
    if not report.normalized_job:
        return

    job = report.normalized_job
    table = Table(title="Normalized Job Details", show_header=True)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Project Number", job.project_number)
    table.add_row("Project Name", job.project_name)
    table.add_row("Revit Version", str(job.revit_version))
    table.add_row("ACC Project", "Yes" if job.is_acc_project else "No")
    table.add_row("Scope Boxes", str(len(job.scope_boxes)))
    table.add_row("Views Required", str(len(job.views_required)))

    if job.views_required:
        views = ", ".join([v.view_type_code for v in job.views_required])
        table.add_row("View Types", views)

    console.print(table)


@cli.command()
@click.argument("job_id")
@click.option("--approve", is_flag=True, help="Auto-approve the plan")
def plan(job_id: str, approve: bool):
    """Generate an execution plan for a job."""
    try:
        job_uuid = UUID(job_id)
    except ValueError:
        console.print(f"[red]Invalid job ID: {job_id}[/red]")
        return

    normalized_job = storage.get_normalized_job(job_uuid)
    if not normalized_job:
        console.print(f"[red]Job not found: {job_id}[/red]")
        return

    console.print(f"\n[bold blue]Generating plan for job {job_id}[/bold blue]\n")

    mcp = MCPLayer(revit_version=normalized_job.revit_version)
    orchestrator = Orchestrator(mcp_layer=mcp)

    plan = orchestrator.generate_plan(normalized_job)
    storage.save_plan(plan)

    if approve:
        plan.status = PlanStatus.APPROVED
        storage.update_plan_status(plan.plan_id, PlanStatus.APPROVED)

    console.print("[green]Plan generated![/green]")
    console.print(f"Plan ID: [bold]{plan.plan_id}[/bold]")
    console.print(f"Status: {plan.status.value}")
    console.print(f"Steps: {len(plan.steps)}")

    _display_plan_steps(plan)


def _display_plan_steps(plan):
    """Display plan steps as a tree."""
    tree = Tree(f"[bold]Execution Plan[/bold] ({len(plan.steps)} steps)")

    for step in plan.steps:
        step_node = tree.add(
            f"[cyan]{step.sequence}.[/cyan] {step.tool_name} " f"[dim]({step.status.value})[/dim]"
        )
        if step.args:
            args_str = ", ".join(f"{k}={v}" for k, v in list(step.args.items())[:3])
            step_node.add(f"[dim]Args: {args_str}[/dim]")

    console.print(tree)


@cli.command()
@click.argument("plan_id")
@click.option("--production", is_flag=True, help="Execute against production (not simulation)")
def execute(plan_id: str, production: bool):
    """Execute a plan (simulation by default)."""
    try:
        plan_uuid = UUID(plan_id)
    except ValueError:
        console.print(f"[red]Invalid plan ID: {plan_id}[/red]")
        return

    plan = storage.get_plan(plan_uuid)
    if not plan:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        return

    normalized_job = storage.get_normalized_job(plan.job_id)
    if not normalized_job:
        console.print("[red]Job not found for plan[/red]")
        return

    mode = "PRODUCTION" if production else "SIMULATION"
    console.print(f"\n[bold blue]Executing plan in {mode} mode[/bold blue]\n")

    mcp = MCPLayer(revit_version=normalized_job.revit_version)
    orchestrator = Orchestrator(mcp_layer=mcp)
    orchestrator.plans[plan.plan_id] = plan

    if production:
        if plan.status != PlanStatus.SIMULATION_PASSED:
            console.print("[red]Plan must pass simulation before production execution[/red]")
            return
        updated_plan, results = orchestrator.execute_plan(plan)
    else:
        updated_plan, results = orchestrator.simulate_plan(plan)

    storage.save_results(plan.plan_id, results)
    storage.update_plan_status(updated_plan.plan_id, updated_plan.status)

    console.print("\n[green]Execution complete![/green]")
    console.print(f"Status: {updated_plan.status.value}")

    _display_results(results)

    qa_report = orchestrator.evaluate_results(updated_plan, results)
    storage.save_qa_report(qa_report)

    console.print("\n[bold]QA Report[/bold]")
    console.print(f"Status: {qa_report.status.value}")
    console.print(f"Score: {qa_report.score:.1f}/100")


def _display_results(results):
    """Display execution results."""
    table = Table(title="Execution Results", show_header=True)
    table.add_column("#", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Duration", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Warnings", style="yellow")

    for i, result in enumerate(results):
        status_color = {
            "SUCCESS": "green",
            "WARNING": "yellow",
            "FAILED": "red",
        }.get(result.status.value, "white")

        table.add_row(
            str(i + 1),
            f"[{status_color}]{result.status.value}[/{status_color}]",
            f"{result.duration_ms}ms",
            str(len(result.created_ids)),
            str(len(result.warnings)),
        )

    console.print(table)

    for i, result in enumerate(results):
        if result.errors:
            console.print(f"\n[red]Errors (step {i + 1}):[/red]")
            for error in result.errors:
                console.print(f"  [red]{error}[/red]")
        if result.warnings:
            console.print(f"\n[yellow]Warnings (step {i + 1}):[/yellow]")
            for warning in result.warnings:
                console.print(f"  [yellow]{warning}[/yellow]")


@cli.command()
@click.option("--status", help="Filter by status")
@click.option("--limit", default=10, help="Maximum number of jobs to show")
def jobs(status: Optional[str], limit: int):
    """List all jobs."""
    job_status = None
    if status:
        try:
            job_status = JobStatus(status.upper())
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            return

    all_jobs = storage.list_jobs(status=job_status, limit=limit)

    if not all_jobs:
        console.print("[yellow]No jobs found[/yellow]")
        return

    table = Table(title="Jobs", show_header=True)
    table.add_column("Job ID", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Created", style="dim")

    for job in all_jobs:
        status_color = {
            "COMPLETED": "green",
            "FAILED": "red",
            "PENDING": "yellow",
        }.get(job.status.value, "white")

        table.add_row(
            str(job.job_id)[:8] + "...",
            job.job_type.value,
            f"[{status_color}]{job.status.value}[/{status_color}]",
            job.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


@cli.command()
@click.option("--limit", default=10, help="Maximum number of plans to show")
def plans(limit: int):
    """List all plans."""
    all_plans = storage.list_plans(limit=limit)

    if not all_plans:
        console.print("[yellow]No plans found[/yellow]")
        return

    table = Table(title="Plans", show_header=True)
    table.add_column("Plan ID", style="cyan")
    table.add_column("Job ID", style="dim")
    table.add_column("Steps", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Created", style="dim")

    for plan in all_plans:
        status_color = {
            "COMPLETED": "green",
            "FAILED": "red",
            "DRAFT": "yellow",
            "SIMULATION_PASSED": "green",
            "SIMULATION_FAILED": "red",
        }.get(plan.status.value, "white")

        table.add_row(
            str(plan.plan_id)[:8] + "...",
            str(plan.job_id)[:8] + "...",
            str(len(plan.steps)),
            f"[{status_color}]{plan.status.value}[/{status_color}]",
            plan.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


@cli.command()
def tools():
    """List available tools in the MCP layer."""
    mcp = MCPLayer()
    catalog = mcp.get_tool_catalog()

    table = Table(title="Available Tools", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="white")
    table.add_column("Description", style="dim")
    table.add_column("Read-Only", style="yellow")

    for tool in catalog:
        table.add_row(
            tool.name,
            tool.category,
            tool.description[:50] + "..." if len(tool.description) > 50 else tool.description,
            "Yes" if tool.is_read_only else "No",
        )

    console.print(table)


@cli.command()
def stats():
    """Show storage statistics."""
    statistics = storage.get_statistics()

    panel = Panel(
        f"[bold]Total Jobs:[/bold] {statistics['total_jobs']}\n"
        f"[bold]Total Plans:[/bold] {statistics['total_plans']}\n"
        f"[bold]Total QA Reports:[/bold] {statistics['total_qa_reports']}\n\n"
        f"[bold]Jobs by Status:[/bold]\n"
        + "\n".join(f"  {k}: {v}" for k, v in statistics["jobs_by_status"].items())
        + "\n\n[bold]Plans by Status:[/bold]\n"
        + "\n".join(f"  {k}: {v}" for k, v in statistics["plans_by_status"].items()),
        title="Storage Statistics",
    )

    console.print(panel)


@cli.command()
@click.argument("text")
@click.option("--simulate", is_flag=True, help="Validate only, do not execute in Revit")
def prompt(text: str, simulate: bool):
    """Execute a natural-language prompt (e.g. 'create 10 vertical gridlines spaced 10 ft apart')."""
    from axiom_core.agents.execution_agent import ExecutionAgent
    from axiom_core.agents.orchestrator_agent import OrchestratorAgent
    from axiom_core.agents.telemetry_agent import TelemetryAgent
    from axiom_core.pipe_client import PipeClient

    console.print("\n[bold blue]Axiom Prompt[/bold blue]\n")
    console.print(f"[dim]> {text}[/dim]\n")

    pipe_client = PipeClient()
    execution_agent = ExecutionAgent(pipe_client=pipe_client)
    telemetry_agent = TelemetryAgent()
    orchestrator_agent = OrchestratorAgent(
        execution_agent=execution_agent,
        telemetry_agent=telemetry_agent,
    )

    result = orchestrator_agent.handle_prompt(text, simulate=simulate)

    if result["status"] == "UNRESOLVED":
        console.print("[red]Could not resolve prompt to a known capability.[/red]")
        console.print("[dim]Currently supported: grid creation, level creation, model inventory.[/dim]")
        return

    if result["status"] == "CLARIFICATION_NEEDED":
        console.print("[yellow]CLARIFICATION NEEDED[/yellow]\n")
        console.print(result.get("clarification", ""))
        console.print("\n[dim]No changes were made. Please rephrase your prompt.[/dim]")

        # Persist to execution log
        from axiom_core.database import create_db_engine, init_db, make_session_factory
        from axiom_core.execution_log import log_execution

        engine = create_db_engine()
        init_db(engine)
        sf = make_session_factory(engine)
        mode_label = "simulation" if simulate else "execution"
        log_path = log_execution(
            prompt=text,
            resolved=result.get("resolved"),
            results=[],
            plan=None,
            events=telemetry_agent.get_events(),
            mode=mode_label,
            status="CLARIFICATION_NEEDED",
            session_factory=sf,
        )
        console.print(f"\n[dim]Log: {log_path}[/dim]")
        return

    resolved = result["resolved"]
    if resolved.assumptions:
        console.print("[cyan]Assumptions:[/cyan]")
        for assumption in resolved.assumptions:
            console.print(f"  - {assumption}")
        console.print()

    console.print(f"[bold]Capability:[/bold] {resolved.capability_name}")
    console.print("[bold]Parameters:[/bold]")

    display_names = {
        "HorizontalCount": "Vertical Grids",
        "VerticalCount": "Horizontal Grids",
        "SpacingFeet": "Spacing (ft)",
        "Length": "Length (ft)",
        "HorizontalSpacingsFeet": "Vertical Spacings (ft)",
        "VerticalSpacingsFeet": "Horizontal Spacings (ft)",
        "LevelCount": "Levels",
        "FloorToFloorFeet": "Floor-to-Floor (ft)",
        "StartElevationFeet": "Start Elevation (ft)",
        "LevelNames": "Level Names",
        "VariableElevationsFeet": "Elevations (ft)",
    }

    params_table = Table(show_header=True)
    params_table.add_column("Parameter", style="cyan")
    params_table.add_column("Value", style="white")
    for k, v in resolved.params.items():
        display_val = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
        params_table.add_row(display_names.get(k, k), display_val)
    console.print(params_table)

    if result["results"]:
        console.print()
        _display_results(result["results"])

    plan = result["plan"]
    if plan:
        console.print(f"\n[bold]Plan Status:[/bold] {plan.status.value}")

    mode = "SIMULATION" if simulate else "EXECUTION"
    status_color = "green" if result["status"] == "SUCCESS" else "red"
    console.print(f"\n[{status_color}]{mode} {result['status']}[/{status_color}]")

    if not pipe_client.is_available() and not simulate:
        console.print(
            "\n[yellow]Note: Revit pipe not available. " "Results are from mock execution.[/yellow]"
        )

    events = telemetry_agent.get_events()

    # Persist execution record to JSONL log and SQLite
    from axiom_core.database import create_db_engine, init_db, make_session_factory
    from axiom_core.execution_log import log_execution

    engine = create_db_engine()
    init_db(engine)
    sf = make_session_factory(engine)

    mode_label = "simulation" if simulate else "execution"
    log_path = log_execution(
        prompt=text,
        resolved=resolved,
        results=result.get("results", []),
        plan=plan,
        events=events,
        mode=mode_label,
        status=result["status"],
        session_factory=sf,
    )
    console.print(f"\n[dim]Log: {log_path} ({len(events)} events)[/dim]")


@cli.command()
@click.argument("excel_file", type=click.Path(exists=True))
@click.option("--firm-id", default="default", help="Firm identifier")
def demo(excel_file: str, firm_id: str):
    """Run a complete demo: submit, plan, simulate, and report."""
    console.print("\n[bold blue]===== AXIOM PLATFORM DEMO =====[/bold blue]\n")

    console.print("[bold]Step 1: Normalizing input...[/bold]")
    normalizer = InputNormalizer()
    report = normalizer.normalize_excel(excel_file, firm_id)

    if not report.success:
        console.print("[red]Normalization failed[/red]")
        for error in report.errors:
            console.print(f"  - {error.field}: {error.message}")
        return

    if report.job and report.normalized_job:
        storage.save_job(report.job)
        storage.save_normalized_job(report.normalized_job)
        console.print(f"[green]Job created: {report.job.job_id}[/green]")

        console.print("\n[bold]Step 2: Generating plan...[/bold]")
        mcp = MCPLayer(revit_version=report.normalized_job.revit_version)
        orchestrator = Orchestrator(mcp_layer=mcp)

        plan = orchestrator.generate_plan(report.normalized_job)
        plan.status = PlanStatus.APPROVED
        storage.save_plan(plan)
        console.print(f"[green]Plan generated with {len(plan.steps)} steps[/green]")

        console.print("\n[bold]Step 3: Running simulation...[/bold]")
        plan, results = orchestrator.simulate_plan(plan)
        storage.save_results(plan.plan_id, results)
        storage.update_plan_status(plan.plan_id, plan.status)
        console.print(f"[green]Simulation complete: {plan.status.value}[/green]")

        console.print("\n[bold]Step 4: QA Evaluation...[/bold]")
        qa_report = orchestrator.evaluate_results(plan, results)
        storage.save_qa_report(qa_report)
        console.print(
            f"[green]QA Score: {qa_report.score:.1f}/100 ({qa_report.status.value})[/green]"
        )

        console.print("\n[bold blue]===== DEMO COMPLETE =====[/bold blue]")
        console.print(f"\nJob ID: {report.job.job_id}")
        console.print(f"Plan ID: {plan.plan_id}")
        console.print(f"QA Report ID: {qa_report.report_id}")

        _display_plan_steps(plan)
        _display_results(results)


@cli.command("test-grids")
@click.option("--mode", "run_mode", default="simulate",
              type=click.Choice(["simulate", "real"]),
              help="Run mode: simulate (no Revit) or real (requires Revit pipe)")
@click.option("--case-file", default=None, type=click.Path(),
              help="Path to YAML test case file (defaults to built-in suite)")
@click.option("--limit", default=None, type=int,
              help="Maximum number of test cases to run")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
@click.option("--output-dir", default="artifacts/grid_test_runs", type=click.Path(),
              help="Base directory for test run outputs")
@click.option("--fail-fast", is_flag=True, help="Stop on first failure")
@click.option("--review-output", is_flag=True,
              help="Export CSV, XLSX, and Markdown review package alongside Parquet")
def test_grids(run_mode, case_file, limit, run_id, output_dir, fail_fast, review_output):
    """Run the CreateGrids deterministic test harness."""
    from datetime import datetime, timezone
    from pathlib import Path

    from axiom_core.testing.loader import load_test_cases
    from axiom_core.testing.report import find_latest_previous_run, generate_summary
    from axiom_core.testing.runner import run_test_suite
    from axiom_core.testing.storage import export_review_package, persist_results

    console.print("\n[bold blue]Axiom Grid Test Harness[/bold blue]\n")

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")

    output_path = Path(output_dir)

    # Load cases
    try:
        cases = load_test_cases(
            case_file=case_file,
            mode_filter=run_mode,
            limit=limit,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        return

    console.print(f"[dim]Run ID:    {run_id}[/dim]")
    console.print(f"[dim]Mode:      {run_mode}[/dim]")
    console.print(f"[dim]Cases:     {len(cases)}[/dim]")
    console.print(f"[dim]Fail-fast: {fail_fast}[/dim]")
    console.print()

    if not cases:
        console.print("[yellow]No test cases found for the selected mode.[/yellow]")
        return

    # Run
    results = run_test_suite(cases, fail_fast=fail_fast)

    # Display results table
    results_table = Table(title="Test Results", show_header=True)
    results_table.add_column("Test ID", style="cyan", min_width=20)
    results_table.add_column("Status", min_width=8)
    results_table.add_column("Passed", min_width=6)
    results_table.add_column("Created", min_width=7)
    results_table.add_column("Duration", min_width=8)
    results_table.add_column("Failure", style="dim", max_width=40)

    for r in results:
        status_color = {
            "SUCCESS": "green",
            "FAILED": "red",
            "UNRESOLVED": "yellow",
            "SKIPPED": "dim",
            "ERROR": "red bold",
        }.get(r.status, "white")

        passed_str = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        if r.failure_category == "skipped":
            passed_str = "[dim]SKIP[/dim]"

        results_table.add_row(
            r.test_id,
            f"[{status_color}]{r.status}[/{status_color}]",
            passed_str,
            str(r.created_count),
            f"{r.duration_ms}ms",
            r.failure_detail[:40] if r.failure_detail else "",
        )

    console.print(results_table)

    # Persist
    try:
        from axiom_core.database import create_db_engine, init_db, make_session_factory

        engine = create_db_engine()
        init_db(engine)
        sf = make_session_factory(engine)
    except Exception:
        sf = None

    paths = persist_results(results, output_path, run_id, session_factory=sf)

    # Find previous run for regression comparison
    previous = find_latest_previous_run(output_path, run_id)

    # Generate summary
    summary_path = generate_summary(
        results, run_id, output_path, previous_parquet=previous
    )

    # Print summary stats
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and r.failure_category != "skipped")
    skipped = sum(1 for r in results if r.failure_category == "skipped")

    console.print()
    pass_rate = (passed / total * 100) if total > 0 else 0
    color = "green" if failed == 0 else "red"
    console.print(
        f"[{color}]{passed}/{total} passed[/{color}] "
        f"({pass_rate:.0f}%) "
        f"| {failed} failed | {skipped} skipped"
    )

    if previous:
        console.print(f"[dim]Regression baseline: {previous.parent.name}[/dim]")

    console.print(f"\n[dim]JSONL:   {paths.get('jsonl')}[/dim]")
    console.print(f"[dim]Parquet: {paths.get('parquet')}[/dim]")
    console.print(f"[dim]Summary: {summary_path}[/dim]")

    if review_output:
        review_paths = export_review_package(
            results, output_path / run_id, run_id=run_id,
        )
        console.print("\n[bold blue]Review Package[/bold blue]")
        for fmt, rpath in review_paths.items():
            console.print(f"[dim]{fmt}: {rpath}[/dim]")


@cli.command("test-levels")
@click.option("--mode", "run_mode", default="simulate",
              type=click.Choice(["simulate", "real"]),
              help="Run mode: simulate (no Revit) or real (requires Revit pipe)")
@click.option("--case-file", default=None, type=click.Path(),
              help="Path to YAML test case file (defaults to built-in suite)")
@click.option("--limit", default=None, type=int,
              help="Maximum number of test cases to run")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
@click.option("--output-dir", default="artifacts/level_test_runs", type=click.Path(),
              help="Base directory for test run outputs")
@click.option("--fail-fast", is_flag=True, help="Stop on first failure")
@click.option("--review-output", is_flag=True,
              help="Export CSV, XLSX, and Markdown review package alongside Parquet")
def test_levels(run_mode, case_file, limit, run_id, output_dir, fail_fast, review_output):
    """Run the CreateLevels deterministic test harness."""
    from datetime import datetime, timezone
    from pathlib import Path

    from axiom_core.testing.loader import load_test_cases
    from axiom_core.testing.report import find_latest_previous_run, generate_summary
    from axiom_core.testing.runner import run_test_suite
    from axiom_core.testing.storage import export_review_package, persist_results

    console.print("\n[bold blue]Axiom Level Test Harness[/bold blue]\n")

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")

    output_path = Path(output_dir)

    # Load cases — default to level fixture
    if case_file is None:
        case_file = str(
            Path(__file__).resolve().parents[2]
            / "tests"
            / "fixtures"
            / "level_test_cases"
            / "create_levels.yaml"
        )

    try:
        cases = load_test_cases(
            case_file=case_file,
            mode_filter=run_mode,
            limit=limit,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        return

    console.print(f"[dim]Run ID:    {run_id}[/dim]")
    console.print(f"[dim]Mode:      {run_mode}[/dim]")
    console.print(f"[dim]Cases:     {len(cases)}[/dim]")
    console.print(f"[dim]Fail-fast: {fail_fast}[/dim]")
    console.print()

    if not cases:
        console.print("[yellow]No test cases found for the selected mode.[/yellow]")
        return

    # Run
    results = run_test_suite(cases, fail_fast=fail_fast)

    # Display results table
    results_table = Table(title="Level Test Results", show_header=True)
    results_table.add_column("Test ID", style="cyan", min_width=20)
    results_table.add_column("Status", min_width=8)
    results_table.add_column("Passed", min_width=6)
    results_table.add_column("Created", min_width=7)
    results_table.add_column("Duration", min_width=8)
    results_table.add_column("Failure", style="dim", max_width=40)

    for r in results:
        status_color = {
            "SUCCESS": "green",
            "FAILED": "red",
            "UNRESOLVED": "yellow",
            "SKIPPED": "dim",
            "ERROR": "red bold",
            "CLARIFICATION_NEEDED": "yellow",
        }.get(r.status, "white")

        passed_str = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        if r.failure_category == "skipped":
            passed_str = "[dim]SKIP[/dim]"

        results_table.add_row(
            r.test_id,
            f"[{status_color}]{r.status}[/{status_color}]",
            passed_str,
            str(r.created_count),
            f"{r.duration_ms}ms",
            r.failure_detail[:40] if r.failure_detail else "",
        )

    console.print(results_table)

    # Persist
    try:
        from axiom_core.database import create_db_engine, init_db, make_session_factory

        engine = create_db_engine()
        init_db(engine)
        sf = make_session_factory(engine)
    except Exception:
        sf = None

    paths = persist_results(results, output_path, run_id, session_factory=sf)

    # Find previous run for regression comparison
    previous = find_latest_previous_run(output_path, run_id)

    # Generate summary
    summary_path = generate_summary(
        results, run_id, output_path, previous_parquet=previous
    )

    # Print summary stats
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and r.failure_category != "skipped")
    skipped = sum(1 for r in results if r.failure_category == "skipped")

    console.print()
    pass_rate = (passed / total * 100) if total > 0 else 0
    color = "green" if failed == 0 else "red"
    console.print(
        f"[{color}]{passed}/{total} passed[/{color}] "
        f"({pass_rate:.0f}%) "
        f"| {failed} failed | {skipped} skipped"
    )

    if previous:
        console.print(f"[dim]Regression baseline: {previous.parent.name}[/dim]")

    console.print(f"\n[dim]JSONL:   {paths.get('jsonl')}[/dim]")
    console.print(f"[dim]Parquet: {paths.get('parquet')}[/dim]")
    console.print(f"[dim]Summary: {summary_path}[/dim]")

    if review_output:
        review_paths = export_review_package(
            results, output_path / run_id, run_id=run_id,
        )
        console.print("\n[bold blue]Review Package[/bold blue]")
        for fmt, rpath in review_paths.items():
            console.print(f"[dim]{fmt}: {rpath}[/dim]")


@cli.command("inventory-model")
@click.option("--output-dir", default="artifacts/model_inventory_runs", type=click.Path(),
              help="Base directory for inventory run outputs")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
def inventory_model(output_dir, run_id):
    """Run a read-only model inventory (InventoryModel capability)."""
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from axiom_core.agents.execution_agent import ExecutionAgent
    from axiom_core.agents.orchestrator_agent import OrchestratorAgent
    from axiom_core.agents.telemetry_agent import TelemetryAgent
    from axiom_core.inventory.report import generate_summary
    from axiom_core.inventory.storage import persist_inventory
    from axiom_core.pipe_client import PipeClient

    console.print("\n[bold blue]Axiom Model Inventory[/bold blue]\n")

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("inv_%Y%m%d_%H%M%S")

    output_path = Path(output_dir)

    pipe_client = PipeClient()
    execution_agent = ExecutionAgent(pipe_client=pipe_client)
    telemetry_agent = TelemetryAgent()
    orchestrator = OrchestratorAgent(
        execution_agent=execution_agent,
        telemetry_agent=telemetry_agent,
    )

    console.print(f"[dim]Run ID: {run_id}[/dim]")
    console.print("[dim]Sending InventoryModel prompt...[/dim]\n")

    start_time = time.time()
    result = orchestrator.handle_prompt("Run InventoryModel", simulate=False)
    elapsed_ms = int((time.time() - start_time) * 1000)

    if result["status"] not in ("SUCCESS", "COMPLETED"):
        console.print(f"[red]Inventory failed: {result['status']}[/red]")
        errors = result.get("errors", [])
        for err in errors:
            console.print(f"  [red]{err}[/red]")
        return

    # Extract elements and source model from result
    elements: list[dict] = []
    source_model = ""
    results_list = result.get("results", [])
    for r in results_list:
        output_data = getattr(r, "output_data", {}) if hasattr(r, "output_data") else {}
        elements.extend(output_data.get("elements", []))
        if not source_model:
            source_model = output_data.get("source_model", "")

    console.print(f"[green]Inventory collected {len(elements)} elements[/green]")

    # Display summary table
    instances = [e for e in elements if not e.get("IsType", False)]
    types = [e for e in elements if e.get("IsType", False)]

    all_params = []
    for elem in elements:
        all_params.extend(elem.get("Parameters", []))

    summary_table = Table(title="Inventory Summary", show_header=True)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Count", style="white")
    summary_table.add_row("Element instances", str(len(instances)))
    summary_table.add_row("Element types", str(len(types)))
    summary_table.add_row("Total parameters", str(len(all_params)))

    read_only = sum(1 for p in all_params if p.get("IsReadOnly", False))
    writable = len(all_params) - read_only
    summary_table.add_row("Read-only params", str(read_only))
    summary_table.add_row("Writable params", str(writable))

    missing_level = sum(1 for e in instances if not e.get("LevelName"))
    summary_table.add_row("Missing level", str(missing_level))
    summary_table.add_row("Duration", f"{elapsed_ms}ms")
    console.print(summary_table)

    # Category breakdown
    from collections import Counter as _Counter

    cat_counter = _Counter(e.get("Category", "(No Category)") for e in elements)
    if cat_counter:
        cat_table = Table(title="Categories", show_header=True)
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", style="white")
        for cat, count in cat_counter.most_common(15):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    # Persist
    try:
        from axiom_core.database import create_db_engine, init_db, make_session_factory

        engine = create_db_engine()
        init_db(engine)
        sf = make_session_factory(engine)
    except Exception:
        sf = None

    paths = persist_inventory(
        elements, output_path, run_id,
        session_factory=sf, source_model=source_model,
    )

    summary_path = generate_summary(
        elements, run_id, output_path,
        duration_ms=elapsed_ms, source_model=source_model,
    )

    console.print(f"\n[dim]JSONL:       {paths.get('jsonl')}[/dim]")
    console.print(f"[dim]Elements:    {paths.get('elements_parquet')}[/dim]")
    console.print(f"[dim]Parameters:  {paths.get('parameters_parquet')}[/dim]")
    console.print(f"[dim]Summary:     {summary_path}[/dim]")


@cli.command("inventory-summary")
@click.option("--latest", is_flag=True, default=False,
              help="Inspect the most recent inventory run")
@click.option("--run-id", "run_id", default=None,
              help="Specific run ID to inspect")
@click.option("--base-dir", default="artifacts/model_inventory_runs", type=click.Path(),
              help="Base directory for inventory run outputs")
@click.option("--category", "category_filter", default=None,
              help="Filter by category (case-insensitive substring)")
@click.option("--param-name", "param_name_filter", default=None,
              help="Filter by parameter name (case-insensitive substring)")
@click.option("--writable-only", is_flag=True, default=False,
              help="Show only writable parameters")
def inventory_summary(latest, run_id, base_dir, category_filter, param_name_filter, writable_only):
    """Inspect and summarize an InventoryModel run from Parquet artifacts."""
    from pathlib import Path

    from axiom_core.inventory.review import find_latest_run, load_summary

    base_path = Path(base_dir)

    if run_id:
        run_dir = base_path / run_id
    elif latest:
        run_dir = find_latest_run(base_path)
        if run_dir is None:
            console.print(f"[red]No inventory runs found in {base_path}[/red]")
            return
    else:
        console.print("[red]Specify --latest or --run-id[/red]")
        return

    if not run_dir.exists():
        console.print(f"[red]Run directory not found: {run_dir}[/red]")
        return

    console.print("\n[bold blue]Inventory Summary[/bold blue]")
    console.print(f"[dim]Run directory: {run_dir}[/dim]\n")

    s = load_summary(
        run_dir,
        category_filter=category_filter,
        param_name_filter=param_name_filter,
        writable_only=writable_only,
    )

    if not s.total_elements and not s.total_parameters and not s.parameter_definition_count:
        console.print("[yellow]No data found in this run.[/yellow]")
        return

    is_summary_mode = s.scan_mode == "summary"

    # Filters banner
    filters = []
    if category_filter:
        filters.append(f"category='{category_filter}'")
    if param_name_filter:
        filters.append(f"param_name='{param_name_filter}'")
    if writable_only:
        filters.append("writable only")
    if filters:
        console.print(f"[dim]Filters: {', '.join(filters)}[/dim]\n")

    # Load extra metadata (prompt traceability) from run_metadata.json
    run_meta_path = run_dir / "run_metadata.json"
    run_meta_extra: dict = {}
    if run_meta_path.exists():
        import json as _json
        with open(run_meta_path, "r", encoding="utf-8-sig") as _mf:
            run_meta_extra = _json.load(_mf)

    # Run metadata
    meta_table = Table(title="Run Metadata", show_header=True)
    meta_table.add_column("Field", style="cyan")
    meta_table.add_column("Value", style="white")
    meta_table.add_row("Run ID", s.run_id or "(unknown)")
    meta_table.add_row("Source Model", s.source_model or "(unknown)")
    if s.scan_mode:
        meta_table.add_row("Scan Mode", s.scan_mode)
    raw_prompt = run_meta_extra.get("raw_prompt", "")
    if raw_prompt:
        meta_table.add_row("Prompt", raw_prompt)
    obj_cat = run_meta_extra.get("object_category", "")
    if obj_cat:
        meta_table.add_row("Object Category", obj_cat)
    if run_meta_extra.get("source"):
        meta_table.add_row("Source", run_meta_extra["source"])
    console.print(meta_table)

    # Totals
    if s.is_parameter_schema:
        totals_table = Table(title="Parameter Schema Totals", show_header=True)
        totals_table.add_column("Metric", style="cyan")
        totals_table.add_column("Count", style="white")
        totals_table.add_row("Parameter definitions", str(s.parameter_definition_count))
        totals_table.add_row("Unique parameter names", str(s.unique_parameter_names))
        totals_table.add_row("Read-only", str(s.read_only_params))
        totals_table.add_row("Writable", str(s.writable_params))
        totals_table.add_row("Instance params", str(s.instance_params))
        totals_table.add_row("Type params", str(s.type_params))
        if s.unique_data_types:
            totals_table.add_row("Unique data types", str(s.unique_data_types))
        if s.unique_groups:
            totals_table.add_row("Unique parameter groups", str(s.unique_groups))
        if s.measurable_count:
            totals_table.add_row("Measurable specs", str(s.measurable_count))
        if s.unique_disciplines:
            totals_table.add_row("Disciplines", str(s.unique_disciplines))
        console.print(totals_table)

        if s.top_data_type_labels:
            dt_table = Table(title="Top Data Types", show_header=True)
            dt_table.add_column("Data Type", style="cyan")
            dt_table.add_column("Count", style="white")
            for label, count in s.top_data_type_labels[:10]:
                dt_table.add_row(label, str(count))
            console.print(dt_table)

        if s.top_group_labels:
            grp_table = Table(title="Top Parameter Groups", show_header=True)
            grp_table.add_column("Group", style="cyan")
            grp_table.add_column("Count", style="white")
            for label, count in s.top_group_labels[:10]:
                grp_table.add_row(label, str(count))
            console.print(grp_table)

        if s.top_disciplines:
            disc_table = Table(title="Disciplines", show_header=True)
            disc_table.add_column("Discipline", style="cyan")
            disc_table.add_column("Count", style="white")
            for label, count in s.top_disciplines:
                disc_table.add_row(label, str(count))
            console.print(disc_table)
    else:
        totals_table = Table(title="Totals", show_header=True)
        totals_table.add_column("Metric", style="cyan")
        totals_table.add_column("Count", style="white")
        totals_table.add_row("Element instances", str(s.total_instances))
        totals_table.add_row("Element types", str(s.total_types))
        if is_summary_mode and s.total_parameters == 0:
            totals_table.add_row(
                "Parameters", "0 (summary mode — no parameter dump)"
            )
        else:
            totals_table.add_row("Total parameters", str(s.total_parameters))
            totals_table.add_row("Read-only params", str(s.read_only_params))
            totals_table.add_row("Writable params", str(s.writable_params))
            totals_table.add_row("Instance params", str(s.instance_params))
            totals_table.add_row("Type params", str(s.type_params))
        totals_table.add_row("Missing level", str(s.missing_level_count))
        console.print(totals_table)

    # Category counts
    if s.category_counts:
        cat_title = "Categories (param definitions)" if s.is_parameter_schema else "Categories"
        cat_table = Table(title=cat_title, show_header=True)
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", style="white")
        for cat, count in sorted(s.category_counts.items(), key=lambda x: -x[1]):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    # Top parameter names
    if s.top_param_names:
        param_title = "Top Parameter Definitions" if s.is_parameter_schema else "Top Parameter Names"
        param_table = Table(title=param_title, show_header=True)
        param_table.add_column("Parameter", style="cyan")
        param_table.add_column("Occurrences", style="white")
        for name, count in s.top_param_names[:15]:
            param_table.add_row(name, str(count))
        console.print(param_table)


@cli.command("local-runner")
@click.option("--task", "task_path", required=True, type=click.Path(exists=True),
              help="Path to task.json file")
@click.option("--artifact-dir", default="artifacts/local_runner_runs",
              type=click.Path(), help="Base directory for run artifacts")
def local_runner(task_path, artifact_dir):
    """Execute an allowlisted local action from a task.json file.

    The local runner provides a restricted execution harness for safe
    local developer/agent operations. Only named allowlisted actions
    are permitted — no arbitrary shell commands.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    from local_runner.local_runner import run_from_task_file

    console.print("\n[bold blue]Axiom Local Runner[/bold blue]\n")
    console.print(f"[dim]Task: {task_path}[/dim]")
    console.print(f"[dim]Artifacts: {artifact_dir}[/dim]\n")

    result = run_from_task_file(task_path, artifact_base=artifact_dir)

    status_color = {
        "success": "green",
        "failed": "red",
        "timed_out": "yellow",
        "blocked": "red",
        "not_implemented": "yellow",
    }.get(result.status, "white")

    console.print(f"[{status_color}]Status: {result.status}[/{status_color}]")
    console.print(f"Action: {result.action}")
    console.print(f"Exit code: {result.exit_code}")
    console.print(f"Duration: {result.duration_ms}ms")

    if result.artifact_dir:
        console.print(f"Artifacts: {result.artifact_dir}")

    if result.error_message:
        console.print(f"[red]Error: {result.error_message}[/red]")

    if result.status != "success" and result.artifact_dir:
        failure_path = Path(result.artifact_dir) / "failure_summary.md"
        if failure_path.exists():
            console.print(f"\n[dim]Failure summary: {failure_path}[/dim]")


@cli.command("inventory-import")
@click.option("--latest", is_flag=True, default=False,
              help="Import the most recent Revit inventory export")
@click.option("--file", "import_file", default=None, type=click.Path(exists=True),
              help="Path to a specific inventory JSON file to import")
@click.option("--export-dir", default=None, type=click.Path(),
              help="Directory containing inventory JSON exports "
                   "(default: %%LOCALAPPDATA%%/Axiom/inventory_exports)")
@click.option("--output-dir", default="artifacts/model_inventory_runs", type=click.Path(),
              help="Base directory for persisted inventory artifacts")
def inventory_import(latest, import_file, export_dir, output_dir):
    """Import a Revit InventoryModel JSON export into the Python artifact pipeline.

    The Revit Prompt dialog writes inventory JSON to:
      %LOCALAPPDATA%/Axiom/inventory_exports/inv_YYYYMMDD_HHmmss.json

    This command reads that JSON and persists it as:
      - elements.parquet
      - parameters.parquet
      - elements.jsonl
      - summary.md
    """
    import json
    import os
    import platform
    from pathlib import Path


    # Determine the export directory
    if import_file:
        json_path = Path(import_file)
    else:
        if export_dir:
            export_path = Path(export_dir)
        elif platform.system() == "Windows":
            local_app = os.environ.get("LOCALAPPDATA", "")
            export_path = Path(local_app) / "Axiom" / "inventory_exports"
        else:
            # Linux/Mac fallback for testing
            export_path = Path.home() / ".axiom" / "inventory_exports"

        if not export_path.exists():
            console.print(f"[red]Export directory not found: {export_path}[/red]")
            console.print("[dim]Run InventoryModel from the Revit Prompt dialog first.[/dim]")
            return

        json_files = sorted(export_path.glob("inv_*.json"), reverse=True)
        if not json_files:
            console.print(f"[red]No inventory exports found in {export_path}[/red]")
            return

        if latest:
            json_path = json_files[0]
        else:
            console.print("[bold]Available inventory exports:[/bold]")
            for f in json_files[:10]:
                console.print(f"  {f.name}")
            console.print("\n[dim]Use --latest or --file <path> to import.[/dim]")
            return

    console.print("\n[bold blue]Importing Inventory[/bold blue]")
    console.print(f"[dim]Source: {json_path}[/dim]\n")

    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    run_id = data.get("run_id", json_path.stem)
    source_model = data.get("source_model", "")
    scan_mode = data.get("scan_mode", "")

    # Detect parameter schema mode
    is_param_schema = scan_mode in (
        "parameter_schema", "category_parameter_schema",
    ) or "parameter_definitions" in data

    # Detect object schema mode
    is_object_schema = scan_mode in ("object_schema", "category_object_schema")

    if is_param_schema:
        _import_parameter_schema(data, run_id, source_model, scan_mode, json_path, output_dir)
    elif is_object_schema:
        _import_object_schema(data, run_id, source_model, scan_mode, json_path, output_dir)
    else:
        _import_standard_inventory(data, run_id, source_model, scan_mode, json_path, output_dir)


def _import_object_schema(data, run_id, source_model, scan_mode, json_path, output_dir):
    """Import an object_schema JSON export as an object registry candidate."""
    import json
    from pathlib import Path

    from axiom_core.inventory.storage import persist_object_registry

    elements = data.get("elements", [])
    instance_count = data.get("instance_count", 0)
    type_count = data.get("type_count", 0)
    element_count = data.get("element_count", instance_count + type_count)

    console.print(f"  Run ID: [cyan]{run_id}[/cyan]")
    console.print(f"  Source model: [cyan]{source_model}[/cyan]")
    console.print(f"  Scan mode: [cyan]{scan_mode}[/cyan]")
    console.print(f"  Elements: {element_count} ({instance_count} instances, {type_count} types)")

    # Build object registry candidate
    reg_dir = Path("artifacts/object_registry_candidates")
    reg_paths = persist_object_registry(
        elements=elements,
        output_dir=reg_dir,
        run_id=run_id,
        source_model=source_model,
    )
    console.print("\n[green]Object registry candidate:[/green]")
    for fmt, path in reg_paths.items():
        console.print(f"  {fmt}: {path}")

    # Also persist standard inventory for query support
    output_path = Path(output_dir)
    from axiom_core.inventory.storage import persist_inventory

    std_paths = persist_inventory(
        elements=elements,
        output_dir=output_path,
        run_id=run_id,
        source_model=source_model,
    )
    console.print("\n[green]Inventory data:[/green]")
    for fmt, path in std_paths.items():
        console.print(f"  {fmt}: {path}")

    # Category breakdown
    category_counts: dict[str, int] = {}
    for elem in elements:
        cat = elem.get("Category", "Unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Write run_metadata.json
    run_dir = output_path / run_id
    run_metadata = {
        "run_id": run_id,
        "source_model": source_model,
        "scan_mode": scan_mode,
        "instance_count": instance_count,
        "type_count": type_count,
        "element_count": element_count,
        "category_count": len(category_counts),
        "imported_from": json_path.name,
    }
    for tf in ("raw_prompt", "resolved_capability", "result_class", "source", "active_view"):
        val = data.get(tf, "")
        if val:
            run_metadata[tf] = val
    meta_path = run_dir / "run_metadata.json"
    meta_path.write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")
    console.print(f"  metadata: {meta_path}")

    raw_prompt = data.get("raw_prompt", "")
    if raw_prompt:
        console.print(f"  Raw prompt: [dim]{raw_prompt}[/dim]")

    # Write summary.md
    summary_path = run_dir / "summary.md"
    summary_lines = [
        f"# Object Schema Run: {run_id}\n",
        f"- **Source model:** {source_model}\n",
        f"- **Scan mode:** {scan_mode}\n",
    ]
    if raw_prompt:
        summary_lines.append(f"- **Prompt:** `{raw_prompt}`\n")
    summary_lines.extend([
        f"- **Instances:** {instance_count}\n",
        f"- **Types:** {type_count}\n",
        f"- **Total elements:** {element_count}\n",
        f"- **Categories:** {len(category_counts)}\n",
        f"- **Imported from:** `{json_path.name}`\n",
        "\n## Top Categories\n",
    ])
    for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1])[:20]:
        summary_lines.append(f"- {cat}: {cnt}\n")
    summary_path.write_text("".join(summary_lines), encoding="utf-8")
    console.print(f"  summary: {summary_path}")

    # Object registry summary
    reg_summary_path = reg_dir / run_id / "summary.md"
    reg_summary_path.parent.mkdir(parents=True, exist_ok=True)
    reg_lines = [
        f"# Object Registry Candidate: {run_id}\n",
        f"- **Source model:** {source_model}\n",
        f"- **Total elements:** {element_count}\n",
        f"- **Categories:** {len(category_counts)}\n",
        f"- **Instances:** {instance_count}\n",
        f"- **Types:** {type_count}\n",
        "\n## Categories\n",
    ]
    for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
        reg_lines.append(f"- {cat}: {cnt}\n")
    reg_summary_path.write_text("".join(reg_lines), encoding="utf-8")
    console.print(f"  registry summary: {reg_summary_path}")

    console.print("\n[bold green]Object schema import complete.[/bold green]")
    console.print("[dim]Next: axiom inventory-plan --file <summary.json> --mode parameter-schema[/dim]")


def _import_parameter_schema(data, run_id, source_model, scan_mode, json_path, output_dir):
    """Import a parameter schema JSON export."""
    import json
    from pathlib import Path

    from axiom_core.inventory.storage import persist_parameter_schema

    param_defs = data.get("parameter_definitions", data.get("elements", []))
    object_category = data.get("object_category", "")
    console.print(f"  Run ID: [cyan]{run_id}[/cyan]")
    console.print(f"  Source model: [cyan]{source_model}[/cyan]")
    console.print(f"  Scan mode: [cyan]{scan_mode}[/cyan]")
    if object_category:
        console.print(f"  Object Category: [cyan]{object_category}[/cyan]")
    console.print(f"  Parameter definitions: {len(param_defs)}")

    output_path = Path(output_dir)
    paths = persist_parameter_schema(
        param_defs=param_defs,
        output_dir=output_path,
        run_id=run_id,
        source_model=source_model,
        scan_mode=scan_mode,
    )

    console.print("\n[green]Persisted to:[/green]")
    for fmt, path in paths.items():
        console.print(f"  {fmt}: {path}")

    # Write run_metadata.json
    run_dir = output_path / run_id
    raw_prompt = data.get("raw_prompt", "")
    run_metadata = {
        "run_id": run_id,
        "source_model": source_model,
        "scan_mode": scan_mode,
        "parameter_definition_count": len(param_defs),
        "imported_from": json_path.name,
    }
    if object_category:
        run_metadata["object_category"] = object_category
    # Copy prompt traceability fields
    for tf in ("raw_prompt", "resolved_capability", "result_class", "source", "active_view"):
        val = data.get(tf, "")
        if val:
            run_metadata[tf] = val
    meta_path = run_dir / "run_metadata.json"
    meta_path.write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")
    console.print(f"  metadata: {meta_path}")

    if raw_prompt:
        console.print(f"  Raw prompt: [dim]{raw_prompt}[/dim]")

    # Write summary.md
    unique_names = {p.get("ParameterName", "") for p in param_defs}
    ro = sum(1 for p in param_defs if p.get("IsReadOnly", False))
    summary_path = run_dir / "summary.md"
    summary_lines = [
        f"# Parameter Schema Run: {run_id}\n",
        f"- **Source model:** {source_model}\n",
        f"- **Scan mode:** {scan_mode}\n",
    ]
    if raw_prompt:
        summary_lines.append(f"- **Prompt:** `{raw_prompt}`\n")
    summary_lines.extend([
        f"- **Parameter definitions:** {len(param_defs)}\n",
        f"- **Unique parameter names:** {len(unique_names)}\n",
        f"- **Read-only:** {ro}\n",
        f"- **Writable:** {len(param_defs) - ro}\n",
        f"- **Imported from:** `{json_path.name}`\n",
    ])
    summary_path.write_text("".join(summary_lines), encoding="utf-8")
    console.print(f"  summary: {summary_path}")

    console.print("\n[bold green]Parameter schema import complete.[/bold green]")


def _import_standard_inventory(data, run_id, source_model, scan_mode, json_path, output_dir):
    """Import a standard inventory JSON export."""
    import json
    from pathlib import Path

    from axiom_core.inventory.storage import persist_inventory

    elements = data.get("elements", [])
    elem_count = data.get("element_count", len(elements))
    type_count = data.get("type_count", 0)
    param_count = data.get("parameter_count", 0)
    object_category = data.get("object_category", "")

    console.print(f"  Run ID: [cyan]{run_id}[/cyan]")
    console.print(f"  Source model: [cyan]{source_model}[/cyan]")
    if object_category:
        console.print(f"  Object Category: [cyan]{object_category}[/cyan]")
    console.print(f"  Elements: {elem_count} instances, {type_count} types")
    console.print(f"  Parameters: {param_count}")

    output_path = Path(output_dir)
    paths = persist_inventory(
        elements=elements,
        output_dir=output_path,
        run_id=run_id,
        source_model=source_model,
    )

    console.print("\n[green]Persisted to:[/green]")
    for fmt, path in paths.items():
        console.print(f"  {fmt}: {path}")

    # Write run_metadata.json
    run_dir = output_path / run_id
    category_counts = data.get("category_counts", {})
    instance_count = elem_count - type_count if elem_count > type_count else elem_count
    run_metadata = {
        "run_id": run_id,
        "source_model": source_model,
        "scan_mode": scan_mode,
        "instance_count": instance_count,
        "type_count": type_count,
        "parameter_count": param_count,
        "category_counts": category_counts,
        "imported_from": json_path.name,
    }
    if object_category:
        run_metadata["object_category"] = object_category
    # Copy prompt traceability fields
    for tf in ("raw_prompt", "resolved_capability", "result_class", "source", "active_view"):
        val = data.get(tf, "")
        if val:
            run_metadata[tf] = val
    meta_path = run_dir / "run_metadata.json"
    meta_path.write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")
    console.print(f"  metadata: {meta_path}")

    raw_prompt = data.get("raw_prompt", "")
    if raw_prompt:
        console.print(f"  Raw prompt: [dim]{raw_prompt}[/dim]")

    # Write summary.md
    summary_path = run_dir / "summary.md"
    summary_lines = [
        f"# Inventory Run: {run_id}\n",
        f"- **Source model:** {source_model}\n",
        f"- **Scan mode:** {scan_mode or 'unknown'}\n",
    ]
    if raw_prompt:
        summary_lines.append(f"- **Prompt:** `{raw_prompt}`\n")
    summary_lines.extend([
        f"- **Elements:** {instance_count} instances, {type_count} types\n",
        f"- **Parameters:** {param_count}\n",
        f"- **Imported from:** `{json_path.name}`\n",
    ])
    summary_path.write_text("".join(summary_lines), encoding="utf-8")
    console.print(f"  summary: {summary_path}")

    console.print("\n[bold green]Import complete.[/bold green]")
    console.print("[dim]Run: axiom inventory-summary --latest[/dim]")


@cli.command("inventory-import-batch")
@click.option("--dir", "import_dir", default=None, type=click.Path(exists=True),
              help="Directory containing JSON export files to import")
@click.option("--manifest", "manifest_path", default=None, type=click.Path(exists=True),
              help="Path to parameter_schema_manifest JSON from plan execution")
@click.option("--scan-mode", "scan_mode_filter", default=None,
              help="Only import files matching this scan_mode (e.g. category_parameter_schema)")
@click.option("--output-dir", default="artifacts/model_inventory_runs", type=click.Path(),
              help="Base output directory for imported runs")
def inventory_import_batch(import_dir, manifest_path, scan_mode_filter, output_dir):
    """Batch import all matching JSON exports from a directory or manifest.

    Scans the directory for inventory JSON files and imports each one.
    Optionally filter by scan_mode to only import specific types.

    With --manifest, reads a parameter_schema_manifest JSON produced by
    'Run InventoryModel parameter schema plan' and imports only the
    successful exports listed in the manifest.
    """
    import json as json_mod
    from pathlib import Path

    if not import_dir and not manifest_path:
        console.print("[red]Either --dir or --manifest is required.[/red]")
        return

    # If manifest provided, extract export paths from it
    if manifest_path:
        manifest_file = Path(manifest_path)
        try:
            with open(manifest_file, "r", encoding="utf-8-sig") as f:
                manifest_data = json_mod.load(f)
        except (json_mod.JSONDecodeError, OSError) as e:
            console.print(f"[red]Failed to read manifest: {e}[/red]")
            return

        exports = manifest_data.get("exports", [])
        successful_exports = [
            e for e in exports
            if e.get("status") == "success" and e.get("export_path")
        ]
        failed_exports = [e for e in exports if e.get("status") == "failed"]
        skipped_exports = [
            e for e in exports
            if e.get("status") not in ("success", "failed")
        ]

        console.print("\n[bold blue]Batch Import from Manifest[/bold blue]")
        console.print(f"[dim]Manifest: {manifest_file}[/dim]")
        console.print(f"[dim]Source model: {manifest_data.get('source_model', '')}[/dim]")
        console.print(f"[dim]Plan ID: {manifest_data.get('plan_id', '')}[/dim]")
        console.print(f"[dim]Total entries: {len(exports)} "
                      f"(success={len(successful_exports)}, "
                      f"failed={len(failed_exports)}, "
                      f"skipped={len(skipped_exports)})[/dim]")
        console.print()

        # Detect duplicate export_path values (export collision)
        export_paths = [
            e.get("export_path", "") for e in successful_exports
            if e.get("export_path")
        ]
        unique_paths = set(export_paths)
        if len(export_paths) != len(unique_paths):
            dup_count = len(export_paths) - len(unique_paths)
            console.print(
                f"[red bold]WARNING: Export path collision detected![/red bold]\n"
                f"  Successful entries: {len(export_paths)}\n"
                f"  Distinct export paths: {len(unique_paths)}\n"
                f"  Duplicate export paths: {dup_count}\n"
            )
            console.print(
                "[red]Multiple categories exported to the same file, causing "
                "data loss. Redeploy with the export collision fix and rerun "
                "the plan.[/red]\n"
            )
            # Show which paths are duplicated
            from collections import Counter as _Counter
            path_counts = _Counter(export_paths)
            dups = {p: c for p, c in path_counts.items() if c > 1}
            for dp, dc in sorted(dups.items(), key=lambda x: -x[1])[:10]:
                console.print(f"  [red]-[/red] {dp} ({dc} categories)")
            if len(dups) > 10:
                console.print(f"  [dim]... and {len(dups) - 10} more[/dim]")
            console.print()

        if failed_exports:
            console.print("[yellow]Failed categories (not imported):[/yellow]")
            for fe in failed_exports:
                cat = fe.get("category", "?")
                err = fe.get("error_message", "")
                console.print(f"  [yellow]-[/yellow] {cat}: {err}")
            console.print()

        if not successful_exports:
            console.print("[red]No successful exports in manifest — nothing to import.[/red]")
            if failed_exports:
                console.print("[dim]All categories failed. Fix failures and retry:[/dim]")
                console.print("[dim]  Run InventoryModel parameter schema plan resume[/dim]")
            return

        json_files = []
        missing_count = 0
        for exp in successful_exports:
            p = Path(exp["export_path"])
            if p.exists():
                json_files.append(p)
            else:
                cat = exp.get("category", p.name)
                console.print(f"  [yellow]WARN[/yellow] Missing export file: {p} "
                              f"(category: {cat})")
                missing_count += 1
        if missing_count:
            console.print(f"[yellow]{missing_count} export file(s) missing.[/yellow]\n")
    else:
        dir_path = Path(import_dir)
        json_files = sorted(dir_path.glob("*.json"), key=lambda p: p.stat().st_mtime)

    if not json_files:
        source_label = manifest_path if manifest_path else import_dir
        console.print(f"[red]No JSON files found from {source_label}[/red]")
        return

    if not manifest_path:
        console.print("\n[bold blue]Batch Import[/bold blue]")
        console.print(f"[dim]Directory: {dir_path}[/dim]")
        console.print(f"[dim]JSON files found: {len(json_files)}[/dim]")
        if scan_mode_filter:
            console.print(f"[dim]Filter: scan_mode={scan_mode_filter}[/dim]")
        console.print()

    imported = 0
    skipped = 0
    errors = 0

    for json_path in json_files:
        try:
            with open(json_path, "r", encoding="utf-8-sig") as f:
                data = json_mod.load(f)
        except (json_mod.JSONDecodeError, OSError) as e:
            console.print(f"  [red]SKIP[/red] {json_path.name}: {e}")
            errors += 1
            continue

        file_scan_mode = data.get("scan_mode", "")

        # Filter by scan_mode if specified
        if scan_mode_filter and file_scan_mode != scan_mode_filter:
            console.print(f"  [dim]SKIP[/dim] {json_path.name} (scan_mode={file_scan_mode})")
            skipped += 1
            continue

        run_id = data.get("run_id", json_path.stem)
        source_model = data.get("source_model", "")

        console.print(f"  [cyan]Importing[/cyan] {json_path.name} "
                      f"(scan_mode={file_scan_mode}, run_id={run_id})")

        is_param_schema = file_scan_mode in (
            "parameter_schema", "category_parameter_schema",
        ) or "parameter_definitions" in data
        is_object_schema = file_scan_mode in ("object_schema", "category_object_schema")

        try:
            if is_param_schema:
                _import_parameter_schema(
                    data, run_id, source_model, file_scan_mode, json_path, output_dir,
                )
            elif is_object_schema:
                _import_object_schema(
                    data, run_id, source_model, file_scan_mode, json_path, output_dir,
                )
            else:
                _import_standard_inventory(
                    data, run_id, source_model, file_scan_mode, json_path, output_dir,
                )
            imported += 1
        except Exception as e:
            console.print(f"  [red]ERROR[/red] {json_path.name}: {e}")
            errors += 1

    console.print("\n[bold green]Batch import complete.[/bold green]")
    console.print(f"  Imported: {imported}")
    console.print(f"  Skipped: {skipped}")
    if errors:
        console.print(f"  Errors: {errors}")
    console.print("[dim]Run: axiom inventory-summary --latest[/dim]")


@cli.command("inventory-export")
@click.option("--file", "json_file", required=True, type=click.Path(exists=True),
              help="Path to Revit-exported inventory JSON file")
@click.option("--chunk-by", "chunk_by", default=None,
              type=click.Choice(["discipline"]),
              help="Chunk extraction by discipline groups")
@click.option("--discipline", "discipline_filter", default=None,
              help="Extract only a single discipline (e.g. Architectural, Structural)")
@click.option("--output-dir", default="artifacts/inventory_runs", type=click.Path(),
              help="Base directory for inventory run outputs")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
@click.option("--review-output", is_flag=True,
              help="No-op for discipline mode (review files always created). "
              "Reserved for future non-discipline export modes.")
def inventory_export(json_file, chunk_by, discipline_filter, output_dir, run_id, review_output):
    """Import and extract inventory by discipline chunks.

    When using --chunk-by discipline, CSV, XLSX, and Markdown review
    files are always created for each discipline folder. The
    --review-output flag is accepted but has no additional effect in
    discipline mode (unlike test-grids/test-levels where it controls
    review file generation).
    """
    import json as json_mod
    from datetime import datetime, timezone
    from pathlib import Path

    console.print("\n[bold blue]Axiom Inventory Export[/bold blue]\n")

    json_path = Path(json_file)
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json_mod.load(f)

    elements = data.get("elements", data.get("Elements", []))
    source_model = data.get("document_title", data.get("DocumentTitle", ""))

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("inv_%Y%m%d_%H%M%S")

    output_path = Path(output_dir)

    console.print(f"[dim]Run ID:     {run_id}[/dim]")
    console.print(f"[dim]Source:     {source_model}[/dim]")
    console.print(f"[dim]Elements:   {len(elements)}[/dim]")

    if chunk_by == "discipline" or discipline_filter:
        from axiom_core.inventory.discipline_export import run_discipline_extraction

        console.print("[dim]Chunk by:   discipline[/dim]")
        if discipline_filter:
            console.print(f"[dim]Discipline: {discipline_filter}[/dim]")
        console.print()

        if not elements:
            console.print(
                "[bold yellow]WARNING:[/bold yellow] Input inventory JSON "
                "contains no element-level records. Discipline split requires "
                "full-detail inventory export. Summary-mode exports cannot be "
                "classified by discipline.\n"
            )

        paths = run_discipline_extraction(
            elements, output_path, run_id,
            source_model=source_model,
            discipline_filter=discipline_filter,
        )

        console.print("[bold green]Discipline extraction complete.[/bold green]\n")
        for key, p in paths.items():
            if key == "warning":
                continue
            console.print(f"[dim]{key}: {p}[/dim]")
    else:
        # Standard flat import (no chunking)
        from axiom_core.inventory.storage import persist_inventory

        paths = persist_inventory(
            elements, output_path, run_id,
            source_model=source_model,
        )

        console.print("[bold green]Export complete.[/bold green]\n")
        for key, p in paths.items():
            console.print(f"[dim]{key}: {p}[/dim]")


def _get_plan_handoff_dir():
    """Return the LocalAppData handoff directory for plan files (Windows convention)."""
    import os
    from pathlib import Path

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        # Linux/CI fallback: use ~/.local/share/Axiom
        local_app_data = str(Path.home() / ".local" / "share")
    return Path(local_app_data) / "Axiom" / "inventory_plans"


def _write_plan_handoff(paths: dict, plan) -> None:
    """Copy plan JSON to LocalAppData handoff location for Revit pickup."""
    import shutil
    from pathlib import Path

    json_path = paths.get("json")
    if not json_path or not Path(json_path).exists():
        return

    handoff_dir = _get_plan_handoff_dir()

    # Write to latest/ subdirectory
    latest_dir = handoff_dir / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_plan = latest_dir / "parameter_schema_plan.json"
    shutil.copy2(str(json_path), str(latest_plan))

    # Also write flat copy for simpler lookup
    flat_plan = handoff_dir / "parameter_schema_plan.json"
    shutil.copy2(str(json_path), str(flat_plan))

    console.print("\n[bold]Revit handoff plan:[/bold]")
    console.print(f"  {latest_plan}")
    console.print(f"  {flat_plan}")


@cli.command("inventory-plan-status")
def inventory_plan_status():
    """Show status of the latest parameter schema plan and handoff paths."""
    import json as json_mod
    from pathlib import Path

    from axiom_core.inventory.extraction_planner import PRIORITY_CATEGORIES

    console.print("\n[bold blue]Parameter Schema Plan Status[/bold blue]\n")

    # Check repo plan
    repo_plans_dir = Path("artifacts/inventory_plans")
    repo_plan_path = None
    if repo_plans_dir.exists():
        plan_dirs = sorted(repo_plans_dir.iterdir(), reverse=True)
        for pd in plan_dirs:
            candidate = pd / "parameter_schema_plan.json"
            if candidate.exists():
                repo_plan_path = candidate
                break

    # Check handoff plans
    handoff_dir = _get_plan_handoff_dir()
    latest_handoff = handoff_dir / "latest" / "parameter_schema_plan.json"
    flat_handoff = handoff_dir / "parameter_schema_plan.json"

    console.print("[bold]Plan locations:[/bold]")
    console.print(f"  Repo:           {repo_plan_path or '(not found)'} "
                  f"{'[green]EXISTS[/green]' if repo_plan_path and repo_plan_path.exists() else '[red]MISSING[/red]'}")
    console.print(f"  Handoff latest: {latest_handoff} "
                  f"{'[green]EXISTS[/green]' if latest_handoff.exists() else '[red]MISSING[/red]'}")
    console.print(f"  Handoff flat:   {flat_handoff} "
                  f"{'[green]EXISTS[/green]' if flat_handoff.exists() else '[red]MISSING[/red]'}")

    # Load the best available plan
    plan_path = None
    for p in [latest_handoff, flat_handoff, repo_plan_path]:
        if p and p.exists():
            plan_path = p
            break

    if not plan_path:
        console.print("\n[red]No parameter_schema_plan.json found.[/red]")
        console.print("[dim]Generate one with: axiom inventory-plan --file <summary.json> --mode parameter-schema[/dim]")
        return

    try:
        plan_data = json_mod.loads(plan_path.read_text(encoding="utf-8"))
    except (json_mod.JSONDecodeError, OSError) as e:
        console.print(f"\n[red]Failed to read plan: {e}[/red]")
        return

    plan_id = plan_data.get("run_id", "")
    jobs = plan_data.get("jobs", [])
    source_model = plan_data.get("source_model", "")
    priority_lower = {p.lower() for p in PRIORITY_CATEGORIES}
    priority_jobs = [
        j for j in jobs
        if j.get("categories", []) and j["categories"][0].lower() in priority_lower
    ]

    console.print("\n[bold]Plan details:[/bold]")
    console.print(f"  Plan ID:             {plan_id}")
    console.print(f"  Source model:         {source_model}")
    console.print(f"  Total categories:    {len(jobs)}")
    console.print(f"  Priority categories: {len(priority_jobs)}")
    console.print(f"  Loaded from:         {plan_path}")

    console.print("\n[bold]Next Revit prompts:[/bold]")
    console.print("  [cyan]Run InventoryModel parameter schema plan max 10[/cyan]")
    console.print("  [cyan]Run InventoryModel parameter schema plan priority only[/cyan]")
    console.print("  [cyan]Run InventoryModel parameter schema plan[/cyan]")

    # Check for existing manifests
    exports_dir = handoff_dir.parent / "inventory_exports"
    if exports_dir.exists():
        manifests = sorted(exports_dir.glob("parameter_schema_manifest_*.json"), reverse=True)
        if manifests:
            console.print("\n[bold]Latest manifest:[/bold]")
            console.print(f"  {manifests[0]}")
            try:
                m_data = json_mod.loads(manifests[0].read_text(encoding="utf-8"))
                console.print(f"  Completed: {m_data.get('completed_categories', 0)}")
                console.print(f"  Failed:    {m_data.get('failed_categories', 0)}")
                console.print(f"  Skipped:   {m_data.get('skipped_categories', 0)}")
                if m_data.get("completed_categories", 0) > 0:
                    console.print(f"\n[dim]Import: axiom inventory-import-batch --manifest \"{manifests[0]}\"[/dim]")
            except (json_mod.JSONDecodeError, OSError):
                pass


@cli.command("inventory-plan")
@click.option("--file", "json_file", required=True, type=click.Path(exists=True),
              help="Path to Revit-exported summary inventory JSON file")
@click.option("--output-dir", default="artifacts/inventory_plans", type=click.Path(),
              help="Base directory for extraction plan outputs")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
@click.option("--max-group", "max_group", default=5000, type=int,
              help="Max elements in a discipline group job (default: 5000)")
@click.option("--isolate-threshold", "isolate_threshold", default=3000, type=int,
              help="Isolate a category if it exceeds this count (default: 3000)")
@click.option("--max-chunk", "max_chunk", default=5000, type=int,
              help="Max elements per chunk of a large category (default: 5000)")
@click.option("--mode", "plan_mode", default="extraction",
              type=click.Choice(["extraction", "parameter-schema"]),
              help="Plan mode: 'extraction' (default) or 'parameter-schema'")
def inventory_plan(json_file, output_dir, run_id, max_group, isolate_threshold, max_chunk, plan_mode):
    """Build an adaptive extraction plan from a summary-mode inventory export.

    Reads category counts from the summary JSON and produces a plan
    that groups small categories by discipline, isolates large categories,
    and chunks very large categories — all before any full-detail
    extraction runs.

    Outputs:
      - inventory_extraction_plan.json
      - inventory_extraction_plan.md
      - inventory_extraction_plan.xlsx
    """
    import json as json_mod
    from datetime import datetime, timezone
    from pathlib import Path

    from axiom_core.inventory.extraction_planner import (
        build_extraction_plan,
        build_parameter_schema_plan,
        generate_plan_outputs,
    )

    mode_label = "Parameter Schema Discovery" if plan_mode == "parameter-schema" else "Extraction"
    console.print(f"\n[bold blue]Axiom {mode_label} Planner[/bold blue]\n")

    json_path = Path(json_file)
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json_mod.load(f)

    # Extract category counts from summary-mode JSON
    category_counts: dict[str, int] = {}

    # Try structured category_counts field first
    if "category_counts" in data:
        category_counts = data["category_counts"]
    elif "CategoryCounts" in data:
        category_counts = data["CategoryCounts"]
    elif "elements" in data or "Elements" in data:
        # Fall back to counting from elements array if present
        elements = data.get("elements", data.get("Elements", []))
        if elements:
            for el in elements:
                cat = el.get("Category", el.get("category", "Unknown"))
                category_counts[cat] = category_counts.get(cat, 0) + 1
        else:
            console.print(
                "[bold yellow]WARNING:[/bold yellow] JSON has no element-level "
                "records and no category_counts field. Cannot build plan.\n"
            )
            return

    if not category_counts:
        console.print(
            "[bold yellow]WARNING:[/bold yellow] No category counts found in JSON. "
            "Cannot build extraction plan.\n"
        )
        return

    source_model = data.get("document_title", data.get("DocumentTitle", ""))
    total_instances = data.get("instance_count", data.get("InstanceCount", 0))
    total_types = data.get("type_count", data.get("TypeCount", 0))

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("plan_%Y%m%d_%H%M%S")

    console.print(f"[dim]Run ID:     {run_id}[/dim]")
    console.print(f"[dim]Source:     {source_model}[/dim]")
    console.print(f"[dim]Mode:       {plan_mode}[/dim]")
    console.print(f"[dim]Categories: {len(category_counts)}[/dim]")
    console.print(f"[dim]Instances:  {total_instances}[/dim]")
    if plan_mode != "parameter-schema":
        console.print(f"[dim]Thresholds: group={max_group}, isolate={isolate_threshold}, chunk={max_chunk}[/dim]")
    console.print()

    if plan_mode == "parameter-schema":
        plan = build_parameter_schema_plan(
            category_counts,
            run_id=run_id,
            source_model=source_model,
        )
    else:
        plan = build_extraction_plan(
            category_counts,
            run_id=run_id,
            source_model=source_model,
            total_instance_count=total_instances,
            total_type_count=total_types,
            max_group_elements=max_group,
            isolate_category_threshold=isolate_threshold,
            max_category_chunk_elements=max_chunk,
        )

    output_path = Path(output_dir)
    paths = generate_plan_outputs(plan, output_path, mode=plan_mode)

    console.print(f"[bold green]{mode_label} plan complete: {len(plan.jobs)} jobs[/bold green]\n")

    if plan.warnings:
        for w in plan.warnings:
            console.print(f"[bold yellow]WARNING:[/bold yellow] {w}")
        console.print()

    console.print("[bold]Repo plan:[/bold]")
    for key, p in paths.items():
        console.print(f"  {key}: {p}")

    # Write handoff copy to LocalAppData for Revit pickup (Windows only)
    if plan_mode == "parameter-schema":
        _write_plan_handoff(paths, plan)

    # Print quick job summary
    console.print("\n[bold]Planned Jobs:[/bold]")
    for j in plan.jobs:
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(j.risk_level, "white")
        console.print(
            f"  {j.sequence_number:2d}. [{risk_color}]{j.risk_level:6s}[/{risk_color}] "
            f"{j.discipline:15s} {j.extraction_scope:40s} "
            f"~{j.estimated_element_count:,} elements  [{j.strategy}]"
        )


@cli.command("inventory-combine")
@click.option("--manifest", "manifest_file", default=None, type=click.Path(exists=True),
              help="Path to batch manifest JSON file")
@click.option("--batch-dir", "batch_dir", default=None, type=click.Path(exists=True),
              help="Directory containing batch JSON files (alternative to --manifest)")
@click.option("--output-dir", default="artifacts/inventory_runs", type=click.Path(),
              help="Base directory for combined inventory output")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
@click.option("--chunk-by", "chunk_by", default=None,
              type=click.Choice(["discipline"]),
              help="After combining, chunk by discipline groups")
def inventory_combine(manifest_file, batch_dir, output_dir, run_id, chunk_by):
    """Combine multiple batch inventory JSON files into a single output.

    Batched extraction writes one JSON file per batch. This command
    merges all batch files into a single inventory and optionally
    runs discipline extraction on the combined result.

    Use --manifest to point at the manifest JSON written by Revit,
    or --batch-dir to scan a directory for batch_*.json files.
    """
    import json as json_mod
    from datetime import datetime, timezone
    from pathlib import Path

    console.print("\n[bold blue]Axiom Inventory Combine[/bold blue]\n")

    batch_files: list[Path] = []

    if manifest_file:
        manifest_path = Path(manifest_file)
        with open(manifest_path, "r", encoding="utf-8-sig") as f:
            manifest = json_mod.load(f)
        batch_paths = manifest.get("batch_files", [])
        for bp in batch_paths:
            p = Path(bp)
            if p.exists():
                batch_files.append(p)
            else:
                console.print(f"[yellow]WARNING: batch file not found: {bp}[/yellow]")
        source_model = manifest.get("source_model", "")
    elif batch_dir:
        bd = Path(batch_dir)
        batch_files = sorted(bd.glob("batch_*.json"))
        source_model = ""
    else:
        console.print("[red]Provide --manifest or --batch-dir[/red]")
        return

    if not batch_files:
        console.print("[red]No batch files found.[/red]")
        return

    console.print(f"[dim]Found {len(batch_files)} batch file(s)[/dim]")

    # Merge all batch elements and counts
    all_elements: list = []
    merged_category_counts: dict[str, int] = {}
    total_errors = 0
    total_instances = 0
    total_types = 0
    total_params = 0

    for bf in batch_files:
        console.print(f"[dim]  Reading: {bf.name}[/dim]")
        with open(bf, "r", encoding="utf-8-sig") as f:
            data = json_mod.load(f)

        elements = data.get("elements", data.get("Elements", []))
        all_elements.extend(elements)

        cat_counts = data.get("category_counts", data.get("CategoryCounts", {}))
        for cat, count in cat_counts.items():
            merged_category_counts[cat] = merged_category_counts.get(cat, 0) + count

        total_errors += data.get("error_count", 0)
        total_instances += data.get("instance_count", data.get("InstanceCount", 0))
        total_types += data.get("type_count", data.get("TypeCount", 0))
        total_params += data.get("parameter_count", data.get("ParameterCount", 0))

        if not source_model:
            source_model = data.get("source_model", data.get("document_title", ""))

    console.print(f"\n[dim]Combined: {len(all_elements)} elements from {len(batch_files)} batches[/dim]")
    console.print(f"[dim]Instances: {total_instances}, Types: {total_types}, Errors: {total_errors}[/dim]")

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("combined_%Y%m%d_%H%M%S")

    output_path = Path(output_dir)

    if chunk_by == "discipline":
        from axiom_core.inventory.discipline_export import run_discipline_extraction

        console.print("[dim]Running discipline extraction on combined data...[/dim]\n")

        if not all_elements:
            console.print(
                "[bold yellow]WARNING:[/bold yellow] Combined inventory has no "
                "element-level records. Cannot run discipline extraction.\n"
            )

        paths = run_discipline_extraction(
            all_elements, output_path, run_id,
            source_model=source_model,
        )

        console.print("[bold green]Discipline extraction complete.[/bold green]\n")
        for key, p in paths.items():
            if key == "warning":
                continue
            console.print(f"[dim]{key}: {p}[/dim]")
    else:
        # Standard flat merge
        from axiom_core.inventory.storage import persist_inventory

        paths = persist_inventory(
            all_elements, output_path, run_id,
            source_model=source_model,
        )

        console.print("[bold green]Combine complete.[/bold green]\n")
        for key, p in paths.items():
            console.print(f"[dim]{key}: {p}[/dim]")

    # Write combined metadata
    run_dir = output_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    combined_meta = {
        "run_id": run_id,
        "source_model": source_model,
        "batch_count": len(batch_files),
        "batch_files": [str(bf) for bf in batch_files],
        "total_elements": len(all_elements),
        "instance_count": total_instances,
        "type_count": total_types,
        "parameter_count": total_params,
        "error_count": total_errors,
        "category_counts": merged_category_counts,
        "combined_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = run_dir / "run_metadata.json"
    meta_path.write_text(json_mod.dumps(combined_meta, indent=2), encoding="utf-8")
    console.print(f"[dim]metadata: {meta_path}[/dim]")

    console.print(f"\n[bold green]Combined {len(batch_files)} batches "
                  f"({len(all_elements)} elements) into {run_id}[/bold green]")


@cli.command("parameter-registry-build")
@click.option("--from-inventory", "input_dir", required=True,
              type=click.Path(exists=True),
              help="Base directory containing model_inventory_runs with parameter schema outputs")
@click.option("--output-dir", default="artifacts/parameter_registry_candidates",
              type=click.Path(),
              help="Output directory for registry candidate")
@click.option("--run-id", "run_id", default=None,
              help="Custom run identifier (defaults to timestamp)")
@click.option("--object-registry", "object_registry_dir", default=None,
              type=click.Path(exists=True),
              help="Path to object registry candidate for coverage analysis")
def parameter_registry_build(input_dir, output_dir, run_id, object_registry_dir):
    """Build a property registry candidate from multiple category parameter schema runs.

    Scans model_inventory_runs for parameter_schema.parquet files, deduplicates
    by (ObjectCategory, ClassName, ParameterName, BuiltInParameterId, DataTypeId,
    StorageType, IsInstanceParam, IsTypeParam), and produces a consolidated
    registry candidate with coverage summary.
    """
    import json as json_mod
    from collections import Counter
    from datetime import datetime, timezone
    from pathlib import Path

    import pyarrow as pa
    import pyarrow.parquet as pq
    from axiom_core.inventory.storage import PARAMETER_SCHEMA_PARQUET_SCHEMA

    console.print("\n[bold blue]Axiom Property Registry Builder[/bold blue]\n")

    input_path = Path(input_dir)
    ps_files = sorted(input_path.rglob("parameter_schema.parquet"))

    if not ps_files:
        console.print(f"[red]No parameter_schema.parquet files found in {input_path}[/red]")
        return

    console.print(f"[dim]Found {len(ps_files)} parameter schema file(s)[/dim]")

    # Collect all rows with provenance tracking
    all_rows: list[dict] = []
    source_runs: list[str] = []
    source_models: set[str] = set()
    run_ids_seen: set[str] = set()

    for ps_file in ps_files:
        run_name = ps_file.parent.name
        source_runs.append(run_name)
        console.print(f"[dim]  Reading: {run_name}/parameter_schema.parquet[/dim]")

        # Read run_metadata.json if available for provenance
        meta_path = ps_file.parent / "run_metadata.json"
        run_meta: dict = {}
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8-sig") as mf:
                run_meta = json_mod.load(mf)

        table = pq.read_table(str(ps_file))
        df = {col: table.column(col).to_pylist() for col in table.schema.names}
        for i in range(table.num_rows):
            row = {col: df[col][i] for col in df}
            if not row.get("parameter_name"):
                continue
            # Track provenance
            row["_source_run"] = run_name
            row["_source_model"] = row.get("source_model", run_meta.get("source_model", ""))
            row["_run_id"] = row.get("run_id", run_name)
            if row["_source_model"]:
                source_models.add(row["_source_model"])
            run_ids_seen.add(row["_run_id"])
            all_rows.append(row)

    console.print(f"\n[dim]Total parameter definitions before dedup: {len(all_rows)}[/dim]")

    # Deduplicate by expanded composite key
    seen: dict[tuple, dict] = {}
    for row in all_rows:
        key = (
            row.get("category", ""),
            row.get("class_name", ""),
            row.get("parameter_name", ""),
            row.get("built_in_parameter_id", ""),
            row.get("data_type_id", ""),
            row.get("storage_type", ""),
            row.get("is_instance_param", False),
            row.get("is_type_param", False),
        )
        if key in seen:
            existing = seen[key]
            existing["observed_count"] = (
                (existing.get("observed_count") or 0) +
                (row.get("observed_count") or 0)
            )
            # Track multi-source provenance
            existing.setdefault("_all_source_models", set()).add(row["_source_model"])
            existing.setdefault("_all_run_ids", set()).add(row["_run_id"])
        else:
            entry = dict(row)
            entry["_all_source_models"] = {row["_source_model"]}
            entry["_all_run_ids"] = {row["_run_id"]}
            seen[key] = entry

    deduped = list(seen.values())
    console.print(f"[dim]Unique parameter definitions after dedup: {len(deduped)}[/dim]")

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("registry_%Y%m%d_%H%M%S")

    out_path = Path(output_dir) / run_id
    out_path.mkdir(parents=True, exist_ok=True)

    # Prepare final rows with multi-source fields
    final_rows: list[dict] = []
    for row in deduped:
        final = {
            "ObjectCategory": row.get("category", ""),
            "ClassName": row.get("class_name", ""),
            "ParameterName": row.get("parameter_name", ""),
            "StorageType": row.get("storage_type", ""),
            "BuiltInParameterId": row.get("built_in_parameter_id", ""),
            "DataTypeId": row.get("data_type_id", ""),
            "DataTypeLabel": row.get("data_type_label", ""),
            "GroupTypeId": row.get("group_type_id", ""),
            "GroupTypeLabel": row.get("group_type_label", ""),
            "IsMeasurableSpec": row.get("is_measurable_spec", False),
            "UnitTypeId": row.get("unit_type_id", ""),
            "UnitLabel": row.get("unit_label", ""),
            "DisciplineLabel": row.get("discipline_label", ""),
            "IsReadOnly": row.get("is_read_only", False),
            "IsInstanceParam": row.get("is_instance_param", False),
            "IsTypeParam": row.get("is_type_param", False),
            "ObservedCount": row.get("observed_count", 0),
            "ObservedOnCategories": row.get("observed_on_categories", ""),
            "ObservedOnClasses": row.get("observed_on_classes", ""),
            "SourceModels": ", ".join(sorted(row.get("_all_source_models", set()))),
            "RevitVersions": "",
            "RunIds": ", ".join(sorted(row.get("_all_run_ids", set()))),
        }
        final_rows.append(final)

    # Write JSONL
    jsonl_path = out_path / "revit_property_registry.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in final_rows:
            f.write(json_mod.dumps(row, default=str) + "\n")
    console.print(f"  jsonl: {jsonl_path}")

    # Write Parquet (using PARAMETER_SCHEMA schema for compatibility)
    parquet_path = out_path / "revit_property_registry.parquet"
    rows_for_pq = []
    for row in final_rows:
        rows_for_pq.append({
            "run_id": run_id,
            "source_model": row["SourceModels"],
            "scan_mode": "registry",
            "category": row["ObjectCategory"],
            "class_name": row["ClassName"],
            "parameter_name": row["ParameterName"],
            "storage_type": row["StorageType"],
            "built_in_parameter_id": row["BuiltInParameterId"],
            "is_read_only": row["IsReadOnly"],
            "is_instance_param": row["IsInstanceParam"],
            "is_type_param": row["IsTypeParam"],
            "observed_count": row["ObservedCount"],
            "observed_on_categories": row["ObservedOnCategories"],
            "observed_on_classes": row["ObservedOnClasses"],
            "data_type_id": row["DataTypeId"],
            "data_type_label": row["DataTypeLabel"],
            "group_type_id": row["GroupTypeId"],
            "group_type_label": row["GroupTypeLabel"],
            "is_measurable_spec": row["IsMeasurableSpec"],
            "unit_type_id": row["UnitTypeId"],
            "unit_label": row["UnitLabel"],
            "discipline_label": row["DisciplineLabel"],
        })
    if not rows_for_pq:
        rows_for_pq = [dict.fromkeys(PARAMETER_SCHEMA_PARQUET_SCHEMA.names)]
    arrays = {}
    for fld in PARAMETER_SCHEMA_PARQUET_SCHEMA:
        arrays[fld.name] = [r.get(fld.name) for r in rows_for_pq]
    table = pa.table(arrays, schema=PARAMETER_SCHEMA_PARQUET_SCHEMA)
    pq.write_table(table, str(parquet_path))
    console.print(f"  parquet: {parquet_path}")

    # Coverage analysis
    categories_with_definitions = {r["ObjectCategory"] for r in final_rows if r["ObjectCategory"]}
    unique_names = {r["ParameterName"] for r in final_rows}
    ro_count = sum(1 for r in final_rows if r["IsReadOnly"])
    instance_count = sum(1 for r in final_rows if r["IsInstanceParam"])
    type_count = sum(1 for r in final_rows if r["IsTypeParam"])
    cat_counter = Counter(r["ObjectCategory"] for r in final_rows)
    dt_counter = Counter(r["DataTypeLabel"] for r in final_rows if r["DataTypeLabel"])
    grp_counter = Counter(r["GroupTypeLabel"] for r in final_rows if r["GroupTypeLabel"])

    # Scan run_metadata.json files to find all executed categories
    # (including those with zero parameter definitions)
    executed_categories: set[str] = set()
    executed_zero_defs: set[str] = set()
    for ps_file in ps_files:
        meta_file = ps_file.parent / "run_metadata.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8-sig") as mf:
                rmeta = json_mod.load(mf)
            obj_cat = rmeta.get("object_category", "")
            if obj_cat:
                executed_categories.add(obj_cat)
                if rmeta.get("parameter_definition_count", 0) == 0:
                    executed_zero_defs.add(obj_cat)
    # Categories from parquet rows are also executed
    executed_categories.update(categories_with_definitions)
    # A category that gained definitions in a later run is not truly zero-defs
    executed_zero_defs -= categories_with_definitions

    # Check coverage against object registry if provided
    discovered_categories: set[str] = set()
    if object_registry_dir:
        obj_reg_path = Path(object_registry_dir)
        obj_parquet_files = list(obj_reg_path.rglob("revit_object_registry.parquet"))
        for opf in obj_parquet_files:
            ot = pq.read_table(str(opf))
            if "category" in ot.schema.names:
                discovered_categories.update(
                    c for c in ot.column("category").to_pylist() if c
                )
        elem_parquet_files = list(obj_reg_path.rglob("elements.parquet"))
        for epf in elem_parquet_files:
            et = pq.read_table(str(epf))
            if "category" in et.schema.names:
                discovered_categories.update(
                    c for c in et.column("category").to_pylist() if c
                )

    not_executed = sorted(discovered_categories - executed_categories) if discovered_categories else []
    executed_matching_discovered = sorted(
        executed_categories & discovered_categories
    ) if discovered_categories else []

    # Priority coverage analysis
    from axiom_core.inventory.extraction_planner import PRIORITY_CATEGORIES
    priority_lower = {p.lower(): p for p in PRIORITY_CATEGORIES}
    covered_priority = sorted(
        c for c in categories_with_definitions if c.lower() in priority_lower
    )
    executed_priority = sorted(
        c for c in executed_categories if c.lower() in priority_lower
    )
    missing_priority = sorted(
        p for p in PRIORITY_CATEGORIES if p.lower() not in {c.lower() for c in executed_categories}
    )

    # Write summary
    summary_path = out_path / "summary.md"
    summary_lines = [
        f"# Property Registry Candidate: {run_id}\n",
        f"- **Source runs:** {len(source_runs)}\n",
        f"- **Source models:** {', '.join(sorted(source_models)) or '(unknown)'}\n",
        f"- **Total definitions before dedup:** {len(all_rows)}\n",
        f"- **Total unique definitions:** {len(final_rows)}\n",
        f"- **Unique parameter names:** {len(unique_names)}\n",
        f"- **Read-only:** {ro_count}\n",
        f"- **Writable:** {len(final_rows) - ro_count}\n",
        f"- **Instance params:** {instance_count}\n",
        f"- **Type params:** {type_count}\n",
        "\n## Coverage Breakdown\n",
    ]
    if discovered_categories:
        summary_lines.append(
            f"- **Discovered object categories:** {len(discovered_categories)}\n"
        )
    summary_lines.extend([
        f"- **Categories executed successfully:** {len(executed_categories)}\n",
        f"- **Categories with parameter definitions:** {len(categories_with_definitions)}\n",
        f"- **Categories with zero parameter definitions:** {len(executed_zero_defs)}\n",
    ])
    if discovered_categories:
        summary_lines.extend([
            f"- **Executed categories matching discovered:** "
            f"{len(executed_matching_discovered)}\n",
            f"- **Categories not executed/imported:** {len(not_executed)}\n",
        ])
    summary_lines.extend([
        f"- **Priority categories executed:** "
        f"{len(executed_priority)} / {len(PRIORITY_CATEGORIES)}\n",
        f"- **Priority categories with definitions:** "
        f"{len(covered_priority)} / {len(PRIORITY_CATEGORIES)}\n",
        f"- **Priority categories missing:** {len(missing_priority)}\n",
    ])

    summary_lines.append("\n## Output Paths\n")
    summary_lines.append(f"- JSONL: `{out_path / 'revit_property_registry.jsonl'}`\n")
    summary_lines.append(f"- Parquet: `{out_path / 'revit_property_registry.parquet'}`\n")

    summary_lines.append("\n## Top Categories by Property Count\n")
    for cat, cnt in cat_counter.most_common(20):
        summary_lines.append(f"- {cat}: {cnt}\n")
    summary_lines.append("\n## Top Data Types\n")
    for dt, cnt in dt_counter.most_common(15):
        summary_lines.append(f"- {dt}: {cnt}\n")
    summary_lines.append("\n## Top Parameter Groups\n")
    for grp, cnt in grp_counter.most_common(15):
        summary_lines.append(f"- {grp}: {cnt}\n")

    if covered_priority:
        summary_lines.append("\n## Covered Priority Categories\n")
        for pc in covered_priority:
            cnt = cat_counter.get(pc, 0)
            summary_lines.append(f"- {pc}: {cnt} definitions\n")
    if missing_priority:
        summary_lines.append("\n## Missing Priority Categories\n")
        for mp in missing_priority:
            summary_lines.append(f"- {mp}\n")
    if executed_zero_defs:
        summary_lines.append("\n## Executed With Zero Parameter Definitions\n")
        summary_lines.append(
            "These categories were scanned successfully but had no parameter "
            "definitions. This is expected for categories like tags, annotation "
            "symbols, and internal Revit types.\n\n"
        )
        for zc in sorted(executed_zero_defs):
            summary_lines.append(f"- {zc}\n")
    if not_executed:
        summary_lines.append("\n## Not Executed / Not Imported\n")
        summary_lines.append(
            "These categories exist in the object registry but have not been "
            "scanned for parameter schema yet.\n\n"
        )
        for ne in not_executed:
            summary_lines.append(f"- {ne}\n")
    summary_lines.append("\n## Source Runs\n")
    for sr in source_runs:
        summary_lines.append(f"- {sr}\n")
    summary_path.write_text("".join(summary_lines), encoding="utf-8")
    console.print(f"  summary: {summary_path}")

    # Write metadata
    meta = {
        "run_id": run_id,
        "source_runs": source_runs,
        "source_models": sorted(source_models),
        "run_ids": sorted(run_ids_seen),
        "before_dedup_count": len(all_rows),
        "after_dedup_count": len(final_rows),
        "unique_parameter_names": len(unique_names),
        "categories_with_definitions": sorted(categories_with_definitions),
        "categories_executed_successfully": sorted(executed_categories),
        "categories_with_zero_definitions": sorted(executed_zero_defs),
        "categories_not_executed": not_executed,
        "discovered_object_categories": sorted(discovered_categories) if discovered_categories else [],
        "executed_matching_discovered": executed_matching_discovered,
        "covered_priority_categories": covered_priority,
        "executed_priority_categories": executed_priority,
        "missing_priority_categories": missing_priority,
        "category_with_definitions_count": len(categories_with_definitions),
        "category_executed_count": len(executed_categories),
        "category_zero_defs_count": len(executed_zero_defs),
        "read_only_count": ro_count,
        "writable_count": len(final_rows) - ro_count,
        "instance_param_count": instance_count,
        "type_param_count": type_count,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "output_paths": {
            "jsonl": str(out_path / "revit_property_registry.jsonl"),
            "parquet": str(out_path / "revit_property_registry.parquet"),
            "summary": str(summary_path),
        },
    }
    meta_path = out_path / "run_metadata.json"
    meta_path.write_text(json_mod.dumps(meta, indent=2), encoding="utf-8")
    console.print(f"  metadata: {meta_path}")

    # Console summary
    console.print(f"\n[bold green]Property registry built: {len(final_rows)} unique definitions "
                  f"from {len(source_runs)} runs[/bold green]")
    console.print(f"  Categories executed: {len(executed_categories)}")
    console.print(f"  Categories with definitions: {len(categories_with_definitions)}")
    console.print(f"  Categories with zero definitions: {len(executed_zero_defs)}")
    if discovered_categories:
        console.print(f"  Discovered object categories: {len(discovered_categories)}")
        console.print(f"  Not executed/imported: {len(not_executed)}")
    console.print(f"  Priority coverage: {len(executed_priority)}/{len(PRIORITY_CATEGORIES)} "
                  f"executed, {len(covered_priority)}/{len(PRIORITY_CATEGORIES)} with definitions")
    if missing_priority:
        console.print(f"[yellow]Missing priority categories: "
                      f"{', '.join(missing_priority)}[/yellow]")
    if not_executed:
        console.print(f"[dim]{len(not_executed)} categories not yet executed. "
                      f"Use plan execution queue to scan remaining categories.[/dim]")


@cli.command("set-parameter-value")
@click.argument("prompt_text", nargs=-1, required=True)
@click.option("--registry", "registry_path", default=None,
              type=click.Path(exists=True),
              help="Path to revit_property_registry.jsonl")
@click.option("--registry-dir", "registry_dir", default=None,
              type=click.Path(exists=True),
              help="Path to directory containing revit_property_registry.jsonl")
@click.option("--artifact-dir", "artifact_dir",
              default="artifacts/parameter_edit_runs",
              help="Base directory for evidence artifacts")
@click.option("--model-name", "model_name", default="",
              help="Revit model name for evidence")
@click.option("--simulate/--no-simulate", default=True,
              help="Simulation mode (no live Revit connection)")
def set_parameter_value(prompt_text, registry_path, registry_dir,
                        artifact_dir, model_name, simulate):
    """Preview or apply a constrained text parameter edit.

    v0 constraints: text parameters only, instance only, writable only,
    category-constrained, max 5 elements, preview by default.

    \b
    Examples:
      axiom set-parameter-value "Set Comments to Axiom test 001 for 3 Walls"
      axiom set-parameter-value "Apply Set Mark to AX-TEST for 2 Doors"
    """
    from pathlib import Path

    from axiom_core.set_parameter_value import (
        load_registry_jsonl,
        parse_set_parameter_prompt,
        run_set_parameter_preview,
        validate_against_registry,
        write_evidence,
    )

    prompt = " ".join(prompt_text)
    console.print("\n[bold blue]Axiom SetParameterValue v0[/bold blue]\n")
    console.print(f"[dim]Prompt: {prompt}[/dim]")

    # Parse prompt
    req = parse_set_parameter_prompt(prompt)
    if req.parse_errors:
        for err in req.parse_errors:
            console.print(f"[red]Parse error: {err}[/red]")
        return

    console.print(f"[dim]Mode: {req.mode}[/dim]")
    console.print(f"[dim]Category: {req.category}[/dim]")
    console.print(f"[dim]Parameter: {req.parameter_name}[/dim]")
    console.print(f'[dim]Value: "{req.value}"[/dim]')
    console.print(f"[dim]Count: {req.element_count}[/dim]")

    # Load registry
    registry_entries: list[dict] = []
    if registry_path:
        registry_entries = load_registry_jsonl(registry_path)
    elif registry_dir:
        jsonl_path = Path(registry_dir) / "revit_property_registry.jsonl"
        if jsonl_path.exists():
            registry_entries = load_registry_jsonl(str(jsonl_path))
    else:
        # Search default locations
        candidates = sorted(
            Path("artifacts/parameter_registry_candidates").glob(
                "*/revit_property_registry.jsonl"
            )
        )
        if candidates:
            registry_entries = load_registry_jsonl(str(candidates[-1]))
            console.print(f"[dim]Registry: {candidates[-1]}[/dim]")

    if not registry_entries:
        console.print("[yellow]Warning: No registry data found. "
                      "Validation will be limited.[/yellow]")

    # Validate against registry
    registry_match = validate_against_registry(req, registry_entries)

    # Execute preview/apply
    result = run_set_parameter_preview(
        req, registry_match, simulated_elements=None
    )
    result.model_name = model_name

    # Write evidence
    evidence_dir = write_evidence(req, registry_match, result,
                                  artifact_base=artifact_dir)

    # Display result
    console.print()
    if result.status == "rejected":
        console.print(f"[red]REJECTED: {result.rejection_reason}[/red]")
    elif result.status == "success" and result.mode == "preview":
        console.print("[green]PREVIEW — model not modified[/green]")
        if result.elements:
            table = Table(title="Element Preview")
            table.add_column("Element ID")
            table.add_column("Category")
            table.add_column("Old Value")
            table.add_column("New Value")
            table.add_column("Status")
            for e in result.elements:
                table.add_row(
                    str(e.element_id),
                    e.category,
                    e.old_value or "(empty)",
                    e.new_value,
                    e.status,
                )
            console.print(table)
    elif result.status == "success" and result.mode == "apply":
        console.print("[bold green]APPLIED — model modified[/bold green]")
        success_n = sum(1 for e in result.elements if e.status == "success")
        console.print(f"[green]{success_n}/{len(result.elements)} "
                      f"elements updated[/green]")

    console.print(f"\n[dim]Evidence: {evidence_dir}[/dim]")
    console.print(f"[dim]Run ID: {result.run_id}[/dim]")


@cli.command("pr-snapshot")
@click.option("--pr", "pr_number", required=True, type=int,
              help="PR number to snapshot")
@click.option("--title", required=True, help="PR title")
@click.option("--branch", required=True, help="PR branch name")
@click.option("--status", "pr_status", required=True,
              type=click.Choice(["open", "merged", "closed", "superseded"]),
              help="PR status")
@click.option("--merge-status", "merge_status", default=None,
              help="Merge status details (e.g. 'merged to main 2026-05-06')")
@click.option("--summary-file", type=click.Path(exists=True),
              help="Path to markdown file with PR summary/description")
@click.option("--validation-file", type=click.Path(exists=True),
              help="Path to markdown/text file with validation results")
@click.option("--changed-files", type=click.Path(exists=True),
              help="Path to text file listing changed files (one per line)")
@click.option("--commits-file", type=click.Path(exists=True),
              help="Path to text file listing commits (one per line)")
@click.option("--source-url", default=None,
              help="URL to the PR on GitHub/GitLab")
@click.option("--verification-method", "verification_method", default="unverified",
              type=click.Choice(["gh_cli", "github_pr_api", "github_ui_manual",
                                 "git_inferred", "unverified"]),
              help="How the PR status was verified")
@click.option("--status-source", "status_source", default=None,
              help="Description of how status was determined "
                   "(e.g. 'gh pr view 9 --json state')")
@click.option("--out", "out_dir", default=None, type=click.Path(),
              help="Output directory (default: artifacts/pr_reviews/pr_NNNN/)")
def pr_snapshot(pr_number, title, branch, pr_status, merge_status,
                summary_file, validation_file, changed_files, commits_file,
                source_url, verification_method, status_source, out_dir):
    """Capture a durable PR review/evidence snapshot as repo-native artifacts.

    Creates JSON + Markdown snapshot files under artifacts/pr_reviews/pr_NNNN/.
    Accepts PR metadata via flags and summary/validation content from local files.
    No GitHub API dependency — paste PR description into a local file and point to it.
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    if out_dir is None:
        out_dir = f"artifacts/pr_reviews/pr_{pr_number:04d}"

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    summary_text = ""
    if summary_file:
        summary_text = Path(summary_file).read_text(encoding="utf-8")

    validation_text = ""
    if validation_file:
        validation_text = Path(validation_file).read_text(encoding="utf-8")

    # Parse structured sections from summary text
    sections = _parse_pr_summary_sections(summary_text)

    # Preserve raw markdown when parsing is ambiguous, rather than guessing.
    raw_summary = summary_text if _summary_parse_remainder(summary_text) else ""
    raw_validation = validation_text if _validation_is_ambiguous(validation_text) else ""

    snapshot = {
        "pr_number": pr_number,
        "title": title,
        "branch": branch,
        "status": pr_status,
        "merge_status": merge_status or pr_status,
        "summary": sections.get("summary", summary_text),
        "raw_summary": raw_summary,
        "raw_validation": raw_validation,
        "review_checklist": sections.get("review_checklist", ""),
        "notes": sections.get("notes", ""),
        "root_cause": sections.get("root_cause", ""),
        "changes": sections.get("changes", ""),
        "what_did_not_change": sections.get("what_did_not_change", ""),
        "validation_commands": sections.get("validation_commands", ""),
        "validation_results": validation_text or sections.get("validation_results", ""),
        "safety_notes": sections.get("safety_notes", ""),
        "known_limitations": sections.get("known_limitations", ""),
        "follow_up_tasks": sections.get("follow_up_tasks", ""),
        "artifact_paths": sections.get("artifact_paths", ""),
        "source_url": source_url,
        "verification_method": verification_method,
        "status_source": status_source or _default_status_source(verification_method),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write JSON
    json_path = out_path / "review_snapshot.json"
    json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")

    # Write Markdown
    md_path = out_path / "review_snapshot.md"
    md_path.write_text(_render_snapshot_markdown(snapshot), encoding="utf-8")

    # Copy changed_files and commits if provided
    if changed_files:
        content = Path(changed_files).read_text(encoding="utf-8")
        (out_path / "changed_files.txt").write_text(content, encoding="utf-8")

    if commits_file:
        content = Path(commits_file).read_text(encoding="utf-8")
        (out_path / "commits.txt").write_text(content, encoding="utf-8")

    console.print(f"\n[bold blue]PR Snapshot[/bold blue] — PR #{pr_number}\n")
    console.print(f"[green]Created:[/green] {json_path}")
    console.print(f"[green]Created:[/green] {md_path}")
    if changed_files:
        console.print(f"[green]Created:[/green] {out_path / 'changed_files.txt'}")
    if commits_file:
        console.print(f"[green]Created:[/green] {out_path / 'commits.txt'}")
    console.print("\n[dim]To generate ledger entries:[/dim]")
    console.print(f"  axiom evidence-update --from-pr-snapshot {out_dir}")


def _default_status_source(verification_method: str) -> str:
    """Return default status_source text for a given verification method."""
    return {
        "gh_cli": "gh pr view --json state,mergedAt,mergeCommit,url",
        "github_pr_api": "GitHub PR API (git_view_pr) verified",
        "github_ui_manual": "Manually verified from GitHub PR page",
        "git_inferred": "Git log/diff only; PR state not verified from GitHub",
        "unverified": "PR status not verified from any authoritative source",
    }.get(verification_method, "PR status not verified from any authoritative source")


# Verification methods that confirm PR state authoritatively
_VERIFIED_METHODS = {"gh_cli", "github_pr_api", "github_ui_manual"}


def _qualified_status(snapshot: dict) -> str:
    """Return status text qualified by verification method.

    Only gh_cli, github_pr_api, and github_ui_manual are considered authoritative.
    All other methods produce qualified status labels.
    """
    status = snapshot.get("status", "unknown")
    method = snapshot.get("verification_method", "unverified")

    if method in _VERIFIED_METHODS:
        return f"{status.capitalize()} (verified: {method})"

    if method == "git_inferred":
        if status == "merged":
            return "Code present on main (git-inferred; PR merge not verified)"
        return f"{status.capitalize()} (git-inferred; not verified from GitHub)"

    # unverified
    if status == "merged":
        return "Merged (UNVERIFIED — status not confirmed from GitHub)"
    return f"{status.capitalize()} (unverified)"


# Order matters: more specific aliases first to avoid false matches.
# E.g. "safety notes" must match safety_notes before "notes" matches notes.
_PR_HEADING_MAP = [
    ("review_checklist", ["review", "checklist", "testing checklist"]),
    ("root_cause", ["root cause"]),
    ("what_did_not_change", ["what did not change", "did not change", "unchanged"]),
    ("validation_commands", ["validation commands", "to validate"]),
    ("validation_results", ["validation results", "live validation",
                             "test results"]),
    ("safety_notes", ["safety notes", "safety status", "safety"]),
    ("known_limitations", ["known limitations", "limitations", "known gaps",
                            "known issues"]),
    ("follow_up_tasks", ["follow up", "follow-up", "next steps", "todo"]),
    ("artifact_paths", ["artifact locations", "artifact paths", "artifacts",
                         "artifact"]),
    ("changes", ["changes", "changed files", "what changed"]),
    ("summary", ["summary"]),
    ("notes", ["notes"]),
]


def _match_pr_heading_key(heading_text: str) -> str | None:
    """Map a markdown heading line to a known snapshot section key, or None."""
    import re

    text = re.sub(r"^#{2,3}\s+", "", heading_text.strip()).strip().lower()
    text = re.sub(r"[:\-—]+$", "", text).strip()
    for key, aliases in _PR_HEADING_MAP:
        for alias in aliases:
            if alias in text:
                return key
    return None


def _parse_pr_summary_sections(text: str) -> dict[str, str]:
    """Parse a PR summary/description into named sections.

    Recognizes common headings from PR templates:
    ## Summary, ## Review & Testing Checklist, ### Notes,
    ## Root Cause, ## Changes, ## What Did NOT Change,
    ## Validation, ## Safety, ## Known Limitations, etc.
    """
    import re

    sections: dict[str, str] = {}
    if not text.strip():
        return sections

    # Split by markdown headings (## or ###)
    parts = re.split(r"^(#{2,3}\s+.+)$", text, flags=re.MULTILINE)

    current_key: str | None = None
    for part in parts:
        heading_match = re.match(r"^#{2,3}\s+(.+)$", part.strip())
        if heading_match:
            current_key = _match_pr_heading_key(heading_match.group(0))
        elif current_key:
            existing = sections.get(current_key, "")
            sections[current_key] = (existing + part).strip()

    return sections


def _summary_parse_remainder(text: str) -> str:
    """Return summary markdown that structured parsing does NOT capture.

    This is content the section parser would silently drop or dump into a
    catch-all: text before the first heading (preamble) and any heading whose
    title does not map to a known section. A non-empty remainder means the
    parse is ambiguous, so the caller should preserve the raw markdown rather
    than guess. Text with no headings at all is unambiguous (it becomes the
    summary verbatim) and yields no remainder.
    """
    import re

    if not text.strip():
        return ""

    parts = re.split(r"^(#{2,3}\s+.+)$", text, flags=re.MULTILINE)
    if not re.search(r"^#{2,3}\s+.+$", text, flags=re.MULTILINE):
        return ""

    remainder: list[str] = []
    preamble = parts[0].strip()
    if preamble:
        remainder.append(preamble)

    idx = 1
    while idx < len(parts):
        heading = parts[idx].strip()
        body = parts[idx + 1] if idx + 1 < len(parts) else ""
        if _match_pr_heading_key(heading) is None:
            remainder.append((heading + "\n" + body).strip())
        idx += 2

    return "\n\n".join(chunk for chunk in remainder if chunk).strip()


def _validation_is_ambiguous(text: str) -> bool:
    """True when validation markdown carries structure the snapshot does not
    parse. Validation input is stored verbatim (never split into sub-sections),
    so any markdown heading is unaccounted-for structure and the raw markdown
    should be preserved explicitly rather than implying it was parsed.
    """
    import re

    if not text.strip():
        return False
    return bool(re.search(r"^#{2,3}\s+.+$", text, flags=re.MULTILINE))


def _render_snapshot_markdown(snapshot: dict) -> str:
    """Render a snapshot dict as a readable Markdown document."""
    lines = [
        f"# PR #{snapshot['pr_number']}: {snapshot['title']}",
        "",
        f"**Branch:** `{snapshot['branch']}`",
        f"**Status:** {_qualified_status(snapshot)}",
        f"**Merge status:** {snapshot['merge_status']}",
        f"**Verification method:** {snapshot.get('verification_method', 'unverified')}",
        f"**Status source:** {snapshot.get('status_source', 'not specified')}",
    ]
    if snapshot.get("source_url"):
        lines.append(f"**URL:** {snapshot['source_url']}")
    lines.append(f"**Snapshot created:** {snapshot['created_at']}")
    lines.append("")

    section_labels = [
        ("summary", "Summary"),
        ("review_checklist", "Review & Testing Checklist"),
        ("notes", "Notes"),
        ("root_cause", "Root Cause"),
        ("changes", "Changes"),
        ("what_did_not_change", "What Did NOT Change"),
        ("validation_commands", "Validation Commands"),
        ("validation_results", "Validation Results"),
        ("safety_notes", "Safety Notes"),
        ("known_limitations", "Known Limitations"),
        ("follow_up_tasks", "Follow-Up Tasks"),
        ("artifact_paths", "Artifact Paths"),
        ("raw_summary", "Raw Summary (preserved — ambiguous parse)"),
        ("raw_validation", "Raw Validation (preserved — ambiguous parse)"),
    ]

    for key, label in section_labels:
        value = snapshot.get(key, "")
        if value and value.strip():
            lines.append(f"## {label}")
            lines.append("")
            lines.append(value.strip())
            lines.append("")

    return "\n".join(lines) + "\n"


@cli.command("evidence-update")
@click.option("--from-pr-snapshot", "snapshot_dir", required=True,
              type=click.Path(exists=True),
              help="Path to PR snapshot directory containing review_snapshot.json")
@click.option("--apply", "apply_flag", is_flag=True, default=False,
              help="Auto-append generated entries to ledger files (use with caution)")
@click.option("--out", "out_file", default=None, type=click.Path(),
              help="Write proposed ledger text to file (default: stdout + snapshot dir)")
def evidence_update(snapshot_dir, apply_flag, out_file):
    """Generate proposed ledger entries from a PR snapshot.

    Reads review_snapshot.json from the snapshot directory and generates
    Markdown blocks suitable for:
    - docs/logs/pr-review-ledger.md
    - docs/logs/bug-validation-log.md
    - docs/logs/behavior-change-ledger.md
    - docs/logs/founders-evidence-log.md

    By default, prints the proposed text and saves to the snapshot directory.
    Use --apply to auto-append to the actual ledger files (use with caution).
    """
    import json
    from pathlib import Path

    snapshot_path = Path(snapshot_dir) / "review_snapshot.json"
    if not snapshot_path.exists():
        console.print(f"[red]Error: {snapshot_path} not found[/red]")
        raise SystemExit(1)

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    proposed = _generate_ledger_entries(snapshot)

    # Write proposed text
    if out_file:
        Path(out_file).write_text(proposed, encoding="utf-8")
        console.print(f"[green]Proposed ledger entries written to: {out_file}[/green]")
    else:
        # Save to snapshot dir
        proposed_path = Path(snapshot_dir) / "proposed_ledger_entries.md"
        proposed_path.write_text(proposed, encoding="utf-8")
        console.print(f"\n[bold blue]Evidence Update[/bold blue] — PR #{snapshot['pr_number']}\n")
        console.print(f"[green]Proposed ledger entries saved to: {proposed_path}[/green]\n")
        console.print("[dim]--- Proposed entries below ---[/dim]\n")
        console.print(proposed)

    if apply_flag:
        _apply_ledger_entries(snapshot, proposed)


def _generate_ledger_entries(snapshot: dict) -> str:
    """Generate proposed Markdown entries for all relevant ledger files."""
    pr_num = snapshot["pr_number"]
    title = snapshot["title"]
    branch = snapshot["branch"]
    status = snapshot["status"]
    created_at = snapshot.get("created_at", "")
    date_str = created_at[:10] if created_at else "TBD"

    lines: list[str] = []

    # --- pr-review-ledger entry ---
    lines.append("=" * 60)
    lines.append("## For: docs/logs/pr-review-ledger.md")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"## PR #{pr_num}: {title}")
    lines.append("")
    lines.append(f"**Branch:** `{branch}`")
    lines.append("**Base:** `main`")
    qualified = _qualified_status(snapshot)
    lines.append(f"**Status:** {qualified} ({date_str})")
    if snapshot.get("summary"):
        lines.append("")
        lines.append("### Summary")
        lines.append("")
        lines.append(snapshot["summary"].strip())
    if snapshot.get("root_cause"):
        lines.append("")
        lines.append("### Root Cause")
        lines.append("")
        lines.append(snapshot["root_cause"].strip())
    if snapshot.get("changes"):
        lines.append("")
        lines.append("### Changes")
        lines.append("")
        lines.append(snapshot["changes"].strip())
    if snapshot.get("validation_results"):
        lines.append("")
        lines.append("### Validation Results")
        lines.append("")
        lines.append(snapshot["validation_results"].strip())
    if snapshot.get("safety_notes"):
        lines.append("")
        lines.append("### Safety Notes")
        lines.append("")
        lines.append(snapshot["safety_notes"].strip())
    if snapshot.get("what_did_not_change"):
        lines.append("")
        lines.append("### What Did NOT Change")
        lines.append("")
        lines.append(snapshot["what_did_not_change"].strip())
    if snapshot.get("known_limitations"):
        lines.append("")
        lines.append("### Known Limitations")
        lines.append("")
        lines.append(snapshot["known_limitations"].strip())
    lines.append("")

    # --- founders-evidence-log entry ---
    lines.append("=" * 60)
    lines.append("## For: docs/logs/founders-evidence-log.md")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"### EVID-NNN: PR #{pr_num} — {title}")
    lines.append("")
    lines.append(f"- **Date:** {date_str}")
    lines.append("- **Workstream:** TBD")
    lines.append(f"- **PR:** #{pr_num} (`{branch}`)")
    qualified = _qualified_status(snapshot)
    lines.append(f"- **Status:** {qualified}")
    lines.append(f"- **Verification:** {snapshot.get('verification_method', 'unverified')} "
                 f"— {snapshot.get('status_source', 'not specified')}")
    if snapshot.get("summary"):
        lines.append(f"- **Work performed:** {_first_paragraph(snapshot['summary'])}")
    if snapshot.get("validation_results"):
        lines.append(f"- **Validation:** {_first_paragraph(snapshot['validation_results'])}")
    lines.append(f"- **Evidence source:** PR #{pr_num}")
    lines.append("- **Estimated hours:** TBD")
    if snapshot.get("artifact_paths"):
        lines.append(f"- **Validation artifact:** {_first_paragraph(snapshot['artifact_paths'])}")
    lines.append("")

    # --- bug-validation-log entry (only if root_cause present) ---
    if snapshot.get("root_cause"):
        lines.append("=" * 60)
        lines.append("## For: docs/logs/bug-validation-log.md")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"### BUG-NNN: {title}")
        lines.append("")
        lines.append(f"- **Discovered:** {date_str}")
        lines.append(f"- **PR:** #{pr_num}")
        lines.append(f"- **Root cause:** {_first_paragraph(snapshot['root_cause'])}")
        if snapshot.get("changes"):
            lines.append(f"- **Fix:** {_first_paragraph(snapshot['changes'])}")
        if snapshot.get("validation_results"):
            lines.append(f"- **Validation:** "
                         f"{_first_paragraph(snapshot['validation_results'])}")
        lines.append(f"- **Status:** {status}")
        lines.append("")

    # --- behavior-change-ledger entry (only if changes suggest behavior change) ---
    if snapshot.get("changes") or snapshot.get("what_did_not_change"):
        lines.append("=" * 60)
        lines.append("## For: docs/logs/behavior-change-ledger.md")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"## BHV-NNN: {title}")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append("| **behavior_id** | BHV-NNN |")
        lines.append(f"| **date** | {date_str} |")
        lines.append("| **capability** | TBD |")
        if snapshot.get("changes"):
            lines.append(f"| **current_behavior** | "
                         f"{_first_paragraph(snapshot['changes'])} |")
        if snapshot.get("what_did_not_change"):
            lines.append(f"| **what_did_not_change** | "
                         f"{_first_paragraph(snapshot['what_did_not_change'])} |")
        lines.append(f"| **status** | {status} |")
        lines.append("| **related_bug_id** | — |")
        lines.append(f"| **notes** | See PR #{pr_num} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def _first_paragraph(text: str) -> str:
    """Extract the first non-empty paragraph from text, truncated to one line."""
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Truncate long lines
            if len(stripped) > 200:
                return stripped[:197] + "..."
            return stripped
    return text.strip()[:200] if text.strip() else ""


def _apply_ledger_entries(snapshot: dict, proposed: str):
    """Auto-append proposed entries to ledger files."""
    import re
    from pathlib import Path
    sections = re.split(r"^={60}\n## For: (.+)\n={60}$", proposed, flags=re.MULTILINE)

    applied = []
    for i in range(1, len(sections), 2):
        target_file = sections[i].strip()
        content = sections[i + 1].strip()
        if not content:
            continue

        target_path = Path(target_file)
        if target_path.exists():
            with target_path.open("a", encoding="utf-8") as f:
                f.write("\n\n---\n\n" + content + "\n")
            applied.append(target_file)
            console.print(f"[green]Appended to: {target_file}[/green]")
        else:
            console.print(f"[yellow]Skipped (not found): {target_file}[/yellow]")

    if not applied:
        console.print("[yellow]No ledger files updated.[/yellow]")


@cli.command("validation-run")
@click.option("--scenario", "scenario", default="set_parameter_preview_apply_wall_comments",
              help="Validation scenario id (or alias, e.g. set_parameter_preview_apply).")
@click.option("--branch", "branch", default=None,
              help="Target git branch to record (and pull when --pull is set).")
@click.option("--revit-version", "revit_version", default="2027",
              help="Revit version for deploy/evidence (default: 2027).")
@click.option("--phase", "phase", default="all",
              type=click.Choice(["pre", "scan", "all"]),
              help="pre = automate before live Revit; scan = evaluate evidence "
                   "after live Revit; all = both.")
@click.option("--pull/--no-pull", "do_pull", default=False,
              help="Fast-forward pull the target branch (requires --branch).")
@click.option("--tests/--no-tests", "do_tests", default=True,
              help="Run the allowlisted Python tests + ruff in pre/all phases.")
@click.option("--deploy/--no-deploy", "do_deploy", default=False,
              help="Build/deploy via the existing deploy script (Windows only).")
@click.option("--max-attempts", "max_attempts", default=None, type=int,
              help="Bounded retry budget for the evidence scan (default: 5). "
                   "Increase to confirm larger testing concepts.")
@click.option("--attempt-wait-seconds", "attempt_wait_seconds", default=2.0, type=float,
              help="Seconds to wait between evidence-scan attempts.")
@click.option("--evidence-root", "evidence_roots", multiple=True,
              type=click.Path(),
              help="Evidence directory containing run folders. Repeatable. "
                   "Defaults to all user profiles' Axiom evidence folders.")
@click.option("--run-id", "run_id", default=None,
              help="Reuse/resume an existing run id (for the scan phase).")
@click.option("--output-dir", "output_dir", default="artifacts/validation_runs",
              type=click.Path(), help="Base directory for validation run artifacts.")
@click.option("--repo-root", "repo_root", default=".", type=click.Path(),
              help="Repository root for git/test/deploy commands.")
def validation_run(scenario, branch, revit_version, phase, do_pull, do_tests,
                   do_deploy, max_attempts, attempt_wait_seconds, evidence_roots,
                   run_id, output_dir, repo_root):
    """Axiom Validation Automation Loop v0 - automate everything around the
    single live-Revit human step and classify the result.

    \b
    Examples:
      # Pre phase: tests + (optional deploy) + print manual Revit steps
      axiom validation-run --scenario set_parameter_preview_apply --branch main --phase pre
      # Scan phase: after performing the live Revit step, evaluate evidence
      axiom validation-run --scenario set_parameter_preview_apply --phase scan
      # Larger retry budget for bigger testing concepts
      axiom validation-run --phase scan --max-attempts 20
    """
    from axiom_core.validation_loop import (
        DEFAULT_MAX_ATTEMPTS,
        resolve_scenario,
        run_validation,
    )

    if resolve_scenario(scenario) is None:
        console.print(f"[red]Unknown scenario: {scenario}[/red]")
        raise SystemExit(1)

    attempts = max_attempts if max_attempts is not None else DEFAULT_MAX_ATTEMPTS

    console.print("\n[bold blue]Axiom Validation Automation Loop v0[/bold blue]\n")
    console.print(f"[dim]Scenario: {scenario} | Phase: {phase} | "
                  f"Revit: {revit_version} | Max attempts: {attempts}[/dim]")

    result = run_validation(
        scenario_name=scenario,
        branch=branch,
        revit_version=revit_version,
        phase=phase,
        do_pull=do_pull,
        do_tests=do_tests,
        do_deploy=do_deploy,
        evidence_dirs=list(evidence_roots) if evidence_roots else None,
        repo_root=repo_root,
        output_dir=output_dir,
        run_id=run_id,
        max_attempts=attempts,
        attempt_wait_seconds=attempt_wait_seconds,
    )

    console.print()
    color = "green" if result.classification == "pass" else "yellow"
    console.print(f"[bold {color}]Classification: {result.classification}[/bold {color}]")
    console.print(f"[dim]{result.reason}[/dim]")
    console.print(f"\n[dim]Run ID: {result.run_id}[/dim]")
    console.print(f"[dim]Artifacts: {result.artifact_dir}[/dim]")
    if result.human_action_required:
        console.print(f"[yellow]Human action required: "
                      f"{result.artifact_dir}/human_action_required.md[/yellow]")
    if phase == "pre":
        console.print(f"[dim]Next: perform the manual Revit steps, then run "
                      f"--phase scan --run-id {result.run_id}[/dim]")

    # Signal failure via exit code so wrappers / CI can react. A pending live
    # Revit step is the expected handoff in the pre phase, not a failure.
    ok_classes = {"pass", "revit_manual_step_pending"}
    if result.classification not in ok_classes:
        raise SystemExit(1)


@cli.command("bridge-execute")
@click.option("--capability", "capability", default="InventoryModel",
              help="Registered capability to execute (default: InventoryModel).")
@click.option("--args-json", "args_json", default=None,
              help="JSON object of capability args. Default for InventoryModel is "
                   "safe summary mode ({\"SummaryOnly\": true}).")
@click.option("--simulate", is_flag=True,
              help="Use the mock path (no Revit needed); request is still recorded.")
@click.option("--transaction-name", "transaction_name", default=None,
              help="Optional Revit transaction name.")
@click.option("--run-id", "run_id", default=None,
              help="Run id for the evidence bundle (default: brun_<timestamp>).")
@click.option("--output-dir", "output_dir", default="artifacts/validation_runs",
              type=click.Path(), help="Base directory for bridge run artifacts.")
def bridge_execute(capability, args_json, simulate, transaction_name, run_id, output_dir):
    """Axiom Automation Bridge v0 - send ONE capability execution request to a
    running Revit add-in over the existing named-pipe bridge, with no human
    interaction, and write durable evidence (request/response/summary/pass-fail).

    \b
    Examples:
      # Read-only InventoryModel summary against a running Revit add-in
      axiom bridge-execute --capability InventoryModel
      # Mock path (no Revit) - proves the driver/evidence flow off-Windows
      axiom bridge-execute --capability InventoryModel --simulate
    """
    from axiom_core.automation_bridge import execute_capability_via_bridge

    if args_json:
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as exc:
            console.print(f"[red]Invalid --args-json: {exc}[/red]")
            raise SystemExit(2)
        if not isinstance(args, dict):
            console.print("[red]--args-json must be a JSON object.[/red]")
            raise SystemExit(2)
    elif capability == "InventoryModel":
        # Safe default: summary mode only (no full scan).
        args = {"SummaryOnly": True, "ScanMode": "summary"}
    else:
        args = {}

    console.print("\n[bold blue]Axiom Automation Bridge v0[/bold blue]\n")
    console.print(f"[dim]Capability: {capability} | Mode: "
                  f"{'simulate' if simulate else 'live'}[/dim]")

    result = execute_capability_via_bridge(
        capability=capability,
        args=args,
        run_id=run_id,
        simulate=simulate,
        transaction_name=transaction_name,
        output_dir=output_dir,
    )

    console.print()
    color = "green" if result.passed else "yellow"
    console.print(f"[bold {color}]Classification: {result.classification}[/bold {color}]")
    console.print(f"[dim]{result.reason}[/dim]")
    console.print(f"\n[dim]Run ID: {result.run_id}[/dim]")
    console.print(f"[dim]Artifacts: {result.artifact_dir}[/dim]")

    if result.classification not in ("pass",):
        raise SystemExit(1)


@cli.command("discovery-run")
@click.option("--adapter", "adapter", default="revit",
              help="Product adapter (only 'revit' supported in v1).")
@click.option("--simulate", is_flag=True,
              help="Interpret the built-in deterministic export (no Revit needed).")
@click.option("--inventory-export-path", "inventory_export_path", default=None,
              type=click.Path(), help="Path to an InventoryModel export to interpret "
                                       "(required for a live run). Recommended: an "
                                       "InventoryModel run FOLDER (auto-detects "
                                       "elements.jsonl/elements.parquet + parameters.parquet "
                                       "+ run_metadata.json). Also accepts a single handoff "
                                       ".json (object with an 'elements' list) or an "
                                       "element-level .jsonl. NOTE: elements.jsonl ALONE has "
                                       "no parameters - pass the run folder (with "
                                       "parameters.parquet) for parameter/candidate "
                                       "discovery. parameters.jsonl / parameter_schema.jsonl "
                                       "are NOT element exports.")
@click.option("--run-id", "run_id", default=None,
              help="Run id for the discovery bundle (default: drun_<timestamp>).")
@click.option("--output-dir", "output_dir", default="artifacts/discovery_runs",
              type=click.Path(), help="Base directory for discovery run artifacts.")
@click.option("--db-path", "db_path", default=None,
              type=click.Path(), help="Optional SQLite DB path to persist registries "
                                       "(reuses PR #1 schema). Omit to skip persistence.")
def discovery_run(adapter, simulate, inventory_export_path, run_id, output_dir, db_path):
    """Discovery Harness v1 - interpret an InventoryModel export into the
    ProductObject/ProductProperty registries, discovery evidence, candidate
    capability definitions, and a human-reviewable report bundle.

    Read-only discovery only: no model mutation, no candidate execution.

    \b
    Examples:
      # Built-in deterministic export (off-Windows / CI)
      axiom discovery-run --adapter revit --simulate
      # Live interpretation of an InventoryModel export
      axiom discovery-run --adapter revit --inventory-export-path export.json
    """
    from axiom_core.discovery import run_discovery

    if adapter != "revit":
        console.print(f"[red]Unsupported adapter '{adapter}' (only 'revit' in v1).[/red]")
        raise SystemExit(2)
    if not simulate and not inventory_export_path:
        console.print("[red]Live discovery requires --inventory-export-path "
                      "(or use --simulate).[/red]")
        raise SystemExit(2)

    session_factory = None
    if db_path:
        from axiom_core.database import (
            create_db_engine,
            init_db,
            make_session_factory,
        )

        engine = create_db_engine(db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)

    console.print("\n[bold blue]Axiom Discovery Harness v1[/bold blue]\n")
    console.print(f"[dim]Adapter: {adapter} | Mode: "
                  f"{'simulate' if simulate else 'live'}[/dim]")

    try:
        result = run_discovery(
            run_id=run_id,
            simulate=simulate,
            inventory_export_path=inventory_export_path,
            output_dir=output_dir,
            session_factory=session_factory,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2)

    m = result.metrics
    table = Table(title="Discovery Metrics")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    for key, val in m.items():
        table.add_row(key.replace("_", " ").title(), str(val))
    console.print()
    console.print(table)
    rows_total = result.parameter_rows_total
    rows_joined = result.parameter_rows_joined
    rows_note = ""
    if rows_total is not None:
        rows_note = f" | Parameter rows joined/total: {rows_joined}/{rows_total}"
    console.print(f"\n[dim]Object source: {result.object_source or '(unknown)'} | "
                  f"Parameter source: {result.parameter_source or 'MISSING'}"
                  f"{rows_note}[/dim]")
    console.print(
        f"[dim]Discovery complete: {'yes' if result.discovery_complete else 'NO'}[/dim]"
    )
    for warning in result.warnings:
        console.print(f"[yellow]Warning: {warning}[/yellow]")
    console.print(f"\n[dim]Run ID: {result.run_id}[/dim]")
    console.print(f"[dim]Artifacts: {result.output_dir}[/dim]")
    if result.persisted:
        console.print(f"[dim]Persisted: {result.persisted}[/dim]")


@cli.command("runner-commands")
@click.option("--name", "name", default=None,
              help="Inspect a single command in detail (unknown names are denied).")
@click.option("--classification", "classification", default=None,
              help="Filter the list by classification "
                   "(read_only/test/build/mutation/live_revit_required).")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit machine-readable JSON instead of tables.")
def runner_commands(name, classification, as_json):
    """Runner Command Registry — list/inspect the commands the AXIOM-01 runner
    is allowed to execute.

    Governance only: this prints the execution policy (safety level,
    prerequisites, evidence outputs, timeout, failure classification). It does
    NOT execute anything. Unknown commands are denied by default.

    \b
    Examples:
      axiom runner-commands                       # list all allowed commands
      axiom runner-commands --classification test # filter by classification
      axiom runner-commands --name pytest         # inspect one command
      axiom runner-commands --json                # machine-readable catalog
    """
    import json as _json

    from axiom_core.runner import (
        CommandClass,
        get_command,
        is_allowed,
        list_commands,
    )

    # Inspect a single command.
    if name:
        if not is_allowed(name):
            allowed = ", ".join(c.name for c in list_commands())
            if as_json:
                console.print_json(_json.dumps({
                    "name": name,
                    "allowed": False,
                    "reason": "unknown command — denied by default",
                    "allowed_commands": [c.name for c in list_commands()],
                }))
            else:
                console.print(
                    f"[red]Command '{name}' is not allowed "
                    f"(unknown commands are denied by default).[/red]")
                console.print(f"[dim]Allowed: {allowed}[/dim]")
            raise SystemExit(2)

        spec = get_command(name)
        if as_json:
            console.print_json(_json.dumps(spec.to_dict()))
            return

        console.print(f"\n[bold blue]{spec.name}[/bold blue]  "
                      f"[dim]{spec.command}[/dim]\n")
        console.print(spec.description)
        meta = Table(show_header=False, box=None)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("Classification", spec.classification.value)
        meta.add_row("Safety level", spec.safety_level.value)
        meta.add_row("Requires Revit", "yes" if spec.requires_revit else "no")
        meta.add_row("Requires model open", "yes" if spec.requires_model_open else "no")
        meta.add_row("Timeout (s)", str(spec.timeout_seconds))
        meta.add_row("Prerequisites",
                     ", ".join(p.value for p in spec.prerequisites) or "none")
        console.print(meta)

        ev = Table(title="Evidence outputs", show_header=False)
        ev.add_column("output")
        for out in spec.evidence_outputs:
            ev.add_row(out.location)
        console.print(ev)

        fm = Table(title="Failure classification")
        fm.add_column("Class", style="yellow")
        fm.add_column("Retryable", justify="center")
        fm.add_column("Description")
        for mode in spec.failure_modes:
            fm.add_row(mode.code.value, "yes" if mode.retryable else "no",
                       mode.description)
        console.print(fm)
        if spec.notes:
            console.print(f"\n[dim]Note: {spec.notes}[/dim]")
        return

    # List (optionally filtered).
    specs = list_commands()
    if classification:
        try:
            wanted = CommandClass(classification.strip().lower())
        except ValueError:
            valid = ", ".join(c.value for c in CommandClass)
            console.print(f"[red]Invalid classification '{classification}'. "
                          f"Valid: {valid}[/red]")
            raise SystemExit(2)
        specs = [s for s in specs if s.classification is wanted]

    if as_json:
        console.print_json(_json.dumps([s.to_dict() for s in specs]))
        return

    console.print("\n[bold blue]Axiom Runner Command Registry[/bold blue]")
    console.print("[dim]Governed execution policy — unknown commands denied by "
                  "default. This catalog does not execute anything.[/dim]\n")
    table = Table(title="Allowed Commands")
    table.add_column("Name", style="cyan")
    table.add_column("Classification")
    table.add_column("Safety")
    table.add_column("Revit", justify="center")
    table.add_column("Timeout", justify="right")
    table.add_column("Prerequisites")
    for spec in specs:
        table.add_row(
            spec.name,
            spec.classification.value,
            spec.safety_level.value,
            "yes" if spec.requires_revit else "no",
            f"{spec.timeout_seconds}s",
            ", ".join(p.value for p in spec.prerequisites) or "none",
        )
    console.print(table)
    console.print(f"\n[dim]{len(specs)} command(s). "
                  f"Inspect one with: axiom runner-commands --name <name>[/dim]")


@cli.command("validation-registry")
@click.option("--name", "name", default=None,
              help="Inspect one capability's validation definition "
                   "(unknown capabilities are denied).")
@click.option("--type", "capability_type", default=None,
              help="Filter the list by capability type "
                   "(inventory/discovery/mutation/bridge/creation).")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit machine-readable JSON instead of tables.")
@click.option("--persist", "persist", is_flag=True, default=False,
              help="Persist the validation definitions to SQLite "
                   "(definitions only — nothing is executed).")
@click.option("--db-path", "db_path", default=None,
              help="SQLite db path to persist into (with --persist).")
def validation_registry(name, capability_type, as_json, persist, db_path):
    """Capability Validation Registry — list/inspect how Axiom capabilities are
    validated.

    Governance only: this prints the validation contract (procedure, inputs,
    environment requirements, evidence, pass/failure criteria, retry policy,
    promotion eligibility). It does NOT execute, promote, or score anything.
    Unknown capabilities are denied by default.

    \b
    Examples:
      axiom validation-registry                      # list all definitions
      axiom validation-registry --type mutation      # filter by capability type
      axiom validation-registry --name InventoryModel  # inspect one capability
      axiom validation-registry --json               # machine-readable catalog
      axiom validation-registry --persist --db-path validation.db
    """
    import json as _json

    from axiom_core.validation import (
        CapabilityType,
        get_procedure,
        is_known,
        list_procedures,
    )

    # Optional: persist the definitions to SQLite (definitions only).
    if persist:
        from axiom_core.database import (
            create_db_engine,
            get_database_url,
            init_db,
            make_session_factory,
        )
        from axiom_core.validation import persist_default_registry

        if db_path is None:
            console.print(f"[dim]No --db-path given; using {get_database_url()}[/dim]")
        engine = create_db_engine(db_path)
        init_db(engine)
        counts = persist_default_registry(make_session_factory(engine))
        console.print(
            f"[green]Persisted validation definitions[/green] "
            f"(inserted={counts['inserted']}, updated={counts['updated']})")
        if not (name or as_json):
            return

    # Inspect a single capability.
    if name:
        if not is_known(name):
            allowed = ", ".join(p.capability_name for p in list_procedures())
            if as_json:
                console.print_json(_json.dumps({
                    "capability_name": name,
                    "known": False,
                    "reason": "unknown capability — denied by default",
                    "known_capabilities": [p.capability_name for p in list_procedures()],
                }))
            else:
                console.print(
                    f"[red]Capability '{name}' is not in the validation registry "
                    f"(unknown capabilities are denied by default).[/red]")
                console.print(f"[dim]Known: {allowed}[/dim]")
            raise SystemExit(2)

        proc = get_procedure(name)
        if as_json:
            console.print_json(_json.dumps(proc.to_dict()))
            return

        console.print(f"\n[bold blue]{proc.capability_name}[/bold blue]  "
                      f"[dim]{proc.validation_procedure_id}[/dim]\n")
        console.print(proc.validation_description)
        meta = Table(show_header=False, box=None)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("Validation", proc.validation_name)
        meta.add_row("Capability type", proc.capability_type.value)
        meta.add_row("Adapter / version", f"{proc.adapter} / {proc.version}")
        meta.add_row("Requires Revit", "yes" if proc.requires_revit else "no")
        meta.add_row("Requires model open", "yes" if proc.requires_model_open else "no")
        meta.add_row("Requires test model", "yes" if proc.requires_test_model else "no")
        meta.add_row("Requires runner", "yes" if proc.requires_runner else "no")
        meta.add_row("Required inputs", ", ".join(proc.required_inputs) or "none")
        meta.add_row("Optional inputs", ", ".join(proc.optional_inputs) or "none")
        meta.add_row("Environment",
                     ", ".join(e.value for e in proc.environment_requirements) or "none")
        console.print(meta)

        steps = Table(title="Procedure steps", show_header=False)
        steps.add_column("#", justify="right", style="dim")
        steps.add_column("step")
        for i, step in enumerate(proc.steps, 1):
            steps.add_row(str(i), step)
        console.print(steps)

        ev = Table(title="Required evidence")
        ev.add_column("Kind", style="cyan")
        ev.add_column("Name")
        ev.add_column("Required", justify="center")
        for item in proc.evidence.all_items():
            ev.add_row(item.kind.value, item.name, "yes" if item.required else "no")
        console.print(ev)

        crit = Table(show_header=False, box=None)
        crit.add_column("k", style="cyan")
        crit.add_column("v")
        crit.add_row("Pass conditions",
                     ", ".join(c.value for c in proc.pass_conditions))
        crit.add_row("Failure conditions",
                     ", ".join(c.value for c in proc.failure_conditions))
        rp = proc.retry_policy
        crit.add_row("Retry policy",
                     f"max_retries={rp.max_retries}, delay={rp.retry_delay_seconds}s, "
                     f"on={', '.join(c.value for c in rp.retry_conditions) or 'none'}")
        pe = proc.promotion_eligibility
        crit.add_row("Promotion eligibility",
                     f"successes>={pe.minimum_successes}, "
                     f"evidence_sets>={pe.minimum_evidence_sets}, "
                     f"confidence>={pe.required_confidence}")
        console.print(crit)
        if proc.notes:
            console.print(f"\n[dim]Note: {proc.notes}[/dim]")
        return

    # List (optionally filtered).
    procs = list_procedures()
    if capability_type:
        try:
            wanted = CapabilityType(capability_type.strip().lower())
        except ValueError:
            valid = ", ".join(t.value for t in CapabilityType)
            console.print(f"[red]Invalid capability type '{capability_type}'. "
                          f"Valid: {valid}[/red]")
            raise SystemExit(2)
        procs = [p for p in procs if p.capability_type is wanted]

    if as_json:
        console.print_json(_json.dumps([p.to_dict() for p in procs]))
        return

    console.print("\n[bold blue]Axiom Capability Validation Registry[/bold blue]")
    console.print("[dim]Governed validation policy — unknown capabilities denied by "
                  "default. This registry does not execute, promote, or score "
                  "anything.[/dim]\n")
    table = Table(title="Validation Definitions")
    table.add_column("Capability", style="cyan")
    table.add_column("Type")
    table.add_column("Adapter")
    table.add_column("Version")
    table.add_column("Revit", justify="center")
    table.add_column("Pass conditions", justify="right")
    table.add_column("Evidence", justify="right")
    for proc in procs:
        table.add_row(
            proc.capability_name,
            proc.capability_type.value,
            proc.adapter,
            proc.version,
            "yes" if proc.requires_revit else "no",
            str(len(proc.pass_conditions)),
            str(len(proc.evidence.all_items())),
        )
    console.print(table)
    console.print(f"\n[dim]{len(procs)} validation definition(s). "
                  f"Inspect one with: axiom validation-registry --name <capability>[/dim]")


@cli.command("evidence-run")
@click.option("--validation", "validation_name", required=True,
              help="Validation to run (unknown validations are denied by default).")
@click.option("--inventory-export-path", "inventory_export_path", default=None,
              type=click.Path(),
              help="InventoryModel export for DiscoveryHarness (omit to use the "
                   "built-in deterministic export).")
@click.option("--output-dir", "output_dir", default=None, type=click.Path(),
              help="Base directory for evidence bundles "
                   "(default: artifacts/validation_evidence).")
def evidence_run(validation_name, inventory_export_path, output_dir):
    """Validation Evidence Runner — produce a durable evidence bundle for a
    read-only validation.

    Consumes the Capability Validation Registry (PR #24), gates the command it
    drives against the Runner Command Registry (PR #22), runs only safe/
    read-only procedures, and writes an evidence bundle every time
    (validation_request.json, validation_result.json, validation_summary.md,
    command_outputs/, pass_fail.json).

    Unknown validations are denied by default; mutation/high-risk validations
    are refused (mutation allowance is not implemented). No scheduling,
    promotion, learning, or model mutation.

    \b
    Examples:
      axiom evidence-run --validation CommandRegistry
      axiom evidence-run --validation ValidationRegistry
      axiom evidence-run --validation DiscoveryHarness
      axiom evidence-run --validation DiscoveryHarness --inventory-export-path export.json
    """
    from axiom_core.validation.evidence_runner import (
        DEFAULT_OUTPUT_BASE,
        EvidenceOutcome,
        EvidenceRunner,
    )

    runner = EvidenceRunner(output_base=output_dir or DEFAULT_OUTPUT_BASE)
    result = runner.run(validation_name, inventory_export_path=inventory_export_path)

    colour = {
        EvidenceOutcome.PASSED: "green",
        EvidenceOutcome.FAILED: "red",
        EvidenceOutcome.DENIED: "red",
        EvidenceOutcome.REFUSED: "yellow",
        EvidenceOutcome.UNSUPPORTED: "yellow",
        EvidenceOutcome.BLOCKED: "yellow",
    }[result.outcome]

    console.print("\n[bold blue]Axiom Validation Evidence Runner[/bold blue]\n")
    console.print(f"Validation: [bold]{result.validation_name}[/bold]")
    console.print(f"Outcome: [{colour}]{result.outcome.value.upper()}[/{colour}]  "
                  f"({result.checks_passed}/{len(result.checks)} checks passed)")
    console.print(f"[dim]{result.reason}[/dim]")

    if result.checks:
        table = Table(title="Checks")
        table.add_column("Check")
        table.add_column("Result", justify="center")
        table.add_column("Detail")
        for c in result.checks:
            mark = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
            table.add_row(c.name, mark, c.detail)
        console.print(table)

    console.print(f"\n[dim]Evidence bundle: {result.bundle_dir}[/dim]")
    console.print(f"[dim]Verdict: pass_fail.json | exit code {result.exit_code}[/dim]")
    raise SystemExit(result.exit_code)


@cli.command("capability-run")
@click.option("--capability", "capability_name", required=True,
              help="Capability to execute (unknown capabilities are denied by default).")
@click.option("--args-json", "args_json", default=None,
              help="JSON object of capability arguments (e.g. '{\"Category\": \"Walls\"}').")
@click.option("--run-id", "run_id", default=None,
              help="Explicit run id for the evidence bundle (default: generated).")
@click.option("--output-dir", "output_dir", default=None, type=click.Path(),
              help="Base directory for evidence bundles "
                   "(default: artifacts/capability_runs).")
@click.option("--simulate", is_flag=True, default=False,
              help="Use the bridge mock path (no live Revit needed).")
def capability_run(capability_name, args_json, run_id, output_dir, simulate):
    """Capability Execution Runner — execute a governed safe/read-only capability
    and produce a durable evidence bundle.

    Gates the capability against the Runner Command Registry (PR #22), maps it to
    its Capability Validation Registry (PR #24) contract, executes only
    explicitly allowed safe/read-only capabilities through the Automation Bridge
    (PR #19), and writes an evidence bundle every time (capability_request.json,
    capability_result.json, capability_summary.md, command_outputs/,
    pass_fail.json).

    Unknown capabilities are denied by default; mutation/high-risk capabilities
    (and unbounded InventoryModel scans) are refused (mutation allowance is not
    implemented). No SetParameterValue execution, scheduling, retry, promotion,
    learning, or model mutation.

    \b
    Examples:
      axiom capability-run --capability InventoryModel --simulate
      axiom capability-run --capability InventoryModel --args-json '{"Category": "Walls"}' --simulate
    """
    from axiom_core.runner.capability_runner import (
        DEFAULT_OUTPUT_BASE,
        CapabilityOutcome,
        CapabilityRunner,
    )

    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid --args-json: {exc}[/red]")
        raise SystemExit(2) from exc
    if not isinstance(args, dict):
        console.print("[red]--args-json must be a JSON object.[/red]")
        raise SystemExit(2)

    runner = CapabilityRunner(output_base=output_dir or DEFAULT_OUTPUT_BASE)
    result = runner.run(
        capability_name, args=args, simulate=simulate, run_id=run_id,
    )

    colour = {
        CapabilityOutcome.PASSED: "green",
        CapabilityOutcome.FAILED: "red",
        CapabilityOutcome.DENIED: "red",
        CapabilityOutcome.REFUSED: "yellow",
        CapabilityOutcome.UNSUPPORTED: "yellow",
        CapabilityOutcome.BLOCKED: "yellow",
    }[result.outcome]

    console.print("\n[bold blue]Axiom Capability Execution Runner[/bold blue]\n")
    console.print(f"Capability: [bold]{result.capability_name}[/bold]  "
                  f"[dim]({'simulate' if result.simulate else 'live'})[/dim]")
    console.print(f"Outcome: [{colour}]{result.outcome.value.upper()}[/{colour}]  "
                  f"({result.checks_passed}/{len(result.checks)} checks passed)")
    console.print(f"[dim]{result.reason}[/dim]")

    if result.checks:
        table = Table(title="Checks")
        table.add_column("Check")
        table.add_column("Result", justify="center")
        table.add_column("Detail")
        for c in result.checks:
            mark = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
            table.add_row(c.name, mark, c.detail)
        console.print(table)

    console.print(f"\n[dim]Evidence bundle: {result.bundle_dir}[/dim]")
    console.print(f"[dim]Verdict: pass_fail.json | exit code {result.exit_code}[/dim]")
    raise SystemExit(result.exit_code)


_STATE_COLOUR = {
    "execution_passed": "green",
    "validation_passed": "green",
    "executable": "cyan",
    "validation_defined": "cyan",
    "defined": "white",
    "discovered": "blue",
    "execution_failed": "red",
    "validation_failed": "red",
    "denied": "red",
    "blocked": "yellow",
    "refused": "yellow",
    "unsupported": "yellow",
    "deprecated": "dim",
}


@cli.command("capability-state")
@click.option("--name", "name", default=None,
              help="Inspect one capability's lifecycle state "
                   "(unknown capabilities exit non-zero).")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit machine-readable JSON instead of tables.")
@click.option("--refresh", "refresh", is_flag=True, default=False,
              help="Rebuild/persist state from registries + evidence artifacts "
                   "into SQLite (otherwise the command is read-only).")
@click.option("--db-path", "db_path", default=None,
              help="SQLite db path for persisted state (default: ~/.axiom/axiom.db).")
@click.option("--capability-runs-dir", "capability_runs_dir", default=None,
              type=click.Path(),
              help="Base dir of Capability Runner evidence bundles "
                   "(default: artifacts/capability_runs).")
@click.option("--validation-evidence-dir", "validation_evidence_dir", default=None,
              type=click.Path(),
              help="Base dir of Validation Evidence Runner bundles "
                   "(default: artifacts/validation_evidence).")
def capability_state(name, as_json, refresh, db_path, capability_runs_dir,
                     validation_evidence_dir):
    """Capability State Registry — durable lifecycle state for capabilities.

    Summarizes existing governance registries (Command Registry / Validation
    Registry), Capability Runner + Validation Evidence bundles, and (when a db
    is present) DiscoveryHarness candidates into one durable per-capability state
    record. State/governance memory only: it executes nothing, retries nothing,
    promotes nothing, and schedules nothing. ``promotion_candidate`` is a
    non-binding derived flag for a future promotion engine.

    Read-only by default; pass ``--refresh`` to rebuild and persist state into
    SQLite. Unknown capability lookup exits non-zero.

    \b
    Examples:
      axiom capability-state                       # list all capability states
      axiom capability-state --name InventoryModel # inspect one capability
      axiom capability-state --json                # machine-readable snapshot
      axiom capability-state --refresh             # rebuild + persist into SQLite
    """
    import json as _json
    from pathlib import Path as _Path

    from axiom_core.database import (
        create_db_engine,
        get_database_url,
        init_db,
        make_session_factory,
    )
    from axiom_core.runner.capability_state import (
        DEFAULT_CAPABILITY_RUNS_BASE,
        DEFAULT_VALIDATION_EVIDENCE_BASE,
        CapabilityStateRegistry,
    )

    runs_base = capability_runs_dir or DEFAULT_CAPABILITY_RUNS_BASE
    evidence_base = validation_evidence_dir or DEFAULT_VALIDATION_EVIDENCE_BASE

    session_factory = None
    if refresh:
        engine = create_db_engine(db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)
    else:
        # Read-only: only attach to the db if it already exists (so persisted
        # state + discovery candidates can load) — never create one.
        url = get_database_url(db_path)
        existing = url.replace("sqlite:///", "", 1)
        if existing and _Path(existing).is_file():
            session_factory = make_session_factory(create_db_engine(db_path))

    registry = CapabilityStateRegistry(
        capability_runs_base=runs_base,
        validation_evidence_base=evidence_base,
        session_factory=session_factory,
    )

    if refresh:
        snapshot = registry.refresh()
        source = "refreshed"
    else:
        persisted = registry.load_snapshot() if session_factory else None
        if persisted is not None:
            snapshot = persisted
            source = "persisted"
        else:
            snapshot = registry.build_snapshot()
            source = "in-memory"

    # Inspect a single capability.
    if name:
        state = snapshot.get(name)
        if state is None:
            if as_json:
                console.print_json(_json.dumps({
                    "capability_name": name,
                    "known": False,
                    "reason": "unknown capability — no lifecycle state",
                    "known_capabilities": snapshot.names(),
                }))
            else:
                console.print(
                    f"[red]Capability '{name}' has no lifecycle state "
                    f"(unknown to the Capability State Registry).[/red]")
                if snapshot.names():
                    console.print(f"[dim]Known: {', '.join(snapshot.names())}[/dim]")
            raise SystemExit(2)

        if as_json:
            console.print_json(_json.dumps(state.to_dict()))
            return

        console.print(f"\n[bold blue]{state.capability_name}[/bold blue]  "
                      f"[{_STATE_COLOUR.get(state.current_status.value, 'white')}]"
                      f"{state.current_status.value}[/]")
        meta = Table(show_header=False, box=None)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("Adapter / type", f"{state.adapter} / {state.capability_type or '—'}")
        meta.add_row("Source", state.source_registry)
        meta.add_row("First seen / last seen",
                     f"{state.first_seen_at} / {state.last_seen_at}")
        meta.add_row("Last validation run", state.last_validation_run_id or "—")
        meta.add_row("Last execution run", state.last_execution_run_id or "—")
        meta.add_row("Last evidence path", state.last_evidence_path or "—")
        meta.add_row("Counts (pass/fail/refused/blocked/unsupported)",
                     f"{state.pass_count}/{state.fail_count}/{state.refused_count}/"
                     f"{state.blocked_count}/{state.unsupported_count}")
        meta.add_row("Promotion candidate",
                     "yes" if state.promotion_candidate else "no")
        meta.add_row("Last error", state.last_error_summary or "—")
        console.print(meta)
        return

    # List all capability states.
    if as_json:
        console.print_json(_json.dumps(snapshot.to_dict()))
        return

    console.print("\n[bold blue]Axiom Capability State Registry[/bold blue]  "
                  f"[dim]({len(snapshot.states)} capabilities — {source})[/dim]\n")
    table = Table()
    table.add_column("Capability")
    table.add_column("Status")
    table.add_column("Type")
    table.add_column("P/F/R/B/U", justify="center")
    table.add_column("Promo", justify="center")
    table.add_column("Last evidence")
    for state in snapshot.states:
        colour = _STATE_COLOUR.get(state.current_status.value, "white")
        table.add_row(
            state.capability_name,
            f"[{colour}]{state.current_status.value}[/{colour}]",
            state.capability_type or "—",
            f"{state.pass_count}/{state.fail_count}/{state.refused_count}/"
            f"{state.blocked_count}/{state.unsupported_count}",
            "[green]yes[/green]" if state.promotion_candidate else "—",
            (state.last_evidence_path or "—"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

_CATEGORY_COLOUR: dict[str, str] = {
    "passed": "green",
    "denied": "yellow",
    "refused": "cyan",
    "blocked": "red",
    "unsupported": "yellow",
    "execution_failed": "red",
    "transport_failed": "red",
    "prerequisite_missing": "red",
    "evidence_missing": "red",
    "validation_failed": "red",
    "timeout": "red",
    "parse_error": "red",
    "policy_violation": "magenta",
    "unknown_error": "red",
}


@cli.command("classify-failure")
@click.option("--evidence-path", "evidence_path", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Path to evidence bundle directory "
                   "(e.g. artifacts/capability_runs/<run_id>)")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output classification as JSON")
def classify_failure(evidence_path, as_json):
    """Classify an evidence bundle outcome into a durable failure category,
    severity level, and retry decision.

    Reads pass_fail.json from the given evidence directory and writes
    failure_classification.json + failure_classification.md into the same
    directory. Never overwrites pass_fail.json.

    Works on both capability-run and validation-run evidence bundles.
    """
    import json as _json
    from pathlib import Path

    from axiom_core.runner.failure_classification import (
        FailureClassificationEngine,
        write_classification,
    )

    engine = FailureClassificationEngine()
    summary = engine.classify(Path(evidence_path))

    json_path, md_path = write_classification(summary)

    if as_json:
        console.print_json(_json.dumps(summary.to_dict(), default=str))
        return

    cat = summary.category.value
    colour = _CATEGORY_COLOUR.get(cat, "white")
    console.print(f"\n[bold blue]Failure Classification[/bold blue]  "
                  f"[{colour}]{cat}[/{colour}]  "
                  f"[dim]({summary.severity.value})[/dim]\n")
    table = Table(show_header=False, box=None)
    table.add_column("k", style="cyan")
    table.add_column("v")
    table.add_row("Evidence path", summary.evidence_path)
    table.add_row("Bundle type", summary.bundle_type)
    table.add_row("Capability", summary.capability_name or "(unknown)")
    table.add_row("Outcome", summary.outcome)
    table.add_row("Category", f"[{colour}]{cat}[/{colour}]")
    table.add_row("Severity", summary.severity.value)
    table.add_row("Retry eligibility", summary.retry_eligibility.value)
    rd = summary.retry_decision
    table.add_row("Retry allowed", str(rd.retry_allowed))
    table.add_row("Retry recommended", str(rd.retry_recommended))
    table.add_row("Retry reason", rd.retry_reason)
    table.add_row("Max retries", str(rd.max_retries))
    table.add_row("Retry delay (sec)", str(rd.retry_delay_seconds))
    table.add_row("Requires human", str(rd.retry_requires_human))
    table.add_row("Requires env change", str(rd.retry_requires_environment_change))
    if summary.error_detail:
        table.add_row("Error detail", summary.error_detail)
    console.print(table)

    if summary.checks:
        console.print()
        ct = Table(title=f"Checks ({sum(1 for c in summary.checks if c.get('passed'))}/"
                         f"{len(summary.checks)} passed)")
        ct.add_column("Check")
        ct.add_column("Result")
        ct.add_column("Detail")
        for c in summary.checks:
            r = "[green]PASS[/green]" if c.get("passed") else "[red]FAIL[/red]"
            ct.add_row(c.get("name", ""), r, c.get("detail", ""))
        console.print(ct)

    console.print("\n[green]Classification written:[/green]")
    console.print(f"  {json_path}")
    console.print(f"  {md_path}")


# ---------------------------------------------------------------------------
# Promotion eligibility
# ---------------------------------------------------------------------------

_PROMOTION_COLOUR: dict[str, str] = {
    "eligible": "green",
    "not_eligible": "yellow",
    "needs_more_evidence": "yellow",
    "failed_recently": "red",
    "blocked": "red",
    "policy_refused": "magenta",
    "unknown": "red",
}


@cli.command("promotion-check")
@click.option("--capability", "capability", default=None,
              help="Capability to check (unknown capabilities exit non-zero).")
@click.option("--all", "check_all", is_flag=True, default=False,
              help="Check every known capability.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit machine-readable JSON instead of a table.")
@click.option("--no-write", "no_write", is_flag=True, default=False,
              help="Do not write the promotion_decision.json/.md evidence "
                   "record (default writes under artifacts/promotion_checks).")
@click.option("--out", "out_dir", default=None, type=click.Path(),
              help="Evidence output directory "
                   "(default: artifacts/promotion_checks/<run_id>).")
@click.option("--db-path", "db_path", default=None,
              help="SQLite db path for persisted state (default: ~/.axiom/axiom.db).")
@click.option("--capability-runs-dir", "capability_runs_dir", default=None,
              type=click.Path(),
              help="Base dir of Capability Runner evidence bundles "
                   "(default: artifacts/capability_runs).")
@click.option("--validation-evidence-dir", "validation_evidence_dir", default=None,
              type=click.Path(),
              help="Base dir of Validation Evidence Runner bundles "
                   "(default: artifacts/validation_evidence).")
def promotion_check(capability, check_all, as_json, no_write, out_dir, db_path,
                    capability_runs_dir, validation_evidence_dir):
    """Promotion Eligibility Engine — decide whether a capability is eligible to
    be promoted toward trusted status.

    Read-only governance: summarizes the Capability State Registry, Validation
    Registry, Command Registry, and Failure Classification artifacts into a
    deterministic promotion decision (eligible / needs_more_evidence /
    failed_recently / blocked / policy_refused / unknown). It promotes nothing,
    mutates no state or registry, executes nothing, retries nothing, and
    schedules nothing. Mutation/high-risk capabilities are not eligible in v1.

    An optional promotion_decision.json + .md evidence record is written under
    artifacts/promotion_checks/<run_id>/ (a report, not a state change).

    \b
    Examples:
      axiom promotion-check --capability InventoryModel
      axiom promotion-check --capability SetParameterValue
      axiom promotion-check --all
      axiom promotion-check --all --json
    """
    import json as _json
    from pathlib import Path as _Path

    from axiom_core.database import (
        create_db_engine,
        get_database_url,
        make_session_factory,
    )
    from axiom_core.runner.capability_state import (
        DEFAULT_CAPABILITY_RUNS_BASE,
        DEFAULT_VALIDATION_EVIDENCE_BASE,
        CapabilityStateRegistry,
    )
    from axiom_core.runner.promotion_eligibility import (
        DEFAULT_PROMOTION_CHECKS_BASE,
        PromotionEligibilityEngine,
        promotion_run_id,
        write_promotion_decisions,
    )

    if bool(capability) == bool(check_all):
        console.print("[red]Specify exactly one of --capability <name> or "
                      "--all.[/red]")
        raise SystemExit(2)

    runs_base = capability_runs_dir or DEFAULT_CAPABILITY_RUNS_BASE
    evidence_base = validation_evidence_dir or DEFAULT_VALIDATION_EVIDENCE_BASE

    # Read-only: attach to the db only if it already exists (so persisted state
    # + discovery candidates load) — never create one. promotion-check mutates
    # nothing.
    session_factory = None
    url = get_database_url(db_path)
    existing = url.replace("sqlite:///", "", 1)
    if existing and _Path(existing).is_file():
        session_factory = make_session_factory(create_db_engine(db_path))

    registry = CapabilityStateRegistry(
        capability_runs_base=runs_base,
        validation_evidence_base=evidence_base,
        session_factory=session_factory,
    )
    engine = PromotionEligibilityEngine(state_registry=registry)

    if check_all:
        decisions = engine.evaluate_all()
        scope = "all"
    else:
        decisions = [engine.evaluate(capability)]
        scope = capability

    json_path = md_path = None
    if not no_write:
        target = out_dir or str(
            _Path(DEFAULT_PROMOTION_CHECKS_BASE) / promotion_run_id(scope))
        json_path, md_path = write_promotion_decisions(decisions, out_dir=target)

    if as_json:
        if check_all:
            console.print_json(_json.dumps(
                {"decisions": [d.to_dict() for d in decisions]}, default=str))
        else:
            console.print_json(_json.dumps(decisions[0].to_dict(), default=str))
    elif check_all:
        console.print("\n[bold blue]Promotion Eligibility[/bold blue]  "
                      f"[dim]({len(decisions)} capabilities)[/dim]\n")
        table = Table()
        table.add_column("Capability")
        table.add_column("Status")
        table.add_column("Eligible", justify="center")
        table.add_column("Passing runs", justify="center")
        table.add_column("Reason")
        for d in decisions:
            colour = _PROMOTION_COLOUR.get(d.status.value, "white")
            table.add_row(
                d.capability_name,
                f"[{colour}]{d.status.value}[/{colour}]",
                "[green]yes[/green]" if d.eligible else "—",
                str(d.evidence.successful_runs),
                d.reason,
            )
        console.print(table)
    else:
        d = decisions[0]
        colour = _PROMOTION_COLOUR.get(d.status.value, "white")
        console.print(f"\n[bold blue]Promotion Eligibility[/bold blue]  "
                      f"[{colour}]{d.status.value}[/{colour}]  "
                      f"[dim]({'eligible' if d.eligible else 'not eligible'})"
                      f"[/dim]\n")
        meta = Table(show_header=False, box=None)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        ev = d.evidence
        meta.add_row("Capability", d.capability_name)
        meta.add_row("Status", f"[{colour}]{d.status.value}[/{colour}]")
        meta.add_row("Reason", d.reason)
        meta.add_row("Current status", ev.current_status)
        meta.add_row("Type / safety",
                     f"{ev.capability_type or '—'} / {ev.safety_level or '—'}")
        meta.add_row("Mutation / high-risk",
                     f"{ev.is_mutation} / {ev.is_high_risk}")
        meta.add_row("Validation defined", str(ev.validation_defined))
        meta.add_row("Passing runs (exec+val)",
                     f"{ev.successful_runs} ({ev.pass_count}+{ev.validation_pass_count})")
        meta.add_row("Evidence path", ev.last_evidence_path or "—")
        meta.add_row("Failure classification",
                     (f"{ev.latest_failure_category} ({ev.latest_failure_severity})"
                      if ev.failure_classification_present else "—"))
        console.print(meta)
        if d.blockers:
            console.print()
            bt = Table(title="Blockers")
            bt.add_column("Code", style="red")
            bt.add_column("Detail")
            for b in d.blockers:
                bt.add_row(b.code, b.detail)
            console.print(bt)

    if json_path is not None:
        console.print("\n[green]Promotion decision written:[/green]")
        console.print(f"  {json_path}")
        console.print(f"  {md_path}")

    # Unknown capability lookup exits non-zero.
    if not check_all and decisions[0].status.value == "unknown":
        raise SystemExit(2)


# ---------------------------------------------------------------------------
# Knowledge Source Registry
# ---------------------------------------------------------------------------


@cli.command("knowledge-sources")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter sources by name substring")
@click.option("--refresh", is_flag=True, help="Deterministic refresh of active sources")
@click.option("--include-disabled", is_flag=True, help="Include disabled sources in output")
def knowledge_sources_cmd(as_json: bool, name_filter: Optional[str], refresh: bool, include_disabled: bool):
    """List registered knowledge sources."""
    from axiom_core.knowledge_registry import KnowledgeSourceRegistry

    registry = KnowledgeSourceRegistry()

    if refresh:
        sources = registry.refresh(include_disabled=include_disabled, name_filter=name_filter)
    else:
        sources = registry.list_sources(include_disabled=include_disabled, name_filter=name_filter)

    if as_json:
        import json as json_mod

        output = [s.to_dict() for s in sources]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not sources:
        console.print("[dim]No knowledge sources registered.[/dim]")
        return

    table = Table(title="Knowledge Sources")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Trust")
    table.add_column("Path", style="dim")

    for s in sources:
        status_style = "green" if s.status.value == "active" else "yellow" if s.status.value == "deprecated" else "red"
        table.add_row(
            s.source_id,
            s.source_name,
            s.source_type.value if isinstance(s.source_type, Enum) else str(s.source_type),
            f"[{status_style}]{s.status.value}[/{status_style}]",
            s.trust_level,
            s.path or "",
        )

    console.print(table)
    console.print(f"\n[dim]{len(sources)} source(s) shown[/dim]")


# ---------------------------------------------------------------------------
# Knowledge Object Model
# ---------------------------------------------------------------------------


@cli.command("knowledge-objects")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter objects by name substring")
@click.option("--type", "obj_type", default=None, help="Filter by object type")
def knowledge_objects_cmd(as_json: bool, name_filter: Optional[str], obj_type: Optional[str]):
    """List registered knowledge objects."""
    from axiom_core.knowledge_objects import KnowledgeObjectRegistry, KnowledgeObjectType

    registry = KnowledgeObjectRegistry()

    type_filter = None
    if obj_type is not None:
        try:
            type_filter = KnowledgeObjectType(obj_type)
        except ValueError:
            console.print(f"[red]Unknown object type: {obj_type}[/red]")
            console.print(f"[dim]Valid types: {', '.join(t.value for t in KnowledgeObjectType)}[/dim]")
            raise SystemExit(1)

    objects = registry.list_objects(object_type=type_filter, name_filter=name_filter)

    if as_json:
        import json as json_mod

        output = [o.to_dict() for o in objects]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not objects:
        console.print("[dim]No knowledge objects registered.[/dim]")
        return

    table = Table(title="Knowledge Objects")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Version")
    table.add_column("Source ID", style="dim")
    table.add_column("Description", style="dim")

    for o in objects:
        table.add_row(
            o.object_id,
            o.object_name,
            o.object_type.value if isinstance(o.object_type, Enum) else str(o.object_type),
            o.version,
            o.source_id or "",
            (o.description or "")[:50],
        )

    console.print(table)
    console.print(f"\n[dim]{len(objects)} object(s) shown[/dim]")


@cli.command("knowledge-relationships")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--object-id", "object_id", default=None, help="Filter by object ID (source or target)")
@click.option("--type", "rel_type", default=None, help="Filter by relationship type")
def knowledge_relationships_cmd(as_json: bool, object_id: Optional[str], rel_type: Optional[str]):
    """List knowledge object relationships."""
    from axiom_core.knowledge_objects import KnowledgeObjectRegistry, RelationshipType

    registry = KnowledgeObjectRegistry()

    type_filter = None
    if rel_type is not None:
        try:
            type_filter = RelationshipType(rel_type)
        except ValueError:
            console.print(f"[red]Unknown relationship type: {rel_type}[/red]")
            console.print(f"[dim]Valid types: {', '.join(t.value for t in RelationshipType)}[/dim]")
            raise SystemExit(1)

    rels = registry.list_relationships(object_id=object_id, relationship_type=type_filter)

    if as_json:
        import json as json_mod

        output = [r.to_dict() for r in rels]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not rels:
        console.print("[dim]No knowledge relationships registered.[/dim]")
        return

    table = Table(title="Knowledge Relationships")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Source", style="bold")
    table.add_column("Type")
    table.add_column("Target", style="bold")
    table.add_column("Notes", style="dim")

    for r in rels:
        table.add_row(
            r.relationship_id[:12] + "…",
            r.source_object_id,
            r.relationship_type.value if isinstance(r.relationship_type, Enum) else str(r.relationship_type),
            r.target_object_id,
            (r.notes or "")[:40],
        )

    console.print(table)
    console.print(f"\n[dim]{len(rels)} relationship(s) shown[/dim]")


@cli.command("knowledge-provenance")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter by knowledge name substring")
@click.option("--trust-level", "trust_level", default=None, help="Filter by trust level")
@click.option("--include-deprecated", is_flag=True, help="Include deprecated provenance records")
def knowledge_provenance_cmd(
    as_json: bool,
    name_filter: Optional[str],
    trust_level: Optional[str],
    include_deprecated: bool,
):
    """List knowledge provenance and trust records."""
    from axiom_core.knowledge_provenance import KnowledgeProvenanceRegistry, TrustLevel

    registry = KnowledgeProvenanceRegistry()

    level_filter = None
    if trust_level is not None:
        try:
            level_filter = TrustLevel(trust_level)
        except ValueError:
            console.print(f"[red]Unknown trust level: {trust_level}[/red]")
            console.print(f"[dim]Valid levels: {', '.join(t.value for t in TrustLevel)}[/dim]")
            raise SystemExit(1)

    records = registry.list_provenance(
        name_filter=name_filter,
        trust_level=level_filter,
        include_deprecated=include_deprecated,
    )

    if as_json:
        import json as json_mod

        output = [r.to_dict() for r in records]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not records:
        console.print("[dim]No knowledge provenance records registered.[/dim]")
        return

    table = Table(title="Knowledge Provenance")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Trust Level")
    table.add_column("Confidence")
    table.add_column("Status")
    table.add_column("Origin", style="dim")
    table.add_column("Superseded By", style="dim")

    for r in records:
        table.add_row(
            r.provenance_id[:12] + "…",
            r.knowledge_name,
            r.trust_level.value if isinstance(r.trust_level, Enum) else str(r.trust_level),
            r.source_confidence.value if isinstance(r.source_confidence, Enum) else str(r.source_confidence),
            r.status.value if isinstance(r.status, Enum) else str(r.status),
            (r.origin or "")[:30],
            (r.superseded_by or "")[:12],
        )

    console.print(table)
    console.print(f"\n[dim]{len(records)} provenance record(s) shown[/dim]")


@cli.command("workflows")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter by workflow name substring")
@click.option("--include-deprecated", is_flag=True, help="Include deprecated workflows")
def workflows_cmd(as_json: bool, name_filter: Optional[str], include_deprecated: bool):
    """List registered workflow knowledge definitions."""
    from axiom_core.workflow_registry import WorkflowKnowledgeRegistry

    registry = WorkflowKnowledgeRegistry()
    workflows = registry.list_workflows(
        name_filter=name_filter, include_deprecated=include_deprecated
    )

    if as_json:
        import json as json_mod

        output = [w.to_dict() for w in workflows]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not workflows:
        console.print("[dim]No workflow definitions registered.[/dim]")
        return

    table = Table(title="Workflow Knowledge Registry")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Steps", justify="right")
    table.add_column("Rules", justify="right")
    table.add_column("Description", style="dim")

    for w in workflows:
        table.add_row(
            w.workflow_id[:12] + "…" if len(w.workflow_id) > 12 else w.workflow_id,
            w.workflow_name,
            w.status.value if isinstance(w.status, Enum) else str(w.status),
            w.version,
            str(len(w.steps)),
            str(len(w.rules)),
            (w.description or "")[:40],
        )

    console.print(table)
    console.print(f"\n[dim]{len(workflows)} workflow(s) shown[/dim]")


@cli.command("learning-candidates")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter by candidate name substring")
@click.option("--type", "ctype", default=None, help="Filter by candidate type")
@click.option("--include-dismissed", is_flag=True, help="Include dismissed candidates")
def learning_candidates_cmd(
    as_json: bool, name_filter: Optional[str], ctype: Optional[str], include_dismissed: bool
):
    """List learning candidates — patterns worth learning."""
    from axiom_core.learning_candidates import (
        CandidateType,
        LearningCandidateRegistry,
    )

    registry = LearningCandidateRegistry()

    candidate_type = None
    if ctype:
        try:
            candidate_type = CandidateType(ctype)
        except ValueError:
            console.print(f"[red]Unknown candidate type: {ctype}[/red]")
            console.print(f"[dim]Valid types: {', '.join(t.value for t in CandidateType)}[/dim]")
            raise SystemExit(1)

    candidates = registry.list_candidates(
        name_filter=name_filter,
        candidate_type=candidate_type,
        include_dismissed=include_dismissed,
    )

    if as_json:
        import json as json_mod

        output = [c.to_dict() for c in candidates]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not candidates:
        console.print("[dim]No learning candidates identified.[/dim]")
        return

    table = Table(title="Learning Candidates")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Strength")
    table.add_column("Score", justify="right")
    table.add_column("Observations", justify="right")
    table.add_column("Evidence", justify="right")

    for c in candidates:
        table.add_row(
            c.candidate_id[:12] + "…" if len(c.candidate_id) > 12 else c.candidate_id,
            c.candidate_name,
            c.candidate_type.value if isinstance(c.candidate_type, Enum) else str(c.candidate_type),
            c.strength.value if isinstance(c.strength, Enum) else str(c.strength),
            str(c.confidence_score),
            str(c.observation_count),
            str(len(c.evidence)),
        )

    console.print(table)
    console.print(f"\n[dim]{len(candidates)} candidate(s) shown[/dim]")


@cli.command("knowledge-reviews")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter by knowledge name substring")
@click.option("--decision", "decision_str", default=None, help="Filter by decision (e.g. approved, rejected)")
@click.option("--status", "status_str", default=None, help="Filter by status (open, closed)")
def knowledge_reviews_cmd(
    as_json: bool,
    name_filter: Optional[str],
    decision_str: Optional[str],
    status_str: Optional[str],
):
    """List knowledge review and approval records."""
    from axiom_core.knowledge_reviews import (
        KnowledgeReviewRegistry,
        ReviewDecision,
        ReviewStatus,
    )

    registry = KnowledgeReviewRegistry()

    decision_filter = None
    if decision_str is not None:
        try:
            decision_filter = ReviewDecision(decision_str)
        except ValueError:
            console.print(f"[red]Unknown decision: {decision_str}[/red]")
            console.print(f"[dim]Valid decisions: {', '.join(d.value for d in ReviewDecision)}[/dim]")
            raise SystemExit(1)

    status_filter = None
    if status_str is not None:
        try:
            status_filter = ReviewStatus(status_str)
        except ValueError:
            console.print(f"[red]Unknown status: {status_str}[/red]")
            console.print(f"[dim]Valid statuses: {', '.join(s.value for s in ReviewStatus)}[/dim]")
            raise SystemExit(1)

    reviews = registry.list_reviews(
        name_filter=name_filter,
        decision_filter=decision_filter,
        status_filter=status_filter,
    )

    if as_json:
        import json as json_mod

        output = [r.to_dict() for r in reviews]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not reviews:
        console.print("[dim]No knowledge reviews registered.[/dim]")
        return

    table = Table(title="Knowledge Reviews")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Knowledge", style="bold")
    table.add_column("Decision")
    table.add_column("Reason")
    table.add_column("Status")
    table.add_column("Reviewer", style="dim")
    table.add_column("Superseded By", style="dim")

    for r in reviews:
        table.add_row(
            r.review_id[:12] + "…" if len(r.review_id) > 12 else r.review_id,
            r.knowledge_name,
            r.decision.value if isinstance(r.decision, Enum) else str(r.decision),
            r.reason.value if isinstance(r.reason, Enum) else str(r.reason),
            r.status.value if isinstance(r.status, Enum) else str(r.status),
            (r.reviewer or "")[:20],
            (r.superseded_by or "")[:12],
        )

    console.print(table)
    console.print(f"\n[dim]{len(reviews)} review(s) shown[/dim]")


@cli.command("knowledge-review-create")
@click.option("--knowledge-id", required=True, help="ID of the knowledge item to review")
@click.option("--knowledge-name", required=True, help="Name of the knowledge item")
@click.option("--decision", required=True, help="Review decision (e.g. approved, rejected, proposed)")
@click.option("--reason", required=True, help="Reason for the decision")
@click.option("--notes", default=None, help="Optional notes")
@click.option("--reviewer", default=None, help="Reviewer identifier")
@click.option("--json-output", "as_json", is_flag=True, help="Output created review as JSON")
def knowledge_review_create_cmd(
    knowledge_id: str,
    knowledge_name: str,
    decision: str,
    reason: str,
    notes: Optional[str],
    reviewer: Optional[str],
    as_json: bool,
):
    """Create a new knowledge review record."""
    from axiom_core.knowledge_reviews import (
        KnowledgeReview,
        KnowledgeReviewRegistry,
        ReviewDecision,
        ReviewReason,
    )

    try:
        dec = ReviewDecision(decision)
    except ValueError:
        console.print(f"[red]Unknown decision: {decision}[/red]")
        console.print(f"[dim]Valid decisions: {', '.join(d.value for d in ReviewDecision)}[/dim]")
        raise SystemExit(1)

    try:
        rsn = ReviewReason(reason)
    except ValueError:
        console.print(f"[red]Unknown reason: {reason}[/red]")
        console.print(f"[dim]Valid reasons: {', '.join(r.value for r in ReviewReason)}[/dim]")
        raise SystemExit(1)

    registry = KnowledgeReviewRegistry()
    review = KnowledgeReview(
        knowledge_id=knowledge_id,
        knowledge_name=knowledge_name,
        decision=dec,
        reason=rsn,
        notes=notes,
        reviewer=reviewer,
    )
    created = registry.create_review(review)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(created.to_dict(), indent=2, default=str))
    else:
        console.print(f"[green]Review created:[/green] {created.review_id}")
        console.print(f"  Knowledge: {created.knowledge_name}")
        console.print(f"  Decision:  {created.decision.value}")
        console.print(f"  Reason:    {created.reason.value}")


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------


@cli.command("knowledge-graph")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--refresh", is_flag=True, help="Rebuild graph from existing registries")
@click.option("--node", "node_id", default=None, help="Look up a specific node by ID")
@click.option("--neighbors", "neighbor_id", default=None, help="List neighbors of a node")
@click.option("--depth", "depth", default=None, type=int, help="Traversal depth (used with --neighbors)")
def knowledge_graph_cmd(
    as_json: bool,
    refresh: bool,
    node_id: Optional[str],
    neighbor_id: Optional[str],
    depth: Optional[int],
):
    """Knowledge graph summary, node lookup, or neighbor traversal."""
    from axiom_core.knowledge_graph import (
        MAX_TRAVERSAL_DEPTH,
        KnowledgeGraph,
    )

    graph = KnowledgeGraph()

    # --- Refresh ---
    if refresh:
        snapshot = graph.build_from_registries()
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps(snapshot.to_dict(), indent=2, default=str))
        else:
            console.print("[green]Graph rebuilt from registries[/green]")
            console.print(f"  Nodes: {snapshot.node_count}")
            console.print(f"  Edges: {snapshot.edge_count}")
            console.print(f"  Node types: {', '.join(snapshot.node_types)}")
            console.print(f"  Edge types: {', '.join(snapshot.edge_types)}")
            console.print(f"  Source registries: {', '.join(snapshot.source_registries)}")
            console.print(f"  Snapshot: {snapshot.snapshot_id}")
        return

    # --- Node lookup ---
    if node_id is not None:
        node = graph.get_node(node_id)
        if node is None:
            console.print(f"[red]Node not found: {node_id}[/red]")
            raise SystemExit(1)
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps(node.to_dict(), indent=2, default=str))
        else:
            console.print(f"[bold]{node.label}[/bold]")
            console.print(f"  ID:       {node.node_id}")
            nt = node.node_type.value if isinstance(node.node_type, Enum) else str(node.node_type)
            console.print(f"  Type:     {nt}")
            console.print(f"  Registry: {node.source_registry}")
            if node.metadata:
                for k, v in node.metadata.items():
                    console.print(f"  {k}: {v}")
        return

    # --- Neighbor traversal ---
    if neighbor_id is not None:
        effective_depth = max(0, min(depth if depth is not None else 1, MAX_TRAVERSAL_DEPTH))
        result = graph.traverse(neighbor_id, max_depth=effective_depth)
        if not result.visited_nodes:
            console.print(f"[red]Node not found: {neighbor_id}[/red]")
            raise SystemExit(1)
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps(result.to_dict(), indent=2, default=str))
        else:
            console.print(f"[bold]Traversal from {neighbor_id} (depth={effective_depth})[/bold]")
            console.print(f"  Nodes visited: {len(result.visited_nodes)}")
            console.print(f"  Edges visited: {len(result.visited_edges)}")
            console.print(f"  Cycle detected: {result.cycle_detected}")
            table = Table(title="Visited Nodes")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Label", style="bold")
            table.add_column("Type")
            table.add_column("Registry", style="dim")
            for n in result.visited_nodes:
                nt = n.node_type.value if isinstance(n.node_type, Enum) else str(n.node_type)
                table.add_row(
                    n.node_id[:20] + "…" if len(n.node_id) > 20 else n.node_id,
                    n.label,
                    nt,
                    n.source_registry,
                )
            console.print(table)
        return

    # --- Default: summary ---
    snapshot = graph.get_latest_snapshot()
    if as_json:
        import json as json_mod

        click.echo(graph.to_json())
        return

    if snapshot is None:
        console.print("[dim]No graph snapshot available. Run --refresh to build.[/dim]")
        return

    console.print("[bold]Knowledge Graph Summary[/bold]")
    console.print(f"  Nodes: {snapshot.node_count}")
    console.print(f"  Edges: {snapshot.edge_count}")
    console.print(f"  Node types: {', '.join(snapshot.node_types)}")
    console.print(f"  Edge types: {', '.join(snapshot.edge_types)}")
    console.print(f"  Source registries: {', '.join(snapshot.source_registries)}")
    console.print(f"  Snapshot: {snapshot.snapshot_id}")
    console.print(f"  Created: {snapshot.created_at}")


@cli.command("retrieve")
@click.argument("query_text")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--type", "query_type", default=None, help="Filter by node type (workflow, capability, rule, etc.)")
@click.option("--max-results", "max_results", default=None, type=int, help="Maximum results to return")
def retrieve_cmd(
    query_text: str,
    as_json: bool,
    query_type: Optional[str],
    max_results: Optional[int],
):
    """Retrieve knowledge by query text."""
    from axiom_core.semantic_retrieval import (
        MAX_RESULTS_DEFAULT,
        VALID_QUERY_TYPES,
        RetrievalQuery,
        SemanticRetrievalEngine,
    )

    if not query_text.strip():
        console.print("[red]Error: query text must not be empty.[/red]")
        raise SystemExit(1)

    if query_type is not None and query_type.lower() not in VALID_QUERY_TYPES:
        console.print(f"[red]Unknown type: {query_type}[/red]")
        console.print(f"Valid types: {', '.join(sorted(VALID_QUERY_TYPES))}")
        raise SystemExit(1)

    effective_max = max_results if max_results is not None else MAX_RESULTS_DEFAULT
    query = RetrievalQuery(
        query_text=query_text,
        query_type=query_type,
        max_results=effective_max,
    )

    engine = SemanticRetrievalEngine()
    result = engine.retrieve(query)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(result.to_dict(), indent=2, default=str))
        return

    if not result.matches:
        console.print(f"[dim]No results found for: {query_text}[/dim]")
        return

    console.print(f"[bold]Results for '{query_text}'[/bold] ({result.total_candidates} candidates, showing {len(result.matches)})")
    console.print()

    table = Table(title="Retrieval Results")
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Score", justify="right")
    table.add_column("Trust", style="green")
    table.add_column("Explanation", style="dim")

    for i, m in enumerate(result.matches, 1):
        ot = m.object_type
        trust = m.trust_level or "-"
        explanation = m.explanation.reason[:50] if m.explanation else "-"
        table.add_row(
            str(i),
            m.object_name,
            ot,
            f"{m.score:.1f}",
            trust,
            explanation,
        )

    console.print(table)


@cli.command("capability-plan")
@click.argument("objective")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--max-steps", "max_steps", default=None, type=int, help="Maximum planning steps")
def plan_capability_cmd(
    objective: str,
    as_json: bool,
    max_steps: Optional[int],
):
    """Generate a knowledge-aware capability plan."""
    from axiom_core.capability_planner import (
        MAX_STEPS_DEFAULT,
        CapabilityPlanner,
        PlanningRequest,
    )

    if not objective.strip():
        console.print("[red]Error: planning objective must not be empty.[/red]")
        raise SystemExit(1)

    effective_max = max_steps if max_steps is not None else MAX_STEPS_DEFAULT
    request = PlanningRequest(objective=objective, max_steps=effective_max)

    planner = CapabilityPlanner()
    result = planner.generate_plan(request)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(result.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]Plan: {result.objective}[/bold]")
    console.print(f"[dim]ID: {result.plan_id}[/dim]")
    console.print(f"[dim]Status: {result.status.value}[/dim]")
    console.print()

    if result.assumptions:
        console.print("[bold cyan]Assumptions:[/bold cyan]")
        for a in result.assumptions:
            console.print(f"  • {a}")
        console.print()

    if result.steps:
        table = Table(title="Planning Steps")
        table.add_column("#", style="dim", width=3)
        table.add_column("Title", style="bold")
        table.add_column("Description", style="dim")
        table.add_column("Capabilities")
        table.add_column("Explanation", style="dim")

        for s in result.steps:
            caps = ", ".join(s.required_capabilities) if s.required_capabilities else "-"
            explanation = s.explanation.reason[:50] if s.explanation else "-"
            table.add_row(
                str(s.sequence),
                s.title,
                (s.description or "")[:40],
                caps,
                explanation,
            )
        console.print(table)
        console.print()

    if result.risks:
        console.print("[bold yellow]Risks:[/bold yellow]")
        for r in result.risks:
            console.print(f"  ⚠ {r}")
        console.print()

    if result.validations:
        console.print("[bold green]Validations Required:[/bold green]")
        for v in result.validations:
            console.print(f"  ✓ {v}")
        console.print()

    if result.explanations:
        console.print("[bold]Plan Explanations:[/bold]")
        for e in result.explanations:
            src = f" ({e.source})" if e.source else ""
            console.print(f"  → {e.reason}{src}")
        console.print()

    console.print(f"[dim]{len(result.steps)} step(s), {len(result.dependencies)} dependency(ies)[/dim]")


# ---------------------------------------------------------------------------
# Plan Review Queue commands (PR #51)
# ---------------------------------------------------------------------------


@cli.command("plan-reviews")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--name", "name_filter", default=None, help="Filter by plan name substring")
@click.option("--decision", "decision_str", default=None, help="Filter by decision (e.g. approved, rejected)")
@click.option("--status", "status_str", default=None, help="Filter by status (open, closed)")
@click.option("--plan-id", "plan_id", default=None, help="Show all reviews for a specific plan ID")
def plan_reviews_cmd(
    as_json: bool,
    name_filter: Optional[str],
    decision_str: Optional[str],
    status_str: Optional[str],
    plan_id: Optional[str],
):
    """List plan review and approval records."""
    from enum import Enum

    from axiom_core.plan_reviews import (
        PlanReviewDecision,
        PlanReviewRegistry,
        PlanReviewStatus,
    )

    registry = PlanReviewRegistry()

    # Single-plan history mode
    if plan_id is not None:
        history = registry.get_history(plan_id)
        if not history.reviews:
            if as_json:
                import json as json_mod

                click.echo(json_mod.dumps(history.to_dict(), indent=2, default=str))
            else:
                console.print(f"[dim]No reviews found for plan: {plan_id}[/dim]")
            raise SystemExit(2)
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps(history.to_dict(), indent=2, default=str))
            return
        console.print(f"\n[bold]Review History: {plan_id}[/bold]")
        console.print(f"[dim]Latest decision: {history.latest_decision.value if history.latest_decision else 'none'}[/dim]\n")
        table = Table(title="Plan Review History")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Decision")
        table.add_column("Reason")
        table.add_column("Status")
        table.add_column("Reviewer", style="dim")
        table.add_column("Created", style="dim")
        for r in history.reviews:
            table.add_row(
                r.review_id[:12] + "…" if len(r.review_id) > 12 else r.review_id,
                r.decision.value if isinstance(r.decision, Enum) else str(r.decision),
                r.reason.value if isinstance(r.reason, Enum) else str(r.reason),
                r.status.value if isinstance(r.status, Enum) else str(r.status),
                (r.reviewer or "")[:20],
                r.created_at[:19] if r.created_at else "",
            )
        console.print(table)
        console.print(f"\n[dim]{len(history.reviews)} review(s) shown[/dim]")
        return

    # List mode
    decision_filter = None
    if decision_str is not None:
        try:
            decision_filter = PlanReviewDecision(decision_str)
        except ValueError:
            console.print(f"[red]Unknown decision: {decision_str}[/red]")
            console.print(f"[dim]Valid decisions: {', '.join(d.value for d in PlanReviewDecision)}[/dim]")
            raise SystemExit(1)

    status_filter = None
    if status_str is not None:
        try:
            status_filter = PlanReviewStatus(status_str)
        except ValueError:
            console.print(f"[red]Unknown status: {status_str}[/red]")
            console.print(f"[dim]Valid statuses: {', '.join(s.value for s in PlanReviewStatus)}[/dim]")
            raise SystemExit(1)

    reviews = registry.list_reviews(
        name_filter=name_filter,
        decision_filter=decision_filter,
        status_filter=status_filter,
    )

    if as_json:
        import json as json_mod

        output = [r.to_dict() for r in reviews]
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    if not reviews:
        console.print("[dim]No plan reviews registered.[/dim]")
        return

    table = Table(title="Plan Reviews")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Plan ID", style="bold")
    table.add_column("Plan Name", style="bold")
    table.add_column("Decision")
    table.add_column("Reason")
    table.add_column("Status")
    table.add_column("Reviewer", style="dim")

    for r in reviews:
        table.add_row(
            r.review_id[:12] + "…" if len(r.review_id) > 12 else r.review_id,
            r.plan_id[:12] + "…" if len(r.plan_id) > 12 else r.plan_id,
            r.plan_name,
            r.decision.value if isinstance(r.decision, Enum) else str(r.decision),
            r.reason.value if isinstance(r.reason, Enum) else str(r.reason),
            r.status.value if isinstance(r.status, Enum) else str(r.status),
            (r.reviewer or "")[:20],
        )

    console.print(table)
    console.print(f"\n[dim]{len(reviews)} review(s) shown[/dim]")


@cli.command("plan-review")
@click.option("--plan-id", required=True, help="Plan ID to look up")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def plan_review_cmd(
    plan_id: str,
    as_json: bool,
):
    """Show review details for a specific plan ID."""
    from axiom_core.plan_reviews import PlanReviewRegistry

    registry = PlanReviewRegistry()
    history = registry.get_history(plan_id)

    if not history.reviews:
        console.print(f"[red]No reviews found for plan: {plan_id}[/red]")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(history.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]Plan Review: {plan_id}[/bold]")
    latest = history.reviews[-1]
    console.print(f"  Plan Name:  {latest.plan_name}")
    console.print(f"  Decision:   {latest.decision.value}")
    console.print(f"  Reason:     {latest.reason.value}")
    console.print(f"  Status:     {latest.status.value}")
    console.print(f"  Reviewer:   {latest.reviewer or '(none)'}")
    console.print(f"  Created:    {latest.created_at}")
    if latest.notes:
        console.print(f"  Notes:      {latest.notes}")
    if latest.evidence:
        console.print(f"  Evidence:   {len(latest.evidence)} item(s)")
    console.print(f"\n[dim]Total reviews for this plan: {len(history.reviews)}[/dim]")


@cli.command("plan-review-create")
@click.option("--plan-id", required=True, help="ID of the plan to review")
@click.option("--plan-name", default=None, help="Name of the plan (defaults to plan-id if omitted)")
@click.option("--decision", required=True, help="Review decision (proposed, approved, rejected, deferred, needs_more_evidence, superseded)")
@click.option("--reason", required=True, help="Reason for the decision")
@click.option("--notes", default=None, help="Optional notes")
@click.option("--reviewer", default=None, help="Reviewer identifier")
@click.option("--json-output", "as_json", is_flag=True, help="Output created review as JSON")
def plan_review_create_cmd(
    plan_id: str,
    plan_name: Optional[str],
    decision: str,
    reason: str,
    notes: Optional[str],
    reviewer: Optional[str],
    as_json: bool,
):
    """Create a new plan review record."""
    from axiom_core.plan_reviews import (
        PlanReview,
        PlanReviewDecision,
        PlanReviewReason,
        PlanReviewRegistry,
    )

    try:
        dec = PlanReviewDecision(decision)
    except ValueError:
        console.print(f"[red]Unknown decision: {decision}[/red]")
        console.print(f"[dim]Valid decisions: {', '.join(d.value for d in PlanReviewDecision)}[/dim]")
        raise SystemExit(1)

    try:
        rsn = PlanReviewReason(reason)
    except ValueError:
        console.print(f"[red]Unknown reason: {reason}[/red]")
        console.print(f"[dim]Valid reasons: {', '.join(r.value for r in PlanReviewReason)}[/dim]")
        raise SystemExit(1)

    effective_name = plan_name or plan_id

    registry = PlanReviewRegistry()
    review = PlanReview(
        plan_id=plan_id,
        plan_name=effective_name,
        decision=dec,
        reason=rsn,
        notes=notes,
        reviewer=reviewer,
    )
    created = registry.create_review(review)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(created.to_dict(), indent=2, default=str))
        return

    console.print(f"[green]Plan review created:[/green] {created.review_id}")
    console.print(f"  Plan:     {created.plan_id}")
    console.print(f"  Decision: {created.decision.value}")
    console.print(f"  Reason:   {created.reason.value}")


# ---------------------------------------------------------------------------
# Controlled Discovery Loop commands (PR #55)
# ---------------------------------------------------------------------------


@cli.command("discovery-loop")
@click.option("--source", default=None, help="Source folder or identifier for discovery")
@click.option("--simulate/--no-simulate", default=False, help="Simulate mode (no real execution)")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def discovery_loop_cmd(
    source: Optional[str],
    simulate: bool,
    as_json: bool,
):
    """Run a controlled discovery loop."""
    from axiom_core.controlled_discovery_loop import ControlledDiscoveryLoop

    loop = ControlledDiscoveryLoop()
    result = loop.run(source=source, simulate=simulate)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(result.to_dict(), indent=2, default=str))
        return

    status_color = "green" if result.status.value in ("completed", "simulated") else "red"
    console.print(f"\n[bold]Discovery Loop: {result.run_id}[/bold]")
    console.print(f"  Status:     [{status_color}]{result.status.value}[/{status_color}]")
    console.print(f"  Source:     {result.source or 'default'}")
    console.print(f"  Simulate:   {result.simulate}")
    console.print(f"  Steps:      {result.step_count}")
    console.print(f"  Candidates: {result.candidates_generated}")
    console.print(f"  Validated:  {result.validations_executed}")
    console.print(f"  Promotions: checked={result.promotions_checked} applied={result.promotions_applied}")

    if result.refusal_reason:
        console.print(f"  [red]Refused:[/red] {result.refusal_reason}")


# ---------------------------------------------------------------------------
# Trusted Capability Registry commands (PR #54)
# ---------------------------------------------------------------------------


@cli.command("trusted-capabilities")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--status", "status_str", default=None, help="Filter by trust status")
def trusted_capabilities_cmd(
    as_json: bool,
    status_str: Optional[str],
):
    """List trusted capabilities."""
    from axiom_core.trusted_capabilities import TrustedCapabilityRegistry, TrustStatus

    registry = TrustedCapabilityRegistry()

    status_filter = None
    if status_str is not None:
        try:
            status_filter = TrustStatus(status_str)
        except ValueError:
            valid = ", ".join(s.value for s in TrustStatus)
            console.print(f"[red]Invalid status:[/red] {status_str}. Valid: {valid}")
            raise SystemExit(1)

    capabilities = registry.list_capabilities(status_filter=status_filter)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([c.to_dict() for c in capabilities], indent=2, default=str))
        return

    if not capabilities:
        console.print("[dim]No trusted capabilities found.[/dim]")
        return

    table = Table(title="Trusted Capabilities")
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Validations")
    table.add_column("Failures")
    table.add_column("Promoted By")
    for c in capabilities:
        table.add_row(
            c.capability_name,
            c.trust_status.value,
            str(c.validation_count),
            str(c.failure_count),
            c.promoted_by or "-",
        )
    console.print(table)


@cli.command("trusted-capability")
@click.option("--name", required=True, help="Capability name")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def trusted_capability_cmd(
    name: str,
    as_json: bool,
):
    """Show trust details for a specific capability."""
    from axiom_core.trusted_capabilities import TrustedCapabilityRegistry

    registry = TrustedCapabilityRegistry()
    cap = registry.get_capability(name)

    if cap is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "capability": name}, indent=2))
        else:
            console.print(f"[red]Capability not found:[/red] {name}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(cap.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]Trusted Capability: {cap.capability_name}[/bold]")
    console.print(f"  Status:      {cap.trust_status.value}")
    console.print(f"  Validations: {cap.validation_count}")
    console.print(f"  Failures:    {cap.failure_count}")
    if cap.promoted_by:
        console.print(f"  Promoted by: {cap.promoted_by} at {cap.promoted_at}")
    if cap.revoked_by:
        console.print(f"  Revoked by:  {cap.revoked_by} at {cap.revoked_at}")
        console.print(f"  Reason:      {cap.revocation_reason}")


@cli.command("trusted-capability-promote")
@click.option("--capability", required=True, help="Capability name to promote")
@click.option("--by", "promoted_by", default="human", help="Who is promoting")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def trusted_capability_promote_cmd(
    capability: str,
    promoted_by: str,
    as_json: bool,
):
    """Explicitly promote a capability to trusted status."""
    from axiom_core.trusted_capabilities import TrustedCapabilityRegistry

    registry = TrustedCapabilityRegistry()
    try:
        cap = registry.promote(capability, promoted_by=promoted_by)
    except ValueError as e:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "promotion_refused", "reason": str(e)}, indent=2))
        else:
            console.print(f"[red]Promotion refused:[/red] {e}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(cap.to_dict(), indent=2, default=str))
        return

    console.print(f"[green]Promoted:[/green] {cap.capability_name} → trusted")
    console.print(f"  By: {cap.promoted_by}")


@cli.command("trusted-capability-revoke")
@click.option("--capability", required=True, help="Capability name to revoke")
@click.option("--by", "revoked_by", default="human", help="Who is revoking")
@click.option("--reason", default="", help="Reason for revocation")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def trusted_capability_revoke_cmd(
    capability: str,
    revoked_by: str,
    reason: str,
    as_json: bool,
):
    """Revoke trust from a capability."""
    from axiom_core.trusted_capabilities import TrustedCapabilityRegistry

    registry = TrustedCapabilityRegistry()
    cap = registry.revoke(capability, revoked_by=revoked_by, reason=reason)

    if cap is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "capability": capability}, indent=2))
        else:
            console.print(f"[red]Capability not found:[/red] {capability}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(cap.to_dict(), indent=2, default=str))
        return

    console.print(f"[yellow]Revoked:[/yellow] {cap.capability_name}")
    console.print(f"  By:     {cap.revoked_by}")
    console.print(f"  Reason: {cap.revocation_reason}")


# ---------------------------------------------------------------------------
# Validation Request Generator commands (PR #52)
# ---------------------------------------------------------------------------


@cli.command("validation-requests")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--status", "status_str", default=None, help="Filter by status (pending, ready, blocked, completed, cancelled)")
@click.option("--plan-id", "plan_id", default=None, help="Filter by plan ID")
def validation_requests_cmd(
    as_json: bool,
    status_str: Optional[str],
    plan_id: Optional[str],
):
    """List validation requests."""
    from axiom_core.validation_requests import (
        ValidationRequestGenerator,
        ValidationRequestStatus,
    )

    generator = ValidationRequestGenerator()

    status_filter = None
    if status_str is not None:
        try:
            status_filter = ValidationRequestStatus(status_str)
        except ValueError:
            valid = ", ".join(s.value for s in ValidationRequestStatus)
            console.print(f"[red]Invalid status:[/red] {status_str}. Valid: {valid}")
            raise SystemExit(1)

    requests = generator.list_requests(status_filter=status_filter, plan_id_filter=plan_id)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([r.to_dict() for r in requests], indent=2, default=str))
        return

    if not requests:
        console.print("[dim]No validation requests found.[/dim]")
        return

    table = Table(title="Validation Requests")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Plan ID")
    table.add_column("Plan Name")
    table.add_column("Status")
    table.add_column("Steps")
    table.add_column("Blockers")
    for r in requests:
        table.add_row(
            r.request_id[:12],
            r.plan_id[:16],
            r.plan_name[:30],
            r.status.value,
            str(len(r.steps)),
            str(len(r.blockers)),
        )
    console.print(table)


@cli.command("validation-request")
@click.option("--id", "request_id", required=True, help="Validation request ID")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def validation_request_cmd(
    request_id: str,
    as_json: bool,
):
    """Show details for a specific validation request."""
    from axiom_core.validation_requests import ValidationRequestGenerator

    generator = ValidationRequestGenerator()
    req = generator.get_request(request_id)

    if req is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "request_id": request_id}, indent=2))
        else:
            console.print(f"[red]Validation request not found:[/red] {request_id}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(req.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]Validation Request: {req.request_id}[/bold]")
    console.print(f"  Plan ID:    {req.plan_id}")
    console.print(f"  Plan Name:  {req.plan_name}")
    console.print(f"  Status:     {req.status.value}")
    console.print(f"  Steps:      {len(req.steps)}")
    console.print(f"  Blockers:   {len(req.blockers)}")
    console.print(f"  Created:    {req.created_at}")

    if req.required_capabilities:
        console.print("\n  [bold]Required Capabilities:[/bold]")
        for cap in req.required_capabilities:
            console.print(f"    • {cap}")

    if req.steps:
        console.print("\n  [bold]Validation Steps:[/bold]")
        for step in req.steps:
            console.print(f"    {step.sequence}. {step.title} [{step.safety_level}]")

    if req.blockers:
        console.print("\n  [bold]Blockers:[/bold]")
        for b in req.blockers:
            console.print(f"    ⚠ [{b.blocker_type.value}] {b.description}")


@cli.command("validation-request-create")
@click.option("--plan-id", required=True, help="Plan ID to generate validation request from")
@click.option("--plan-name", default=None, help="Plan name (defaults to plan-id)")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def validation_request_create_cmd(
    plan_id: str,
    plan_name: Optional[str],
    as_json: bool,
):
    """Generate a validation request from an approved plan."""
    from axiom_core.plan_reviews import PlanReviewDecision, PlanReviewRegistry
    from axiom_core.validation_requests import (
        ValidationRequestGenerator,
        ValidationRequestStep,
    )

    review_registry = PlanReviewRegistry()
    history = review_registry.get_history(plan_id)

    if not history.reviews:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "unknown_plan", "plan_id": plan_id}, indent=2))
        else:
            console.print(f"[red]Unknown plan ID:[/red] {plan_id}")
        raise SystemExit(2)

    latest = history.latest_decision
    if latest == PlanReviewDecision.REJECTED:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "plan_rejected", "plan_id": plan_id}, indent=2))
        else:
            console.print(f"[red]Plan is rejected:[/red] {plan_id}")
        raise SystemExit(1)

    if latest != PlanReviewDecision.APPROVED:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "plan_not_approved", "plan_id": plan_id, "decision": latest.value if latest else None}, indent=2))
        else:
            console.print(f"[yellow]Plan not approved:[/yellow] {plan_id} (current: {latest.value if latest else 'none'})")
        raise SystemExit(1)

    effective_name = plan_name or plan_id
    generator = ValidationRequestGenerator()

    step = ValidationRequestStep(
        sequence=1,
        title=f"Validate plan: {effective_name}",
        description=f"Execute validation procedures for approved plan {plan_id}",
        validation_procedure="standard_validation",
        safety_level="safe",
    )

    request = generator.generate_from_plan(
        plan_id=plan_id,
        plan_name=effective_name,
        steps=[step],
        expected_outputs=["pass_fail.json", "evidence_bundle"],
    )

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(request.to_dict(), indent=2, default=str))
        return

    console.print(f"[green]Validation request created:[/green] {request.request_id}")
    console.print(f"  Plan:   {request.plan_id}")
    console.print(f"  Status: {request.status.value}")
    console.print(f"  Steps:  {len(request.steps)}")


# ---------------------------------------------------------------------------
# Controlled Validation Orchestrator commands (PR #53)
# ---------------------------------------------------------------------------


@cli.command("validation-orchestrate")
@click.option("--request-id", required=True, help="Validation request ID to orchestrate")
@click.option("--simulate", is_flag=True, default=False, help="Simulate without actual execution")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def validation_orchestrate_cmd(
    request_id: str,
    simulate: bool,
    as_json: bool,
):
    """Execute or simulate a validation orchestration."""
    from axiom_core.validation_orchestrator import (
        ControlledValidationOrchestrator,
        ValidationOrchestrationStep,
    )
    from axiom_core.validation_requests import (
        ValidationRequestGenerator,
        ValidationRequestStatus,
    )

    req_generator = ValidationRequestGenerator()
    req = req_generator.get_request(request_id)

    if req is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "request_id": request_id}, indent=2))
        else:
            console.print(f"[red]Validation request not found:[/red] {request_id}")
        raise SystemExit(2)

    if req.status in (
        ValidationRequestStatus.BLOCKED,
        ValidationRequestStatus.CANCELLED,
        ValidationRequestStatus.COMPLETED,
    ):
        if as_json:
            import json as json_mod

            payload: dict[str, object] = {
                "error": f"request_{req.status.value}",
                "request_id": request_id,
            }
            if req.status == ValidationRequestStatus.BLOCKED:
                payload["blockers"] = len(req.blockers)
            click.echo(json_mod.dumps(payload, indent=2))
        else:
            if req.status == ValidationRequestStatus.BLOCKED:
                console.print(f"[red]Request is blocked:[/red] {request_id} ({len(req.blockers)} blockers)")
            else:
                console.print(f"[red]Request is {req.status.value}:[/red] {request_id}")
        raise SystemExit(1)

    orchestrator = ControlledValidationOrchestrator()

    orch_steps = [
        ValidationOrchestrationStep(
            step_id=s.step_id,
            sequence=s.sequence,
            title=s.title,
            procedure=s.validation_procedure,
        )
        for s in req.steps
    ]

    result = orchestrator.orchestrate(
        request_id=request_id,
        steps=orch_steps,
        required_capabilities=req.required_capabilities,
        simulate=simulate,
    )

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(result.to_dict(), indent=2, default=str))
        if result.refusal_reason:
            raise SystemExit(1)
        return

    if result.refusal_reason:
        console.print(f"[red]Refused:[/red] {result.refusal_reason}")
        raise SystemExit(1)

    mode = "Simulated" if simulate else "Completed"
    console.print(f"[green]{mode}:[/green] {result.run_id}")
    console.print(f"  Request: {result.request_id}")
    console.print(f"  Steps:   {result.step_count} ({result.passed_count} passed, {result.failed_count} failed)")
    console.print(f"  Status:  {result.status.value}")


# ---------------------------------------------------------------------------
# Autonomous Work Item Registry commands (PR #56)
# ---------------------------------------------------------------------------


@cli.command("work-items")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.option("--status", "status_str", default=None, help="Filter by status")
@click.option("--type", "type_str", default=None, help="Filter by work item type")
def work_items_cmd(
    as_json: bool,
    status_str: Optional[str],
    type_str: Optional[str],
):
    """List work items."""
    from axiom_core.work_item_registry import (
        WorkItemRegistry,
    )
    from axiom_core.work_item_registry import (
        WorkItemStatus as WIStatus,
    )
    from axiom_core.work_item_registry import (
        WorkItemType as WIType,
    )

    registry = WorkItemRegistry()

    status_filter = None
    if status_str is not None:
        try:
            status_filter = WIStatus(status_str)
        except ValueError:
            valid = ", ".join(s.value for s in WIStatus)
            console.print(f"[red]Invalid status:[/red] {status_str}. Valid: {valid}")
            raise SystemExit(1)

    type_filter = None
    if type_str is not None:
        try:
            type_filter = WIType(type_str)
        except ValueError:
            valid = ", ".join(t.value for t in WIType)
            console.print(f"[red]Invalid type:[/red] {type_str}. Valid: {valid}")
            raise SystemExit(1)

    items = registry.list_items(status_filter=status_filter, type_filter=type_filter)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([i.to_dict() for i in items], indent=2, default=str))
        return

    if not items:
        console.print("[dim]No work items found.[/dim]")
        return

    table = Table(title="Work Items")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Assigned")
    for item in items:
        table.add_row(
            item.item_id[:12],
            item.title[:40],
            item.item_type.value,
            item.status.value,
            item.priority.value,
            item.assigned_to or "-",
        )
    console.print(table)


@cli.command("work-item")
@click.option("--id", "item_id", required=True, help="Work item ID")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def work_item_cmd(
    item_id: str,
    as_json: bool,
):
    """Show details for a specific work item."""
    from axiom_core.work_item_registry import WorkItemRegistry

    registry = WorkItemRegistry()
    item = registry.get_item(item_id)

    if item is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "item_id": item_id}, indent=2))
        else:
            console.print(f"[red]Work item not found:[/red] {item_id}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(item.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]Work Item: {item.item_id}[/bold]")
    console.print(f"  Title:       {item.title}")
    console.print(f"  Type:        {item.item_type.value}")
    console.print(f"  Status:      {item.status.value}")
    console.print(f"  Priority:    {item.priority.value}")
    console.print(f"  Created by:  {item.created_by or '-'}")
    console.print(f"  Assigned to: {item.assigned_to or '-'}")
    console.print(f"  Created:     {item.created_at}")
    console.print(f"  Updated:     {item.updated_at}")
    if item.description:
        console.print(f"  Description: {item.description}")
    if item.evidence:
        console.print(f"  Evidence:    {len(item.evidence)} item(s)")
    if item.dependencies:
        console.print(f"  Dependencies: {len(item.dependencies)}")
        for dep in item.dependencies:
            console.print(f"    -> {dep.depends_on_id} ({dep.dependency_type})")


@cli.command("work-item-create")
@click.option("--title", required=True, help="Work item title")
@click.option("--type", "type_str", required=True, help="Work item type")
@click.option("--description", default=None, help="Description")
@click.option("--priority", "priority_str", default="unset", help="Priority level")
@click.option("--created-by", default=None, help="Creator identifier")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def work_item_create_cmd(
    title: str,
    type_str: str,
    description: Optional[str],
    priority_str: str,
    created_by: Optional[str],
    as_json: bool,
):
    """Create a new work item."""
    from axiom_core.work_item_registry import (
        WorkItemPriority as WIPriority,
    )
    from axiom_core.work_item_registry import (
        WorkItemRegistry,
    )
    from axiom_core.work_item_registry import (
        WorkItemType as WIType,
    )

    try:
        item_type = WIType(type_str)
    except ValueError:
        valid = ", ".join(t.value for t in WIType)
        console.print(f"[red]Invalid type:[/red] {type_str}. Valid: {valid}")
        raise SystemExit(1)

    try:
        priority = WIPriority(priority_str)
    except ValueError:
        valid = ", ".join(p.value for p in WIPriority)
        console.print(f"[red]Invalid priority:[/red] {priority_str}. Valid: {valid}")
        raise SystemExit(1)

    registry = WorkItemRegistry()
    item = registry.create_item(
        title=title,
        item_type=item_type,
        description=description,
        priority=priority,
        created_by=created_by,
    )

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(item.to_dict(), indent=2, default=str))
        return

    console.print(f"[green]Work item created:[/green] {item.item_id}")
    console.print(f"  Title:    {item.title}")
    console.print(f"  Type:     {item.item_type.value}")
    console.print(f"  Status:   {item.status.value}")
    console.print(f"  Priority: {item.priority.value}")


@cli.command("work-item-update")
@click.option("--id", "item_id", required=True, help="Work item ID")
@click.option("--status", "status_str", default=None, help="New status")
@click.option("--title", default=None, help="New title")
@click.option("--description", default=None, help="New description")
@click.option("--priority", "priority_str", default=None, help="New priority")
@click.option("--assigned-to", default=None, help="Assign to")
@click.option("--by", "actor", default=None, help="Actor making the change")
@click.option("--reason", default=None, help="Reason for status change")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def work_item_update_cmd(
    item_id: str,
    status_str: Optional[str],
    title: Optional[str],
    description: Optional[str],
    priority_str: Optional[str],
    assigned_to: Optional[str],
    actor: Optional[str],
    reason: Optional[str],
    as_json: bool,
):
    """Update a work item (status, fields, or both)."""
    from axiom_core.work_item_registry import (
        WorkItemPriority as WIPriority,
    )
    from axiom_core.work_item_registry import (
        WorkItemRegistry,
    )
    from axiom_core.work_item_registry import (
        WorkItemStatus as WIStatus,
    )

    registry = WorkItemRegistry()
    item = registry.get_item(item_id)
    if item is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "item_id": item_id}, indent=2))
        else:
            console.print(f"[red]Work item not found:[/red] {item_id}")
        raise SystemExit(2)

    new_status = None
    if status_str is not None:
        try:
            new_status = WIStatus(status_str)
        except ValueError:
            valid = ", ".join(s.value for s in WIStatus)
            console.print(f"[red]Invalid status:[/red] {status_str}. Valid: {valid}")
            raise SystemExit(1)

    priority = None
    if priority_str is not None:
        try:
            priority = WIPriority(priority_str)
        except ValueError:
            valid = ", ".join(p.value for p in WIPriority)
            console.print(f"[red]Invalid priority:[/red] {priority_str}. Valid: {valid}")
            raise SystemExit(1)

    has_status_change = new_status is not None
    has_field_change = any(v is not None for v in (title, description, priority, assigned_to))

    if not has_status_change and not has_field_change:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps(item.to_dict(), indent=2, default=str))
        else:
            console.print(f"[dim]No changes specified for:[/dim] {item_id}")
        return

    try:
        if has_status_change:
            item = registry.update_status(
                item_id, new_status, actor=actor, reason=reason
            )
        if has_field_change:
            item = registry.update_fields(
                item_id,
                title=title,
                description=description,
                priority=priority,
                assigned_to=assigned_to,
                actor=actor,
            )
    except ValueError as exc:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "update_failed", "reason": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(item.to_dict(), indent=2, default=str))
        return

    console.print(f"[green]Work item updated:[/green] {item.item_id}")
    console.print(f"  Title:    {item.title}")
    console.print(f"  Status:   {item.status.value}")
    console.print(f"  Priority: {item.priority.value}")


# ---------------------------------------------------------------------------
# Codebase Inventory and Symbol Registry commands (PR #57)
# ---------------------------------------------------------------------------


@cli.command("code-inventory")
@click.option("--refresh", "do_refresh", is_flag=True, help="Rescan the repo")
@click.option(
    "--category",
    "category_str",
    default=None,
    help="Filter by category (source, test, cli, architecture_doc, runbook, log_doc, config, artifact, other)",
)
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def code_inventory_cmd(
    do_refresh: bool,
    category_str: Optional[str],
    as_json: bool,
):
    """Show codebase file inventory or rescan."""
    from pathlib import Path

    from axiom_core.codebase_inventory import (
        CodebaseInventory,
        CodeSymbolRegistry,
        FileCategory,
    )

    repo_root = Path.cwd()
    registry = CodeSymbolRegistry()

    if do_refresh:
        scanner = CodebaseInventory(repo_root)
        files, symbols, coverage_refs = scanner.scan()
        surface = registry.refresh(files, symbols, coverage_refs)
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps(surface.to_dict(), indent=2, default=str))
            return
        console.print(f"[green]Inventory refreshed:[/green] {surface.total_files} files, {surface.total_symbols} symbols")
        for cat, count in sorted(surface.files_by_category.items()):
            console.print(f"  {cat}: {count}")
        return

    category = None
    if category_str is not None:
        try:
            category = FileCategory(category_str)
        except ValueError:
            valid = ", ".join(c.value for c in FileCategory)
            console.print(f"[red]Invalid category:[/red] {category_str}. Valid: {valid}")
            raise SystemExit(1)

    files = registry.list_files(category=category)
    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([f.to_dict() for f in files], indent=2, default=str))
        return

    if not files:
        console.print("[dim]No files in inventory. Run with --refresh first.[/dim]")
        return

    table = Table(title="Codebase Files")
    table.add_column("Path", style="cyan")
    table.add_column("Category")
    table.add_column("Module")
    table.add_column("Lines", justify="right")
    for f in files:
        table.add_row(
            f.path[:60],
            f.category.value,
            (f.module_name or "-")[:40],
            str(f.line_count),
        )
    console.print(table)


@cli.command("code-symbols")
@click.option("--kind", "kind_str", default=None, help="Filter by kind (class, function, cli_command, enum, constant, module)")
@click.option("--file", "file_path", default=None, help="Filter by file path")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def code_symbols_cmd(
    kind_str: Optional[str],
    file_path: Optional[str],
    as_json: bool,
):
    """List code symbols in the inventory."""
    from axiom_core.codebase_inventory import (
        CodeSymbolRegistry,
        SymbolKind,
    )

    registry = CodeSymbolRegistry()

    kind = None
    if kind_str is not None:
        try:
            kind = SymbolKind(kind_str)
        except ValueError:
            valid = ", ".join(k.value for k in SymbolKind)
            console.print(f"[red]Invalid kind:[/red] {kind_str}. Valid: {valid}")
            raise SystemExit(1)

    symbols = registry.list_symbols(kind=kind, file_path=file_path)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([s.to_dict() for s in symbols], indent=2, default=str))
        return

    if not symbols:
        console.print("[dim]No symbols found. Run code-inventory --refresh first.[/dim]")
        return

    table = Table(title="Code Symbols")
    table.add_column("Name", style="cyan")
    table.add_column("Kind")
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Parent")
    for s in symbols:
        table.add_row(
            s.name[:40],
            s.kind.value,
            s.file_path[:40],
            str(s.line_number),
            (s.parent_symbol or "-")[:20],
        )
    console.print(table)


@cli.command("code-symbol")
@click.option("--name", required=True, help="Symbol name or qualified name")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def code_symbol_cmd(
    name: str,
    as_json: bool,
):
    """Show details for a specific code symbol."""
    from axiom_core.codebase_inventory import CodeSymbolRegistry

    registry = CodeSymbolRegistry()
    matches = registry.get_symbol(name)

    if not matches:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": "not_found", "name": name}, indent=2))
        else:
            console.print(f"[red]Symbol not found:[/red] {name}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([s.to_dict() for s in matches], indent=2, default=str))
        return

    for s in matches:
        console.print(f"\n[bold]{s.qualified_name}[/bold]")
        console.print(f"  Kind:    {s.kind.value}")
        console.print(f"  File:    {s.file_path}")
        console.print(f"  Line:    {s.line_number}")
        if s.parent_symbol:
            console.print(f"  Parent:  {s.parent_symbol}")
        if s.docstring:
            console.print(f"  Doc:     {s.docstring[:100]}")
        if s.metadata:
            console.print(f"  Meta:    {s.metadata}")


# ---------------------------------------------------------------------------
# Implementation Plan Generator commands (PR #58)
# ---------------------------------------------------------------------------


@cli.command("implementation-plan")
@click.option("--work-item", "work_item_id", required=True, help="Work item ID to plan")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def implementation_plan_cmd(
    work_item_id: str,
    as_json: bool,
):
    """Generate an implementation plan from an approved work item."""
    from axiom_core.codebase_inventory import CodeSymbolRegistry
    from axiom_core.implementation_planner import ImplementationPlanner
    from axiom_core.work_item_registry import WorkItemRegistry

    planner = ImplementationPlanner()
    work_items = WorkItemRegistry()
    code_reg = CodeSymbolRegistry()

    knowledge_graph = None
    try:
        from axiom_core.knowledge_graph import KnowledgeGraph

        knowledge_graph = KnowledgeGraph()
    except Exception:
        pass

    try:
        plan = planner.generate(
            work_item_id=work_item_id,
            work_item_registry=work_items,
            code_registry=code_reg,
            knowledge_graph=knowledge_graph,
        )
    except ValueError as exc:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(plan.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]{plan.title}[/bold]")
    console.print(f"  Plan ID:     {plan.plan_id}")
    console.print(f"  Work Item:   {plan.work_item_id}")
    console.print(f"  Status:      {plan.status.value}")
    console.print(f"  Summary:     {plan.summary}")

    if plan.steps:
        console.print("\n[bold]Steps:[/bold]")
        for step in plan.steps:
            console.print(f"  {step.step_number}. {step.description}")
            if step.target_files:
                for tf in step.target_files:
                    console.print(f"     → {tf}")

    if plan.file_changes:
        console.print("\n[bold]File Changes:[/bold]")
        table = Table()
        table.add_column("File", style="cyan")
        table.add_column("Change")
        table.add_column("Description")
        for fc in plan.file_changes:
            table.add_row(fc.file_path[:50], fc.change_type.value, fc.description[:50])
        console.print(table)

    if plan.test_plan.test_files:
        console.print("\n[bold]Test Files:[/bold]")
        for tf in plan.test_plan.test_files:
            console.print(f"  • {tf}")

    if plan.risks:
        console.print("\n[bold]Risks:[/bold]")
        for r in plan.risks:
            console.print(f"  [{r.level.value.upper()}] {r.description}")
            if r.mitigation:
                console.print(f"         Mitigation: {r.mitigation}")

    if plan.non_goals:
        console.print("\n[bold]Non-Goals:[/bold]")
        for ng in plan.non_goals:
            console.print(f"  • {ng}")

    if plan.evidence_requirements:
        console.print("\n[bold]Evidence Requirements:[/bold]")
        for er in plan.evidence_requirements:
            console.print(f"  • {er}")


# ---------------------------------------------------------------------------
# Patch Proposal commands (PR #59)
# ---------------------------------------------------------------------------


@cli.command("patch-proposal-create")
@click.option("--plan-id", required=True, help="Implementation plan ID")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_proposal_create_cmd(plan_id: str, as_json: bool):
    """Create a patch proposal from an implementation plan."""
    from axiom_core.implementation_planner import ImplementationPlanner
    from axiom_core.patch_proposal import PatchProposalRegistry

    registry = PatchProposalRegistry()
    planner = ImplementationPlanner()

    try:
        proposal = registry.create_from_plan(plan_id, planner)
    except ValueError as exc:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(proposal.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]Created: {proposal.title}[/bold]")
    console.print(f"  Proposal ID:  {proposal.proposal_id}")
    console.print(f"  Plan ID:      {proposal.plan_id}")
    console.print(f"  Status:       {proposal.status.value}")
    console.print(f"  Risk Level:   {proposal.overall_risk_level.value}")
    console.print(f"  Files:        {len(proposal.file_changes)}")
    console.print(f"  Tests:        {len(proposal.test_commands)}")
    console.print(f"  Validations:  {len(proposal.validation_commands)}")


@cli.command("patch-proposals")
@click.option("--status", "status_filter", default=None, help="Filter by status")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_proposals_cmd(status_filter: str | None, as_json: bool):
    """List patch proposals."""
    from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus

    registry = PatchProposalRegistry()

    status = None
    if status_filter:
        try:
            status = PatchStatus(status_filter)
        except ValueError:
            valid = ", ".join(s.value for s in PatchStatus)
            if as_json:
                import json as json_mod

                click.echo(json_mod.dumps({"error": f"Invalid status. Valid: {valid}"}, indent=2))
            else:
                console.print(f"[red]Error:[/red] Invalid status '{status_filter}'. Valid: {valid}")
            raise SystemExit(1)

    proposals = registry.list_proposals(status=status)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([p.to_dict() for p in proposals], indent=2, default=str))
        return

    if not proposals:
        console.print("No patch proposals found.")
        return

    table = Table(title="Patch Proposals")
    table.add_column("ID", style="cyan", max_width=36)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Risk")
    table.add_column("Files")
    for p in proposals:
        table.add_row(
            p.proposal_id[:36],
            p.title[:50],
            p.status.value,
            p.overall_risk_level.value,
            str(len(p.file_changes)),
        )
    console.print(table)


@cli.command("patch-proposal")
@click.option("--id", "proposal_id", required=True, help="Proposal ID")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_proposal_cmd(proposal_id: str, as_json: bool):
    """Show details for a specific patch proposal."""
    from axiom_core.patch_proposal import PatchProposalRegistry

    registry = PatchProposalRegistry()
    proposal = registry.get_proposal(proposal_id)

    if proposal is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": f"Patch proposal not found: {proposal_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Patch proposal not found: {proposal_id}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(proposal.to_dict(), indent=2, default=str))
        return

    console.print(f"\n[bold]{proposal.title}[/bold]")
    console.print(f"  Proposal ID:  {proposal.proposal_id}")
    console.print(f"  Plan ID:      {proposal.plan_id}")
    console.print(f"  Status:       {proposal.status.value}")
    console.print(f"  Risk Level:   {proposal.overall_risk_level.value}")
    console.print(f"  Summary:      {proposal.summary}")

    if proposal.file_changes:
        console.print("\n[bold]Proposed File Changes:[/bold]")
        table = Table()
        table.add_column("File", style="cyan")
        table.add_column("Edit")
        table.add_column("Description")
        for fc in proposal.file_changes:
            table.add_row(fc.file_path[:50], fc.edit_type.value, fc.description[:50])
        console.print(table)

    if proposal.test_commands:
        console.print("\n[bold]Test Commands:[/bold]")
        for tc in proposal.test_commands:
            console.print(f"  $ {tc.command}")
            if tc.description:
                console.print(f"    {tc.description}")

    if proposal.validation_commands:
        console.print("\n[bold]Validation Commands:[/bold]")
        for vc in proposal.validation_commands:
            console.print(f"  $ {vc.command}")
            if vc.description:
                console.print(f"    {vc.description}")

    if proposal.risks:
        console.print("\n[bold]Risks:[/bold]")
        for r in proposal.risks:
            console.print(f"  [{r.level.value.upper()}] {r.description}")
            if r.mitigation:
                console.print(f"         Mitigation: {r.mitigation}")

    if proposal.evidence_requirements:
        console.print("\n[bold]Evidence Requirements:[/bold]")
        for er in proposal.evidence_requirements:
            marker = "required" if er.required else "optional"
            console.print(f"  • [{marker}] {er.description}")

    if proposal.rollback_notes:
        console.print(f"\n[bold]Rollback Notes:[/bold]\n  {proposal.rollback_notes}")


# ---------------------------------------------------------------------------
# Patch Review commands (PR #60)
# ---------------------------------------------------------------------------


@cli.command("patch-review-create")
@click.option("--proposal-id", required=True, help="Patch proposal ID to review")
@click.option("--decision", required=True, help="Review decision (approved, rejected, needs_more_evidence, deprecated)")
@click.option("--reason", default="", help="Reason for the decision")
@click.option("--reviewer", default="", help="Name of the reviewer")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_review_create_cmd(
    proposal_id: str,
    decision: str,
    reason: str,
    reviewer: str,
    as_json: bool,
):
    """Create a review for a patch proposal."""
    from axiom_core.patch_review import PatchReviewRegistry, ReviewDecision

    registry = PatchReviewRegistry()

    try:
        dec = ReviewDecision(decision)
    except ValueError:
        dec = None

    disallowed = {ReviewDecision.PROPOSED, ReviewDecision.SUPERSEDED}
    if dec is None or dec in disallowed:
        valid = ", ".join(d.value for d in ReviewDecision if d not in disallowed)
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": f"Invalid decision. Valid: {valid}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Invalid decision '{decision}'. Valid: {valid}")
        raise SystemExit(1)

    try:
        review = registry.create_review(
            proposal_id=proposal_id,
            decision=dec,
            reason=reason,
            reviewer=reviewer,
        )
    except ValueError as exc:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(review.to_dict(), indent=2, default=str))
        return

    console.print("\n[bold]Review Created[/bold]")
    console.print(f"  Review ID:    {review.review_id}")
    console.print(f"  Proposal ID:  {review.proposal_id}")
    console.print(f"  Decision:     {review.decision.value}")
    console.print(f"  Reason:       {review.reason or '(none)'}")
    console.print(f"  Reviewer:     {review.reviewer or '(none)'}")


@cli.command("patch-reviews")
@click.option("--proposal-id", default=None, help="Filter by proposal ID")
@click.option("--decision", "decision_filter", default=None, help="Filter by decision")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_reviews_cmd(
    proposal_id: str | None,
    decision_filter: str | None,
    as_json: bool,
):
    """List patch reviews."""
    from axiom_core.patch_review import PatchReviewRegistry, ReviewDecision

    registry = PatchReviewRegistry()

    decision = None
    if decision_filter:
        try:
            decision = ReviewDecision(decision_filter)
        except ValueError:
            valid = ", ".join(d.value for d in ReviewDecision)
            if as_json:
                import json as json_mod

                click.echo(json_mod.dumps({"error": f"Invalid decision. Valid: {valid}"}, indent=2))
            else:
                console.print(f"[red]Error:[/red] Invalid decision '{decision_filter}'. Valid: {valid}")
            raise SystemExit(1)

    reviews = registry.list_reviews(proposal_id=proposal_id, decision=decision)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps([r.to_dict() for r in reviews], indent=2, default=str))
        return

    if not reviews:
        console.print("No patch reviews found.")
        return

    table = Table(title="Patch Reviews")
    table.add_column("Review ID", style="cyan", max_width=36)
    table.add_column("Proposal ID", max_width=36)
    table.add_column("Decision")
    table.add_column("Reviewer")
    table.add_column("Created")
    for r in reviews:
        table.add_row(
            r.review_id[:36],
            r.proposal_id[:36],
            r.decision.value,
            r.reviewer or "(none)",
            r.created_at[:19],
        )
    console.print(table)


@cli.command("patch-review")
@click.option("--proposal-id", required=True, help="Proposal ID to show review for")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_review_cmd(proposal_id: str, as_json: bool):
    """Show the latest review and full history for a patch proposal."""
    from axiom_core.patch_review import PatchReviewRegistry

    registry = PatchReviewRegistry()
    latest = registry.get_latest_review(proposal_id)

    if latest is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": f"No reviews found for proposal: {proposal_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] No reviews found for proposal: {proposal_id}")
        raise SystemExit(2)

    history = registry.get_history(proposal_id)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps({
            "latest_review": latest.to_dict(),
            "history": [h.to_dict() for h in history],
        }, indent=2, default=str))
        return

    console.print(f"\n[bold]Latest Review for Proposal {proposal_id[:36]}[/bold]")
    console.print(f"  Review ID:  {latest.review_id}")
    console.print(f"  Decision:   {latest.decision.value}")
    console.print(f"  Reason:     {latest.reason or '(none)'}")
    console.print(f"  Reviewer:   {latest.reviewer or '(none)'}")
    console.print(f"  Created:    {latest.created_at}")

    if latest.evidence:
        console.print("\n[bold]Evidence:[/bold]")
        for e in latest.evidence:
            console.print(f"  • [{e.evidence_type}] {e.description}")
            if e.artifact_path:
                console.print(f"    Path: {e.artifact_path}")

    if len(history) > 1:
        console.print(f"\n[bold]Review History ({len(history)} entries):[/bold]")
        table = Table()
        table.add_column("Decision")
        table.add_column("Reason")
        table.add_column("Reviewer")
        table.add_column("Created")
        for h in history:
            table.add_row(
                h.decision.value,
                (h.reason or "(none)")[:40],
                h.reviewer or "(none)",
                h.created_at[:19],
            )
        console.print(table)


# ---------------------------------------------------------------------------
# Patch Application commands (PR #61)
# ---------------------------------------------------------------------------


@cli.command("patch-apply")
@click.option("--proposal-id", required=True, help="Approved patch proposal ID to apply")
@click.option("--simulate", is_flag=True, help="Simulate without writing files")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def patch_apply_cmd(proposal_id: str, simulate: bool, as_json: bool):
    """Apply an approved patch proposal."""
    from axiom_core.patch_application import PatchApplicationRunner

    runner = PatchApplicationRunner()

    try:
        run = runner.apply(proposal_id=proposal_id, simulate=simulate)
    except ValueError as exc:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(run.to_dict(), indent=2, default=str))
        return

    mode = "SIMULATE" if simulate else "APPLY"
    console.print(f"\n[bold]Patch Application ({mode})[/bold]")
    console.print(f"  Run ID:      {run.run_id}")
    console.print(f"  Proposal:    {run.proposal_id}")
    console.print(f"  Plan:        {run.plan_id}")
    console.print(f"  Status:      {run.status.value}")

    if run.steps:
        console.print("\n[bold]Steps:[/bold]")
        for step in run.steps:
            marker = {
                "applied": "[green]APPLIED[/green]",
                "simulated": "[yellow]SIMULATED[/yellow]",
                "failed": "[red]FAILED[/red]",
                "skipped": "[dim]SKIPPED[/dim]",
            }.get(step.status.value, step.status.value)
            console.print(f"  {marker}  {step.edit_type} {step.file_path}")
            if step.error:
                console.print(f"         Error: {step.error}")

    if run.result:
        console.print("\n[bold]Result:[/bold]")
        console.print(f"  Success:   {run.result.success}")
        console.print(f"  Applied:   {run.result.steps_applied}")
        console.print(f"  Simulated: {run.result.steps_simulated}")
        console.print(f"  Failed:    {run.result.steps_failed}")
        if run.result.error:
            console.print(f"  Error:     {run.result.error}")

    if run.evidence:
        console.print("\n[bold]Evidence:[/bold]")
        for ev in run.evidence:
            console.print(f"  [{ev.artifact_type}] {ev.artifact_path}")


# ---------------------------------------------------------------------------
# Code Validation commands (PR #62)
# ---------------------------------------------------------------------------


@cli.command("code-validate")
@click.option("--patch-run-id", required=True, help="Patch application run ID to validate")
@click.option("--simulate", is_flag=True, help="Simulate without executing commands")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def code_validate_cmd(patch_run_id: str, simulate: bool, as_json: bool):
    """Validate a patch application run."""
    from axiom_core.code_validation import CodeValidationOrchestrator

    orchestrator = CodeValidationOrchestrator()

    try:
        run = orchestrator.validate(patch_run_id=patch_run_id, simulate=simulate)
    except ValueError as exc:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(run.to_dict(), indent=2, default=str))
        return

    mode = "SIMULATE" if simulate else "VALIDATE"
    console.print(f"\n[bold]Code Validation ({mode})[/bold]")
    console.print(f"  Run ID:      {run.run_id}")
    console.print(f"  Patch Run:   {run.patch_run_id}")
    console.print(f"  Proposal:    {run.proposal_id}")
    console.print(f"  Status:      {run.status.value}")

    if run.stages:
        console.print("\n[bold]Stages:[/bold]")
        for stage in run.stages:
            marker = {
                "passed": "[green]PASSED[/green]",
                "failed": "[red]FAILED[/red]",
                "skipped": "[dim]SKIPPED[/dim]",
                "simulated": "[yellow]SIMULATED[/yellow]",
                "refused": "[red]REFUSED[/red]",
                "blocked": "[yellow]BLOCKED[/yellow]",
            }.get(stage.status.value, stage.status.value)
            console.print(f"  {marker}  {stage.kind.value}: {stage.description}")
            if stage.error:
                console.print(f"         Error: {stage.error}")

    if run.summary:
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Overall:   {'PASSED' if run.summary.overall_passed else 'FAILED'}")
        console.print(f"  Passed:    {run.summary.stages_passed}")
        console.print(f"  Failed:    {run.summary.stages_failed}")
        console.print(f"  Skipped:   {run.summary.stages_skipped}")
        if run.summary.error:
            console.print(f"  Error:     {run.summary.error}")

    if run.evidence:
        console.print("\n[bold]Evidence:[/bold]")
        for ev in run.evidence:
            console.print(f"  [{ev.artifact_type}] {ev.artifact_path}")


@cli.command("code-validation-runs")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def code_validation_runs_cmd(as_json: bool):
    """List all code validation runs."""
    from axiom_core.code_validation import CodeValidationOrchestrator

    orchestrator = CodeValidationOrchestrator()
    runs = orchestrator.list_runs()

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(runs, indent=2, default=str))
        return

    if not runs:
        console.print("[dim]No validation runs found.[/dim]")
        return

    console.print(f"\n[bold]Code Validation Runs ({len(runs)})[/bold]\n")
    for r in runs:
        status = r.get("status", "unknown")
        marker = {
            "passed": "[green]PASSED[/green]",
            "failed": "[red]FAILED[/red]",
            "simulated": "[yellow]SIMULATED[/yellow]",
            "refused": "[red]REFUSED[/red]",
        }.get(status, status)
        console.print(
            f"  {marker}  {r.get('run_id', '?')[:12]}  "
            f"patch={r.get('patch_run_id', '?')[:12]}  "
            f"{r.get('started_at', '?')}"
        )


@cli.command("code-validation-run")
@click.option("--run-id", required=True, help="Validation run ID")
@click.option("--json-output", "as_json", is_flag=True, help="Machine-readable JSON output")
def code_validation_run_cmd(run_id: str, as_json: bool):
    """Show details of a specific code validation run."""
    from axiom_core.code_validation import CodeValidationOrchestrator

    orchestrator = CodeValidationOrchestrator()
    data = orchestrator.get_run(run_id)

    if data is None:
        if as_json:
            import json as json_mod

            click.echo(json_mod.dumps({"error": f"Validation run not found: {run_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Validation run not found: {run_id}")
        raise SystemExit(2)

    if as_json:
        import json as json_mod

        click.echo(json_mod.dumps(data, indent=2, default=str))
        return

    console.print("\n[bold]Code Validation Run[/bold]")
    console.print(f"  Run ID:      {data.get('run_id', '?')}")
    console.print(f"  Patch Run:   {data.get('patch_run_id', '?')}")
    console.print(f"  Proposal:    {data.get('proposal_id', '?')}")
    console.print(f"  Status:      {data.get('status', '?')}")
    console.print(f"  Simulate:    {data.get('simulate', '?')}")
    console.print(f"  Started:     {data.get('started_at', '?')}")
    console.print(f"  Completed:   {data.get('completed_at', '?')}")

    stages = data.get("stages", [])
    if stages:
        console.print(f"\n[bold]Stages ({len(stages)}):[/bold]")
        for s in stages:
            status = s.get("status", "?")
            marker = {
                "passed": "[green]PASSED[/green]",
                "failed": "[red]FAILED[/red]",
                "skipped": "[dim]SKIPPED[/dim]",
                "simulated": "[yellow]SIMULATED[/yellow]",
                "refused": "[red]REFUSED[/red]",
                "blocked": "[yellow]BLOCKED[/yellow]",
            }.get(status, status)
            console.print(f"  {marker}  {s.get('kind', '?')}: {s.get('description', '?')}")
            if s.get("error"):
                console.print(f"         Error: {s['error']}")

    summary = data.get("summary", {})
    if summary:
        console.print("\n[bold]Summary:[/bold]")
        overall = "PASSED" if summary.get("overall_passed") else "FAILED"
        console.print(f"  Overall:   {overall}")
        console.print(f"  Passed:    {summary.get('stages_passed', 0)}")
        console.print(f"  Failed:    {summary.get('stages_failed', 0)}")
        console.print(f"  Skipped:   {summary.get('stages_skipped', 0)}")


# ---------------------------------------------------------------------------
# PR Draft Generator commands (PR #63)
# ---------------------------------------------------------------------------


@cli.command("pr-draft")
@click.option("--work-item", default="", help="Work item ID to generate draft from.")
@click.option("--validation-run-id", default="", help="Validation run ID to generate draft from.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def pr_draft_cmd(work_item: str, validation_run_id: str, json_output: bool):
    """Generate a PR draft from a work item or validation run."""
    from axiom_core.pr_draft_generator import PRDraftGenerator

    if not work_item and not validation_run_id:
        msg = {"error": "At least one of --work-item or --validation-run-id required"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print("[red]Error:[/red] At least one of --work-item or --validation-run-id required")
        raise SystemExit(1)

    try:
        generator = PRDraftGenerator()
        draft = generator.generate(
            work_item_id=work_item,
            validation_run_id=validation_run_id,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    data = draft.to_dict()
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        _render_pr_draft_rich(data)


@cli.command("pr-drafts")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def pr_drafts_cmd(json_output: bool):
    """List all PR drafts from artifact directories."""
    from axiom_core.pr_draft_generator import PRDraftGenerator

    generator = PRDraftGenerator()
    drafts = generator.list_drafts()

    if json_output:
        click.echo(json.dumps(drafts, indent=2, default=str))
    else:
        if not drafts:
            console.print("[dim]No PR drafts found.[/dim]")
            return
        console.print(f"\n[bold]PR Drafts[/bold] ({len(drafts)} total)\n")
        for d in drafts:
            status = d.get("status", "?")
            draft_id = d.get("draft_id", "?")
            wi = d.get("work_item_id", "")
            title = ""
            summary = d.get("summary")
            if summary:
                title = summary.get("commit_title", "")
            marker = {
                "generated": "[green]GENERATED[/green]",
                "failed": "[red]FAILED[/red]",
                "refused": "[red]REFUSED[/red]",
                "pending": "[yellow]PENDING[/yellow]",
            }.get(status, status)
            line = f"  {marker}  {draft_id[:12]}..."
            if wi:
                line += f"  (work-item: {wi[:12]}...)"
            if title:
                line += f"  {title}"
            console.print(line)


@cli.command("pr-draft-show")
@click.option("--draft-id", required=True, help="PR draft ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def pr_draft_show_cmd(draft_id: str, json_output: bool):
    """Show details of a specific PR draft."""
    from axiom_core.pr_draft_generator import PRDraftGenerator

    generator = PRDraftGenerator()
    data = generator.get_draft(draft_id)

    if data is None:
        msg = {"error": f"PR draft not found: {draft_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] PR draft not found: {draft_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        _render_pr_draft_rich(data)


def _render_pr_draft_rich(data: dict):
    """Render a PR draft in rich text format."""
    status = data.get("status", "?")
    console.print(f"\n[bold]PR Draft[/bold] ({status.upper()})")
    console.print(f"  Draft ID:       {data.get('draft_id', '?')}")
    console.print(f"  Work Item:      {data.get('work_item_id') or '(none)'}")
    console.print(f"  Validation Run: {data.get('validation_run_id') or '(none)'}")
    console.print(f"  Proposal:       {data.get('proposal_id') or '(none)'}")
    console.print(f"  Patch Run:      {data.get('patch_run_id') or '(none)'}")
    console.print(f"  Status:         {status}")

    summary = data.get("summary")
    if summary:
        console.print("\n[bold]Commit:[/bold]")
        console.print(f"  Title: {summary.get('commit_title', '?')}")
        console.print(f"  Files changed: {summary.get('files_changed', 0)}")
        console.print(f"  Tests affected: {summary.get('tests_affected', 0)}")
        desc = summary.get("extended_description", "")
        if desc:
            console.print("\n[bold]Description:[/bold]")
            for line in desc.split("\n"):
                console.print(f"  {line}")

    vs = data.get("validation_section")
    if vs:
        console.print("\n[bold]Validation:[/bold]")
        passed = "PASSED" if vs.get("overall_passed") else "FAILED"
        console.print(f"  Run: {vs.get('validation_run_id', '?')}")
        console.print(f"  Overall: {passed}")
        console.print(f"  Passed: {vs.get('stages_passed', 0)}")
        console.print(f"  Failed: {vs.get('stages_failed', 0)}")
        console.print(f"  Skipped: {vs.get('stages_skipped', 0)}")

    ss = data.get("strategic_section")
    if ss:
        console.print("\n[bold]Strategic Significance:[/bold]")
        console.print(f"  {ss.get('significance', '?')}")
        console.print(f"  Next step: {ss.get('next_recommended_step', '?')}")
        wdnc = ss.get("what_did_not_change", [])
        if wdnc:
            console.print("\n  [bold]What did not change:[/bold]")
            for item in wdnc:
                console.print(f"    - {item}")
        ng = ss.get("non_goals", [])
        if ng:
            console.print("\n  [bold]Non-goals:[/bold]")
            for item in ng:
                console.print(f"    - {item}")

    limitations = data.get("known_limitations", [])
    if limitations:
        console.print("\n[bold]Known Limitations:[/bold]")
        for lim in limitations:
            console.print(f"  - {lim}")

    if data.get("error"):
        console.print(f"\n[red]Error:[/red] {data['error']}")


# ---------------------------------------------------------------------------
# Review Finding Ingestion commands (PR #64)
# ---------------------------------------------------------------------------


@cli.command("review-findings")
@click.option("--category", default="", help="Filter by category.")
@click.option("--severity", default="", help="Filter by severity.")
@click.option("--status", default="", help="Filter by status.")
@click.option("--pattern", default="", help="Filter by pattern kind.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def review_findings_cmd(
    category: str, severity: str, status: str, pattern: str, json_output: bool,
):
    """List review findings with optional filters."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    registry = ReviewFindingRegistry()
    findings = registry.list_findings(
        category=category, severity=severity, status=status, pattern=pattern,
    )

    if json_output:
        click.echo(json.dumps(
            [f.to_dict() for f in findings], indent=2, default=str,
        ))
    else:
        if not findings:
            console.print("[dim]No review findings found.[/dim]")
            return
        console.print(f"\n[bold]Review Findings[/bold] ({len(findings)} total)\n")
        for f in findings:
            sev_color = {
                "critical": "red", "high": "red", "medium": "yellow",
                "low": "dim", "informational": "dim",
            }.get(f.severity, "white")
            status_marker = {
                "open": "[yellow]OPEN[/yellow]",
                "acknowledged": "[blue]ACK[/blue]",
                "resolved": "[green]RESOLVED[/green]",
                "wont_fix": "[dim]WONT_FIX[/dim]",
                "duplicate": "[dim]DUPLICATE[/dim]",
            }.get(f.status, f.status)
            console.print(
                f"  {status_marker}  [{sev_color}]{f.severity}[/{sev_color}]"
                f"  [{f.category}]  {f.title}  ({f.finding_id[:12]}...)",
            )


@cli.command("review-finding")
@click.option("--id", "finding_id", required=True, help="Finding ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def review_finding_cmd(finding_id: str, json_output: bool):
    """Show details of a specific review finding."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    try:
        registry = ReviewFindingRegistry()
        finding = registry.get_finding(finding_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if finding is None:
        msg = {"error": f"Finding not found: {finding_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Finding not found: {finding_id}")
        raise SystemExit(2)

    data = finding.to_dict()
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        _render_review_finding_rich(data)

    # Show history
    history = registry.get_history(finding_id)
    if history and not json_output:
        console.print("\n[bold]History:[/bold]")
        for h in history:
            console.print(
                f"  {h.timestamp}  {h.action}"
                f"  {h.old_value or ''} -> {h.new_value or ''}"
                f"  ({h.actor or 'system'})",
            )


@cli.command("review-finding-ingest")
@click.option("--draft-id", default="", help="PR draft ID to ingest from.")
@click.option("--source-dir", default="", help="Directory with finding JSON files.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def review_finding_ingest_cmd(
    draft_id: str, source_dir: str, json_output: bool,
):
    """Ingest review findings from evidence bundles."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    if not draft_id and not source_dir:
        msg = {"error": "At least one of --draft-id or --source-dir required"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                "[red]Error:[/red] At least one of --draft-id or --source-dir required",
            )
        raise SystemExit(1)

    try:
        registry = ReviewFindingRegistry()
        findings = registry.ingest_from_evidence(
            source_dir=source_dir, draft_id=draft_id,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(
            [f.to_dict() for f in findings], indent=2, default=str,
        ))
    else:
        if not findings:
            console.print("[dim]No findings ingested.[/dim]")
        else:
            console.print(
                f"\n[bold]Ingested {len(findings)} finding(s)[/bold]\n",
            )
            for f in findings:
                console.print(
                    f"  [{f.severity}] [{f.category}] {f.title}"
                    f"  ({f.finding_id[:12]}...)",
                )


@cli.command("review-finding-create")
@click.option("--title", required=True, help="Finding title.")
@click.option("--description", default="", help="Finding description.")
@click.option(
    "--category", default="informational",
    type=click.Choice(
        ["bug", "flag", "security", "architecture", "performance",
         "style", "informational"],
        case_sensitive=False,
    ),
    help="Finding category.",
)
@click.option(
    "--severity", default="informational",
    type=click.Choice(
        ["critical", "high", "medium", "low", "informational"],
        case_sensitive=False,
    ),
    help="Finding severity.",
)
@click.option("--source-pr", default="", help="Source PR reference.")
@click.option("--source-file", default="", help="Source file path.")
@click.option("--draft-id", default="", help="Related PR draft ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def review_finding_create_cmd(
    title: str,
    description: str,
    category: str,
    severity: str,
    source_pr: str,
    source_file: str,
    draft_id: str,
    json_output: bool,
):
    """Create a new review finding manually."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    try:
        registry = ReviewFindingRegistry()
        finding = registry.create_finding(
            title=title,
            description=description,
            category=category,
            severity=severity,
            source_pr=source_pr,
            source_file=source_file,
            draft_id=draft_id,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    data = finding.to_dict()
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        console.print("\n[bold]Created review finding[/bold]")
        _render_review_finding_rich(data)


@cli.command("review-finding-update")
@click.option("--id", "finding_id", required=True, help="Finding ID.")
@click.option(
    "--status", default="",
    type=click.Choice(
        ["", "open", "acknowledged", "resolved", "wont_fix"],
        case_sensitive=False,
    ),
    help="New status.",
)
@click.option("--resolution", default="", help="Resolution description.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def review_finding_update_cmd(
    finding_id: str, status: str, resolution: str, json_output: bool,
):
    """Update a review finding's status or resolution."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    try:
        registry = ReviewFindingRegistry()
        finding = registry.update_finding(
            finding_id=finding_id, status=status, resolution=resolution,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    data = finding.to_dict()
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        console.print("\n[bold]Updated review finding[/bold]")
        _render_review_finding_rich(data)


@cli.command("review-patterns")
@click.option("--kind", default="", help="Filter by pattern kind.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def review_patterns_cmd(kind: str, json_output: bool):
    """List detected review finding patterns."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    registry = ReviewFindingRegistry()
    patterns = registry.list_patterns(kind=kind)

    if json_output:
        click.echo(json.dumps(
            [p.to_dict() for p in patterns], indent=2, default=str,
        ))
    else:
        if not patterns:
            console.print("[dim]No review patterns found.[/dim]")
            return
        console.print(f"\n[bold]Review Patterns[/bold] ({len(patterns)} total)\n")
        for p in patterns:
            console.print(
                f"  [{p.kind}]  {p.description}  "
                f"(finding: {p.finding_id[:12]}...)",
            )


def _render_review_finding_rich(data: dict):
    """Render a review finding in rich text format."""
    sev = data.get("severity", "?")
    cat = data.get("category", "?")
    status = data.get("status", "?")
    console.print(f"\n[bold]Review Finding[/bold] ({status.upper()})")
    console.print(f"  ID:          {data.get('finding_id', '?')}")
    console.print(f"  Title:       {data.get('title', '?')}")
    console.print(f"  Category:    {cat}")
    console.print(f"  Severity:    {sev}")
    console.print(f"  Status:      {status}")
    console.print(f"  Pattern:     {data.get('pattern', '?')}")

    if data.get("source_pr"):
        console.print(f"  Source PR:   {data['source_pr']}")
    if data.get("source_file"):
        console.print(f"  Source file: {data['source_file']}")
    if data.get("draft_id"):
        console.print(f"  Draft ID:    {data['draft_id']}")

    desc = data.get("description", "")
    if desc:
        console.print("\n[bold]Description:[/bold]")
        for line in desc.split("\n"):
            console.print(f"  {line}")

    if data.get("resolution"):
        console.print(f"\n[bold]Resolution:[/bold] {data['resolution']}")

    evidence = data.get("evidence", [])
    if evidence:
        console.print(f"\n[bold]Evidence:[/bold] ({len(evidence)} item(s))")
        for e in evidence:
            console.print(f"  - {e}")


# ---------------------------------------------------------------------------
# Self-Improvement Loop v1 (PR #65)
# ---------------------------------------------------------------------------


@cli.command("self-improvement")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def self_improvement_cmd(json_output: bool):
    """Run the self-improvement analysis loop.

    Studies engineering history from review findings and generates
    improvement candidates. No automatic code changes.
    """
    from axiom_core.self_improvement_loop import SelfImprovementLoop

    try:
        loop = SelfImprovementLoop()
        result = loop.run_analysis()
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_improvement_result_rich(result)


@cli.command("improvement-candidates")
@click.option(
    "--category",
    type=click.Choice([
        "repeated_bug_class", "missing_test", "duplicated_pattern",
        "candidate_helper", "knowledge_update", "skill_update",
        "playbook_update",
    ]),
    default=None,
    help="Filter by category.",
)
@click.option(
    "--priority",
    type=click.Choice(["critical", "high", "medium", "low", "unset"]),
    default=None,
    help="Filter by priority.",
)
@click.option(
    "--status",
    type=click.Choice([
        "proposed", "accepted", "rejected", "implemented", "deferred",
    ]),
    default=None,
    help="Filter by status.",
)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def improvement_candidates_cmd(
    category: str | None,
    priority: str | None,
    status: str | None,
    json_output: bool,
):
    """List improvement candidates generated from analysis."""
    from axiom_core.self_improvement_loop import SelfImprovementLoop

    try:
        loop = SelfImprovementLoop()
        candidates = loop.list_candidates(
            category=category or "",
            priority=priority or "",
            status=status or "",
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    data = [c.to_dict() for c in candidates]
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        console.print(f"\n[bold]Improvement Candidates[/bold] ({len(data)} total)\n")
        for item in data:
            _render_improvement_candidate_rich(item)


@cli.command("improvement-candidate")
@click.option("--id", "candidate_id", required=True, help="Candidate ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def improvement_candidate_cmd(candidate_id: str, json_output: bool):
    """Show details of a specific improvement candidate."""
    from axiom_core.self_improvement_loop import SelfImprovementLoop

    try:
        loop = SelfImprovementLoop()
        candidate = loop.get_candidate(candidate_id)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if candidate is None:
        msg = {"error": f"Candidate not found: {candidate_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Candidate not found: {candidate_id}")
        raise SystemExit(2)

    data = candidate.to_dict()
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        _render_improvement_candidate_rich(data)


@cli.command("improvement-patterns")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def improvement_patterns_cmd(json_output: bool):
    """List detected improvement patterns from analysis."""
    from axiom_core.self_improvement_loop import SelfImprovementLoop

    try:
        loop = SelfImprovementLoop()
        patterns = loop.list_patterns()
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    data = [p.to_dict() for p in patterns]
    if json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        console.print(f"\n[bold]Improvement Patterns[/bold] ({len(data)} total)\n")
        for item in data:
            console.print(
                f"  [{item['pattern_kind']}] "
                f"{item['occurrence_count']} occurrence(s) - "
                f"{item.get('description', '')}",
            )


def _render_improvement_result_rich(result: dict) -> None:
    """Render self-improvement analysis result in rich text."""
    console.print("\n[bold]Self-Improvement Analysis[/bold]\n")
    console.print(f"  Run ID:            {result.get('run_id', '')}")
    console.print(
        f"  Findings analyzed: {result.get('total_findings_analyzed', 0)}",
    )
    console.print(
        f"  Patterns detected: {result.get('patterns_detected', 0)}",
    )
    console.print(
        f"  Candidates:        {result.get('candidates_generated', 0)}",
    )

    patterns = result.get("patterns", [])
    if patterns:
        console.print("\n[bold]Patterns:[/bold]")
        for p in patterns:
            console.print(
                f"  - {p['pattern_kind']}: {p['occurrence_count']} occurrence(s)",
            )

    candidates = result.get("candidates", [])
    if candidates:
        console.print("\n[bold]Candidates:[/bold]")
        for c in candidates:
            console.print(
                f"  [{c['priority']}] [{c['category']}] {c['title']}",
            )

    summary = result.get("summary", {})
    top_rec = summary.get("top_recommendation", "")
    if top_rec:
        console.print(f"\n[bold]Top Recommendation:[/bold]\n  {top_rec}")


def _render_improvement_candidate_rich(data: dict) -> None:
    """Render a single improvement candidate in rich text."""
    console.print(
        f"\n[bold]Improvement Candidate ({data.get('status', '').upper()})[/bold]",
    )
    console.print(f"  ID:             {data.get('candidate_id', '')}")
    console.print(f"  Title:          {data.get('title', '')}")
    console.print(f"  Category:       {data.get('category', '')}")
    console.print(f"  Priority:       {data.get('priority', '')}")
    console.print(f"  Status:         {data.get('status', '')}")

    if data.get("description"):
        console.print(f"\n[bold]Description:[/bold]\n  {data['description']}")

    if data.get("recommendation"):
        console.print(
            f"\n[bold]Recommendation:[/bold]\n  {data['recommendation']}",
        )

    source = data.get("source_findings", [])
    if source:
        console.print(
            f"\n[bold]Source Findings:[/bold] ({len(source)} finding(s))",
        )
        for s in source:
            console.print(f"  - {s}")

    targets = data.get("target_files", [])
    if targets:
        console.print(
            f"\n[bold]Target Files:[/bold] ({len(targets)} file(s))",
        )
        for t in targets:
            console.print(f"  - {t}")


# ---------------------------------------------------------------------------
# Test Selection Engine v1 (PR #66)
# ---------------------------------------------------------------------------


@cli.command("test-selection")
@click.option(
    "--changed-files",
    multiple=True,
    help="Changed file path(s) to select tests for.",
)
@click.option("--work-item", default=None, help="Work item ID.")
@click.option("--plan-id", default=None, help="Implementation plan ID.")
@click.option("--proposal-id", default=None, help="Patch proposal ID.")
@click.option("--full-suite", is_flag=True, help="Force full test suite.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def test_selection_cmd(
    changed_files: tuple[str, ...],
    work_item: str | None,
    plan_id: str | None,
    proposal_id: str | None,
    full_suite: bool,
    json_output: bool,
):
    """Select targeted tests based on changed files or context."""
    from axiom_core.test_selection_engine import (
        TestSelectionEngine,
        TestSelectionRequest,
    )

    if not changed_files and not work_item and not plan_id and not proposal_id and not full_suite:
        msg = {"error": "At least one of --changed-files, --work-item, --plan-id, --proposal-id, or --full-suite is required."}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {msg['error']}")
        raise SystemExit(1)

    try:
        engine = TestSelectionEngine()
        request = TestSelectionRequest(
            changed_files=list(changed_files),
            work_item_id=work_item or "",
            plan_id=plan_id or "",
            proposal_id=proposal_id or "",
            force_full_suite=full_suite,
        )
        plan = engine.select_tests(request)
        engine.write_evidence(plan, request)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(plan.to_dict(), indent=2, default=str))
    else:
        _render_test_selection_rich(plan)


@cli.command("test-selection-files")
@click.argument("files", nargs=-1, required=True)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def test_selection_files_cmd(files: tuple[str, ...], json_output: bool):
    """Select tests from a list of changed files (positional args)."""
    from axiom_core.test_selection_engine import (
        TestSelectionEngine,
        TestSelectionRequest,
    )

    try:
        engine = TestSelectionEngine()
        file_list = list(files)
        request = TestSelectionRequest(changed_files=file_list)
        plan = engine.select_tests(request)
        engine.write_evidence(plan, request)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(plan.to_dict(), indent=2, default=str))
    else:
        _render_test_selection_rich(plan)


def _render_test_selection_rich(plan) -> None:
    """Render test selection plan in rich text."""
    data = plan.to_dict()
    strategy = data["strategy"].upper()
    console.print(f"\n[bold]Test Selection ({strategy})[/bold]\n")
    console.print(f"  Plan ID:    {data['plan_id']}")
    console.print(f"  Strategy:   {data['strategy']}")
    console.print(f"  Tests:      {data['test_count']}")
    console.print(f"  Ruff:       {data['include_ruff']}")

    if data.get("full_suite_reason"):
        console.print(f"\n  [yellow]Reason:[/yellow] {data['full_suite_reason']}")

    tests = data.get("selected_tests", [])
    if tests:
        console.print("\n[bold]Selected Tests:[/bold]")
        for t in tests:
            src = f" ← {t['source_file']}" if t.get("source_file") else ""
            console.print(f"  - {t['test_path']} ({t['reason']}){src}")

    ruff = data.get("ruff_targets", [])
    if ruff:
        console.print("\n[bold]Ruff Targets:[/bold]")
        for r in ruff:
            console.print(f"  - {r}")


# ---------------------------------------------------------------------------
# Regression Test Generator v1 (PR #67)
# ---------------------------------------------------------------------------


@cli.command("regression-test-generate")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def regression_test_generate_cmd(json_output: bool):
    """Generate regression test candidates from review findings.

    Analyzes review findings and generates structured test
    recommendations. Advisory-only — does not modify test files.
    """
    from axiom_core.regression_test_generator import RegressionTestGenerator

    try:
        generator = RegressionTestGenerator()
        result = generator.generate_from_findings()
        generator.write_evidence(result)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_regression_result_rich(result)


@cli.command("regression-test-create")
@click.option("--title", required=True, help="Bug/failure title.")
@click.option(
    "--description", default="", help="Detailed description.",
)
@click.option(
    "--failure-origin",
    type=click.Choice([
        "review_finding", "runtime_failure", "policy_violation",
        "human_review", "external_review", "security",
    ]),
    required=True,
    help="Origin of the failure.",
)
@click.option(
    "--bug-class",
    type=click.Choice([
        "truthiness_bug", "enum_serialization", "persistence_defect",
        "evidence_failure", "cli_exit_code", "refusal_path",
        "malformed_input", "path_traversal", "command_injection",
        "silent_exception", "stage_ordering", "duplicated_logic", "other",
    ]),
    default=None,
    help="Bug classification (auto-detected if omitted).",
)
@click.option("--target-file", default="", help="Affected source file.")
@click.option("--finding-id", default="", help="Source review finding ID.")
@click.option("--work-item-id", default="", help="Source work item ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def regression_test_create_cmd(
    title: str,
    description: str,
    failure_origin: str,
    bug_class: str | None,
    target_file: str,
    finding_id: str,
    work_item_id: str,
    json_output: bool,
):
    """Create a single regression test candidate."""
    from axiom_core.regression_test_generator import RegressionTestGenerator

    try:
        generator = RegressionTestGenerator()
        candidate = generator.generate_from_input(
            title=title,
            description=description,
            failure_origin=failure_origin,
            bug_class=bug_class or "",
            target_file=target_file,
            source_finding_id=finding_id,
            source_work_item_id=work_item_id,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(candidate.to_dict(), indent=2, default=str))
    else:
        _render_regression_candidate_rich(candidate.to_dict())


@cli.command("regression-test-candidates")
@click.option(
    "--bug-class",
    type=click.Choice([
        "truthiness_bug", "enum_serialization", "persistence_defect",
        "evidence_failure", "cli_exit_code", "refusal_path",
        "malformed_input", "path_traversal", "command_injection",
        "silent_exception", "stage_ordering", "duplicated_logic", "other",
    ]),
    default=None,
    help="Filter by bug class.",
)
@click.option(
    "--status",
    type=click.Choice([
        "proposed", "accepted", "rejected", "implemented", "deferred",
    ]),
    default=None,
    help="Filter by status.",
)
@click.option(
    "--priority",
    type=click.Choice(["critical", "high", "medium", "low", "unset"]),
    default=None,
    help="Filter by priority.",
)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def regression_test_candidates_cmd(
    bug_class: str | None,
    status: str | None,
    priority: str | None,
    json_output: bool,
):
    """List regression test candidates."""
    from axiom_core.regression_test_generator import RegressionTestGenerator

    try:
        generator = RegressionTestGenerator()
        candidates = generator.list_candidates(
            bug_class=bug_class or "",
            status=status or "",
            priority=priority or "",
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(candidates, indent=2, default=str))
    else:
        console.print(f"\n[bold]Regression Test Candidates[/bold] ({len(candidates)})\n")
        for c in candidates:
            console.print(
                f"  [{c.get('priority', 'unset')}] "
                f"{c.get('title', 'untitled')} "
                f"({c.get('bug_class', 'other')}) "
                f"— {c.get('status', 'proposed')}"
            )


@cli.command("regression-test-candidate")
@click.option("--id", "candidate_id", required=True, help="Candidate ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def regression_test_candidate_cmd(candidate_id: str, json_output: bool):
    """Show a single regression test candidate."""
    from axiom_core.regression_test_generator import RegressionTestGenerator

    try:
        generator = RegressionTestGenerator()
        candidate = generator.get_candidate(candidate_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if candidate is None:
        msg = {"error": "not_found", "candidate_id": candidate_id}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Candidate not found:[/red] {candidate_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(candidate, indent=2, default=str))
    else:
        _render_regression_candidate_rich(candidate)


@cli.command("regression-test-update")
@click.option("--id", "candidate_id", required=True, help="Candidate ID.")
@click.option(
    "--status",
    type=click.Choice([
        "proposed", "accepted", "rejected", "implemented", "deferred",
    ]),
    required=True,
    help="New status.",
)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def regression_test_update_cmd(
    candidate_id: str, status: str, json_output: bool,
):
    """Update a regression test candidate status."""
    from axiom_core.regression_test_generator import RegressionTestGenerator

    try:
        generator = RegressionTestGenerator()
        result = generator.update_candidate_status(candidate_id, status)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if result is None:
        msg = {"error": "not_found", "candidate_id": candidate_id}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Candidate not found:[/red] {candidate_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        console.print(f"[green]Updated[/green] {candidate_id} -> {status}")


@cli.command("regression-test-patterns")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def regression_test_patterns_cmd(json_output: bool):
    """List detected bug patterns from regression analysis."""
    from axiom_core.regression_test_generator import RegressionTestGenerator

    try:
        generator = RegressionTestGenerator()
        patterns = generator.list_patterns()
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(patterns, indent=2, default=str))
    else:
        console.print(f"\n[bold]Bug Patterns[/bold] ({len(patterns)})\n")
        for p in patterns:
            console.print(
                f"  - {p.get('bug_class', 'other')}: "
                f"{p.get('occurrence_count', 0)} occurrences"
            )


def _render_regression_result_rich(result: dict) -> None:
    """Render regression generation result in rich text."""
    console.print("\n[bold]Regression Test Generator[/bold]\n")
    console.print(f"  Run ID:             {result.get('run_id', '')}")
    console.print(f"  Findings analyzed:  {result.get('total_findings_analyzed', 0)}")
    console.print(f"  Candidates:         {result.get('total_candidates', 0)}")
    console.print(f"  Patterns:           {result.get('total_patterns', 0)}")

    candidates = result.get("candidates", [])
    if candidates:
        console.print("\n[bold]Candidates:[/bold]")
        for c in candidates:
            console.print(
                f"  [{c.get('priority', 'unset')}] "
                f"{c.get('title', 'untitled')} "
                f"({c.get('bug_class', 'other')})"
            )
            if c.get("assertion_hint"):
                console.print(f"    Hint: {c['assertion_hint']}")

    patterns = result.get("patterns", [])
    if patterns:
        console.print("\n[bold]Bug Patterns:[/bold]")
        for p in patterns:
            console.print(
                f"  - {p.get('bug_class', 'other')}: "
                f"{p.get('occurrence_count', 0)} occurrences"
            )


def _render_regression_candidate_rich(candidate: dict) -> None:
    """Render a single regression test candidate in rich text."""
    console.print("\n[bold]Regression Test Candidate[/bold]\n")
    console.print(f"  ID:             {candidate.get('candidate_id', '')}")
    console.print(f"  Title:          {candidate.get('title', '')}")
    console.print(f"  Bug Class:      {candidate.get('bug_class', '')}")
    console.print(f"  Origin:         {candidate.get('failure_origin', '')}")
    console.print(f"  Test Intent:    {candidate.get('test_intent', '')}")
    console.print(f"  Priority:       {candidate.get('priority', '')}")
    console.print(f"  Status:         {candidate.get('status', '')}")
    if candidate.get("target_file"):
        console.print(f"  Target File:    {candidate['target_file']}")
    if candidate.get("target_test_file"):
        console.print(f"  Target Test:    {candidate['target_test_file']}")
    if candidate.get("assertion_hint"):
        console.print(f"  Assertion Hint: {candidate['assertion_hint']}")
    if candidate.get("source_finding_id"):
        console.print(f"  Finding ID:     {candidate['source_finding_id']}")
    if candidate.get("source_work_item_id"):
        console.print(f"  Work Item ID:   {candidate['source_work_item_id']}")


# ---------------------------------------------------------------------------
# Coding Session Orchestrator v1 (PR #71)
# ---------------------------------------------------------------------------


@cli.command("orchestration-create")
@click.option("--session-id", required=True, help="Session ID to orchestrate.")
@click.option("--title", default="", help="Orchestration title.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestration_create_cmd(
    session_id: str, title: str, json_output: bool,
):
    """Create a new coding session orchestration."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        plan = orch.create_orchestration(session_id=session_id, title=title)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        orch.write_evidence(plan["plan_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        _render_orchestration_rich(plan)


@cli.command("orchestrations")
@click.option("--status", default="", help="Filter by status.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestrations_cmd(status: str, json_output: bool):
    """List all orchestration plans."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        plans = orch.list_orchestrations(status=status)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(plans, indent=2, default=str))
    else:
        console.print(f"\n[bold]Orchestrations ({len(plans)})[/bold]\n")
        for p in plans:
            progress = p.get("stage_progress", {})
            console.print(
                f"  [{p['status']}] {p['plan_id'][:12]}… "
                f"— stage: {p.get('current_stage', '')} "
                f"({progress.get('percentage', 0)}%)",
            )


@cli.command("orchestration")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestration_cmd(plan_id: str, json_output: bool):
    """Show a single orchestration plan."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        plan = orch.get_orchestration(plan_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if plan is None:
        msg = {"error": f"Orchestration not found: {plan_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Orchestration not found: {plan_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        _render_orchestration_rich(plan)


@cli.command("orchestration-advance")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--reason", default="", help="Transition reason.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestration_advance_cmd(
    plan_id: str, reason: str, json_output: bool,
):
    """Advance orchestration to the next stage."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        plan = orch.advance_stage(plan_id, reason=reason)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if plan is None:
        msg = {"error": f"Orchestration not found: {plan_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Orchestration not found: {plan_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        console.print(
            f"[green]Advanced to stage: {plan.get('current_stage', '')}[/green]",
        )


@cli.command("orchestration-block")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--reason", required=True, help="Block reason.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestration_block_cmd(
    plan_id: str, reason: str, json_output: bool,
):
    """Block the current orchestration stage."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        plan = orch.block_stage(plan_id, reason=reason)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if plan is None:
        msg = {"error": f"Orchestration not found: {plan_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Orchestration not found: {plan_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        console.print(f"[yellow]Stage blocked: {reason}[/yellow]")


@cli.command("orchestration-complete")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestration_complete_cmd(plan_id: str, json_output: bool):
    """Mark an orchestration as completed."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        plan = orch.complete_session(plan_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if plan is None:
        msg = {"error": f"Orchestration not found: {plan_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Orchestration not found: {plan_id}")
        raise SystemExit(2)

    try:
        orch.write_evidence(plan["plan_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        console.print("[green]Orchestration completed[/green]")


@cli.command("orchestration-summary")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def orchestration_summary_cmd(plan_id: str, json_output: bool):
    """Generate a summary for an orchestration plan."""
    from axiom_core.coding_session_orchestrator import CodingSessionOrchestrator

    try:
        orch = CodingSessionOrchestrator()
        summary = orch.generate_summary(plan_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if summary is None:
        msg = {"error": f"Orchestration not found: {plan_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Orchestration not found: {plan_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(summary, indent=2, default=str))
    else:
        _render_orchestration_summary_rich(summary)


def _render_orchestration_rich(plan: dict) -> None:
    """Render orchestration plan in rich text."""
    console.print("\n[bold]Coding Session Orchestration[/bold]\n")
    console.print(f"  Plan ID:        {plan.get('plan_id', '')}")
    console.print(f"  Session ID:     {plan.get('session_id', '')}")
    console.print(f"  Status:         {plan.get('status', '')}")
    console.print(f"  Current Stage:  {plan.get('current_stage', '')}")

    progress = plan.get("stage_progress", {})
    console.print(
        f"  Progress:       {progress.get('completed_stages', 0)}"
        f"/{progress.get('total_stages', 0)} "
        f"({progress.get('percentage', 0)}%)",
    )

    completed = plan.get("completed_stages", [])
    if completed:
        console.print(f"\n[bold]Completed Stages ({len(completed)}):[/bold]")
        for s in completed:
            console.print(f"  - {s}")

    blocked = plan.get("blocked_stages", [])
    if blocked:
        console.print(f"\n[bold]Blocked Stages ({len(blocked)}):[/bold]")
        for s in blocked:
            console.print(f"  - {s}")

    observations = plan.get("observations", [])
    if observations:
        console.print(f"\n[bold]Observations ({len(observations)}):[/bold]")
        for o in observations:
            console.print(f"  [{o['severity']}] {o['message']}")


def _render_orchestration_summary_rich(summary: dict) -> None:
    """Render orchestration summary in rich text."""
    console.print("\n[bold]Orchestration Summary[/bold]\n")
    console.print(f"  Plan ID:            {summary.get('plan_id', '')}")
    console.print(f"  Status:             {summary.get('status', '')}")
    console.print(f"  Current Stage:      {summary.get('current_stage', '')}")
    console.print(f"  Tasks:              {summary.get('total_tasks', 0)}")
    console.print(f"  Observations:       {summary.get('total_observations', 0)}")
    console.print(
        f"  Checkpoints:        "
        f"{summary.get('checkpoints_reached', 0)}"
        f"/{summary.get('checkpoints_total', 0)}",
    )

    warnings = summary.get("warnings", [])
    if warnings:
        console.print(f"\n[bold]Warnings ({len(warnings)}):[/bold]")
        for w in warnings:
            console.print(f"  [{w['severity']}] {w['message']}")




# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Autonomous Coding Session Registry v1 (PR #70)
# ---------------------------------------------------------------------------


@cli.command("coding-session-create")
@click.option("--title", required=True, help="Session title.")
@click.option("--description", default="", help="Session description.")
@click.option("--work-item-id", default="", help="Linked work item ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_session_create_cmd(
    title: str,
    description: str,
    work_item_id: str,
    json_output: bool,
):
    """Create a new coding session."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        session = registry.create_session(
            title=title,
            description=description,
            work_item_id=work_item_id,
        )
        registry.write_evidence(session["session_id"])
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    else:
        _render_session_rich(session)


@cli.command("coding-sessions")
@click.option("--status", default="", help="Filter by status.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_sessions_cmd(status: str, json_output: bool):
    """List all coding sessions."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        sessions = registry.list_sessions(status=status)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(sessions, indent=2, default=str))
    else:
        console.print(f"\n[bold]Coding Sessions ({len(sessions)})[/bold]\n")
        for s in sessions:
            console.print(
                f"  [{s['status']}] {s['session_id'][:12]}… "
                f"— {s['title']}",
            )


@cli.command("coding-session")
@click.option("--session-id", required=True, help="Session ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_session_cmd(session_id: str, json_output: bool):
    """Show a single coding session."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        session = registry.get_session(session_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if session is None:
        msg = {"error": f"Session not found: {session_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session not found: {session_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    else:
        _render_session_rich(session)


@cli.command("coding-session-update")
@click.option("--session-id", required=True, help="Session ID.")
@click.option("--status", required=True, help="New status.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_session_update_cmd(
    session_id: str, status: str, json_output: bool,
):
    """Update a coding session status."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        session = registry.update_status(session_id, status)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if session is None:
        msg = {"error": f"Session not found: {session_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session not found: {session_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    else:
        _render_session_rich(session)


@cli.command("coding-session-add-step")
@click.option("--session-id", required=True, help="Session ID.")
@click.option("--kind", required=True, help="Step kind.")
@click.option("--description", required=True, help="Step description.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_session_add_step_cmd(
    session_id: str, kind: str, description: str, json_output: bool,
):
    """Add a step to a coding session."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        session = registry.add_step(session_id, kind, description)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if session is None:
        msg = {"error": f"Session not found: {session_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session not found: {session_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    else:
        console.print(f"[green]Step added to session {session_id}[/green]")


@cli.command("coding-session-add-artifact")
@click.option("--session-id", required=True, help="Session ID.")
@click.option("--kind", required=True, help="Artifact kind.")
@click.option("--reference-id", default="", help="Reference ID.")
@click.option("--path", "artifact_path", default="", help="Artifact path.")
@click.option("--description", default="", help="Description.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_session_add_artifact_cmd(
    session_id: str,
    kind: str,
    reference_id: str,
    artifact_path: str,
    description: str,
    json_output: bool,
):
    """Add an artifact to a coding session."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        session = registry.add_artifact(
            session_id, kind, reference_id, artifact_path, description,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if session is None:
        msg = {"error": f"Session not found: {session_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session not found: {session_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    else:
        console.print(f"[green]Artifact added to session {session_id}[/green]")


@cli.command("coding-session-link")
@click.option("--session-id", required=True, help="Session ID.")
@click.option("--field", "field_name", required=True, help="Field to link.")
@click.option("--id", "linked_id", required=True, help="ID to link.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def coding_session_link_cmd(
    session_id: str,
    field_name: str,
    linked_id: str,
    json_output: bool,
):
    """Link an ID to a coding session field."""
    from axiom_core.coding_session_registry import CodingSessionRegistry

    try:
        registry = CodingSessionRegistry()
        session = registry.link_id(session_id, field_name, linked_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if session is None:
        msg = {"error": f"Session not found: {session_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session not found: {session_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    else:
        console.print(
            f"[green]Linked {field_name}={linked_id} to session {session_id}[/green]",
        )


def _render_session_rich(session: dict) -> None:
    """Render session details in rich text."""
    console.print("\n[bold]Coding Session[/bold]\n")
    console.print(f"  Session ID:     {session.get('session_id', '')}")
    console.print(f"  Title:          {session.get('title', '')}")
    console.print(f"  Status:         {session.get('status', '')}")
    if session.get("work_item_id"):
        console.print(f"  Work Item:      {session['work_item_id']}")
    if session.get("patch_proposal_id"):
        console.print(f"  Patch Proposal: {session['patch_proposal_id']}")
    if session.get("validation_run_id"):
        console.print(f"  Validation Run: {session['validation_run_id']}")

    steps = session.get("steps", [])
    if steps:
        console.print(f"\n[bold]Steps ({len(steps)}):[/bold]")
        for s in steps:
            console.print(
                f"  [{s['status']}] {s['kind']}: {s['description']}",
            )

    artifacts = session.get("artifacts", [])
    if artifacts:
        console.print(f"\n[bold]Artifacts ({len(artifacts)}):[/bold]")
        for a in artifacts:
            console.print(f"  [{a['kind']}] {a['description'] or a['path']}")

    blockers = session.get("blockers", [])
    if blockers:
        console.print("\n[bold]Blockers:[/bold]")
        for b in blockers:
            console.print(f"  - {b}")

    cost = session.get("cost_estimate", {})
    if cost:
        console.print("\n[bold]Cost Estimate:[/bold]")
        console.print(f"  Total steps:    {cost.get('total_steps', 0)}")
        console.print(f"  Completed:      {cost.get('completed_steps', 0)}")
        console.print(f"  Remaining:      {cost.get('estimated_remaining', 0)}")



# ---------------------------------------------------------------------------
# Code Review Policy Engine v1 (PR #69)
# ---------------------------------------------------------------------------


@cli.command("policy-evaluate")
@click.option(
    "--files", multiple=True, help="File paths to evaluate (repeatable).",
)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def policy_evaluate_cmd(files: tuple[str, ...], json_output: bool):
    """Evaluate code review policies against changed files."""
    from axiom_core.code_review_policy import CodeReviewPolicyEngine

    if not files:
        msg = {"error": "At least one --files argument is required."}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print("[red]Error:[/red] At least one --files argument is required.")
        raise SystemExit(1)

    try:
        engine = CodeReviewPolicyEngine()
        result = engine.evaluate_files(changed_files=list(files))
        engine.write_evidence(result)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_policy_result_rich(result)


@cli.command("policy-evaluate-files")
@click.argument("files", nargs=-1, required=True)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def policy_evaluate_files_cmd(files: tuple[str, ...], json_output: bool):
    """Evaluate policies against specific files (positional args)."""
    from axiom_core.code_review_policy import CodeReviewPolicyEngine

    try:
        engine = CodeReviewPolicyEngine()
        result = engine.evaluate_files(changed_files=list(files))
        engine.write_evidence(result)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_policy_result_rich(result)


@cli.command("policy-list")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def policy_list_cmd(json_output: bool):
    """List all registered review policies."""
    from axiom_core.code_review_policy import CodeReviewPolicyEngine

    engine = CodeReviewPolicyEngine()
    policies = engine.list_policies()

    if json_output:
        click.echo(json.dumps(policies, indent=2, default=str))
    else:
        console.print("\n[bold]Registered Review Policies[/bold]\n")
        for p in policies:
            console.print(
                f"  [{p['severity']}] {p['name']} ({p['category']}) "
                f"— origin: {p['origin']}",
            )


def _render_policy_result_rich(result: dict) -> None:
    """Render policy evaluation result in rich text."""
    console.print("\n[bold]Code Review Policy Evaluation[/bold]\n")
    console.print(f"  Run ID:       {result.get('run_id', '')}")
    console.print(f"  Files:        {len(result.get('files_evaluated', []))}")
    console.print(f"  Policies:     {result.get('policies_checked', 0)}")
    console.print(f"  Violations:   {result.get('total_violations', 0)}")
    console.print(f"  Passed:       {result.get('passed', True)}")

    by_sev = result.get("violations_by_severity", {})
    if by_sev:
        console.print("\n[bold]By Severity:[/bold]")
        for sev, count in sorted(by_sev.items()):
            console.print(f"  {sev}: {count}")

    violations = result.get("violations", [])
    if violations:
        console.print("\n[bold]Violations:[/bold]")
        for v in violations:
            console.print(
                f"  [{v['severity']}] {v['policy_name']} "
                f"at {v['file_path']}:{v['line_number']}",
            )
            console.print(f"    {v['description']}")



# ---------------------------------------------------------------------------
# Patch Impact Analyzer v1 (PR #68)
# ---------------------------------------------------------------------------


@cli.command("impact-analyze")
@click.option(
    "--proposal-id", default="", help="Patch proposal ID to analyze.",
)
@click.option(
    "--files", multiple=True, help="File paths to analyze (repeatable).",
)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def impact_analyze_cmd(
    proposal_id: str,
    files: tuple[str, ...],
    json_output: bool,
):
    """Analyze impact of proposed changes before patch application."""
    from axiom_core.patch_impact_analyzer import PatchImpactAnalyzer

    if not proposal_id and not files:
        msg = {"error": "At least one of --proposal-id or --files is required."}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print("[red]Error:[/red] At least one of --proposal-id or --files is required.")
        raise SystemExit(1)

    try:
        analyzer = PatchImpactAnalyzer()
        if proposal_id:
            result = analyzer.analyze_proposal(proposal_id)
        else:
            result = analyzer.analyze_files(changed_files=list(files))
        analyzer.write_evidence(result)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_impact_result_rich(result)


@cli.command("impact-analyze-files")
@click.argument("files", nargs=-1, required=True)
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def impact_analyze_files_cmd(files: tuple[str, ...], json_output: bool):
    """Analyze impact of specific files (positional args)."""
    from axiom_core.patch_impact_analyzer import PatchImpactAnalyzer

    try:
        analyzer = PatchImpactAnalyzer()
        result = analyzer.analyze_files(changed_files=list(files))
        analyzer.write_evidence(result)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_impact_result_rich(result)


def _render_impact_result_rich(result: dict) -> None:
    """Render impact analysis result in rich text."""
    scope = result.get("scope", {})
    console.print("\n[bold]Patch Impact Analysis[/bold]\n")
    console.print(f"  Run ID:           {result.get('run_id', '')}")
    console.print(f"  Proposal:         {result.get('proposal_id', 'N/A') or 'N/A'}")
    console.print(f"  Files changed:    {scope.get('total_files', 0)}")
    console.print(f"  Symbols affected: {scope.get('total_symbols', 0)}")
    console.print(f"  Commands:         {scope.get('total_commands', 0)}")
    console.print(f"  Tests:            {scope.get('total_tests', 0)}")
    console.print(f"  Docs:             {scope.get('total_docs', 0)}")
    console.print(f"  Evidence:         {scope.get('total_evidence', 0)}")
    console.print(f"  Risk flags:       {scope.get('total_risk_flags', 0)}")
    console.print(f"  Overall impact:   {scope.get('overall_impact', '')}")
    console.print(f"  Full suite:       {scope.get('requires_full_suite', False)}")

    if scope.get("high_risk_flags"):
        console.print("\n[bold]High-Risk Flags:[/bold]")
        for flag in scope["high_risk_flags"]:
            console.print(
                f"  [{flag['impact_level']}] {flag['risk_area']}: "
                f"{flag['reason']} ({flag['file_path']})",
            )

    if scope.get("affected_tests"):
        console.print("\n[bold]Affected Tests:[/bold]")
        for test in scope["affected_tests"]:
            console.print(f"  - {test['test_path']} ({test['reason']})")

    if scope.get("affected_commands"):
        console.print("\n[bold]Affected Commands:[/bold]")
        for cmd in scope["affected_commands"]:
            console.print(f"  - {cmd['command_name']}")


# ---------------------------------------------------------------------------
# Session Plan Registry v1 (PR #72)
# ---------------------------------------------------------------------------


@cli.command("session-plan-create")
@click.option("--title", required=True, help="Plan title.")
@click.option("--session-id", default="", help="Linked session ID.")
@click.option("--work-item-id", default="", help="Linked work item ID.")
@click.option("--rationale", default="", help="Plan rationale.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def session_plan_create_cmd(
    title: str,
    session_id: str,
    work_item_id: str,
    rationale: str,
    json_output: bool,
):
    """Create a new session plan."""
    from axiom_core.session_plan_registry import SessionPlanRegistry

    try:
        registry = SessionPlanRegistry()
        plan = registry.create_plan(
            title=title,
            session_id=session_id,
            work_item_id=work_item_id,
            rationale=rationale,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(plan["plan_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        _render_session_plan_rich(plan)


@cli.command("session-plans")
@click.option("--status", default="", help="Filter by status.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def session_plans_cmd(status: str, json_output: bool):
    """List all session plans."""
    from axiom_core.session_plan_registry import SessionPlanRegistry

    try:
        registry = SessionPlanRegistry()
        plans = registry.list_plans(status=status)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(plans, indent=2, default=str))
    else:
        console.print(f"\n[bold]Session Plans ({len(plans)})[/bold]\n")
        for p in plans:
            summary = p.get("step_summary", {})
            console.print(
                f"  [{p.get('status', '')}] {p.get('plan_id', '')[:12]}… "
                f"— {p.get('title', '')} "
                f"({summary.get('total', 0)} steps, "
                f"{summary.get('completed', 0)} done)",
            )


@cli.command("session-plan-show")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def session_plan_show_cmd(plan_id: str, json_output: bool):
    """Show a single session plan."""
    from axiom_core.session_plan_registry import SessionPlanRegistry

    try:
        registry = SessionPlanRegistry()
        plan = registry.get_plan(plan_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if plan is None:
        msg = {"error": f"Plan not found: {plan_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Plan not found: {plan_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        _render_session_plan_rich(plan)


@cli.command("session-plan-export")
@click.option("--plan-id", required=True, help="Plan ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def session_plan_export_cmd(plan_id: str, json_output: bool):
    """Export a session plan as markdown."""
    from axiom_core.session_plan_registry import SessionPlanRegistry

    try:
        registry = SessionPlanRegistry()
        markdown = registry.export_plan(plan_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        plan = registry.get_plan(plan_id)
        if plan is None:
            msg = {"error": f"Plan not found: {plan_id}"}
            click.echo(json.dumps(msg, indent=2))
            raise SystemExit(2)
        click.echo(json.dumps(plan, indent=2, default=str))
    else:
        click.echo(markdown)


def _render_session_plan_rich(plan: dict) -> None:
    """Rich text rendering for a session plan."""
    console.print(f"\n[bold]Session Plan ({plan.get('status', '').upper()})[/bold]\n")
    console.print(f"  Plan ID:     {plan.get('plan_id', '')}")
    console.print(f"  Title:       {plan.get('title', '')}")
    console.print(f"  Status:      {plan.get('status', '')}")
    if plan.get("session_id"):
        console.print(f"  Session ID:  {plan['session_id']}")
    if plan.get("work_item_id"):
        console.print(f"  Work Item:   {plan['work_item_id']}")
    if plan.get("rationale"):
        console.print(f"  Rationale:   {plan['rationale']}")

    summary = plan.get("step_summary", {})
    console.print(
        f"\n  Steps: {summary.get('total', 0)} total, "
        f"{summary.get('completed', 0)} completed, "
        f"{summary.get('remaining', 0)} remaining",
    )

    goals = plan.get("goals", [])
    if goals:
        console.print(f"\n[bold]Goals ({len(goals)}):[/bold]")
        for g in goals:
            console.print(
                f"  [{g.get('priority', 'medium')}] {g.get('description', '')}",
            )

    assumptions = plan.get("assumptions", [])
    if assumptions:
        console.print(f"\n[bold]Assumptions ({len(assumptions)}):[/bold]")
        for a in assumptions:
            verified = "verified" if a.get("verified") else "unverified"
            console.print(f"  [{verified}] {a.get('description', '')}")

    constraints = plan.get("constraints", [])
    if constraints:
        console.print(f"\n[bold]Constraints ({len(constraints)}):[/bold]")
        for c in constraints:
            console.print(f"  {c.get('description', '')}")

    steps = plan.get("steps", [])
    if steps:
        console.print(f"\n[bold]Steps ({len(steps)}):[/bold]")
        for s in sorted(steps, key=lambda x: x.get("order", 0)):
            console.print(
                f"  {s.get('order', 0)}. [{s.get('category', '')}] "
                f"{s.get('description', '')} ({s.get('status', '')})",
            )


# ---------------------------------------------------------------------------
# Session Question Registry v1 (PR #73)
# ---------------------------------------------------------------------------


@cli.command("question-create")
@click.option("--text", required=True, help="Question text.")
@click.option("--context", default="", help="Additional context.")
@click.option("--priority", default="medium", help="Priority (critical/high/medium/low).")
@click.option("--plan-id", default="", help="Linked plan ID.")
@click.option("--work-item-id", default="", help="Linked work item ID.")
@click.option("--rationale", default="", help="Why this question matters.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def question_create_cmd(
    text: str,
    context: str,
    priority: str,
    plan_id: str,
    work_item_id: str,
    rationale: str,
    json_output: bool,
):
    """Create a new session question."""
    from axiom_core.session_question_registry import SessionQuestionRegistry

    try:
        registry = SessionQuestionRegistry()
        question = registry.create_question(
            text=text,
            context=context,
            priority=priority,
            plan_id=plan_id,
            work_item_id=work_item_id,
            rationale=rationale,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(question["question_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(question, indent=2, default=str))
    else:
        _render_question_rich(question)


@cli.command("questions")
@click.option("--status", default="", help="Filter by status.")
@click.option("--plan-id", default="", help="Filter by plan ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def questions_cmd(status: str, plan_id: str, json_output: bool):
    """List all session questions."""
    from axiom_core.session_question_registry import SessionQuestionRegistry

    try:
        registry = SessionQuestionRegistry()
        questions = registry.list_questions(status=status, plan_id=plan_id)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(questions, indent=2, default=str))
    else:
        console.print(f"\n[bold]Session Questions ({len(questions)})[/bold]\n")
        for q in questions:
            summary = q.get("question_summary", {})
            ans = summary.get("total_answers", 0)
            console.print(
                f"  [{q.get('status', '')}] {q.get('question_id', '')[:12]}… "
                f"— {q.get('text', '')[:60]} "
                f"({ans} answers)",
            )


@cli.command("question-show")
@click.option("--question-id", required=True, help="Question ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def question_show_cmd(question_id: str, json_output: bool):
    """Show a single session question."""
    from axiom_core.session_question_registry import SessionQuestionRegistry

    try:
        registry = SessionQuestionRegistry()
        question = registry.get_question(question_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if question is None:
        msg = {"error": f"Question not found: {question_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Question not found: {question_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(question, indent=2, default=str))
    else:
        _render_question_rich(question)


@cli.command("question-resolve")
@click.option("--question-id", required=True, help="Question ID.")
@click.option("--answer", required=True, help="Resolution answer.")
@click.option("--source", default="", help="Answer source.")
@click.option("--rationale", default="", help="Resolution rationale.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def question_resolve_cmd(
    question_id: str,
    answer: str,
    source: str,
    rationale: str,
    json_output: bool,
):
    """Resolve a session question with an answer."""
    from axiom_core.session_question_registry import SessionQuestionRegistry

    try:
        registry = SessionQuestionRegistry()
        question = registry.resolve_question(
            question_id=question_id,
            answer=answer,
            source=source,
            rationale=rationale,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if question is None:
        msg = {"error": f"Question not found: {question_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Question not found: {question_id}")
        raise SystemExit(2)

    try:
        registry.write_evidence(question["question_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(question, indent=2, default=str))
    else:
        _render_question_rich(question)


def _render_question_rich(question: dict) -> None:
    """Rich text rendering for a session question."""
    status = question.get("status", "").upper()
    console.print(f"\n[bold]Session Question ({status})[/bold]\n")
    console.print(f"  Question ID: {question.get('question_id', '')}")
    console.print(f"  Text:        {question.get('text', '')}")
    console.print(f"  Status:      {question.get('status', '')}")
    console.print(f"  Priority:    {question.get('priority', '')}")
    if question.get("plan_id"):
        console.print(f"  Plan ID:     {question['plan_id']}")
    if question.get("work_item_id"):
        console.print(f"  Work Item:   {question['work_item_id']}")
    if question.get("context"):
        console.print(f"  Context:     {question['context']}")
    if question.get("rationale"):
        console.print(f"  Rationale:   {question['rationale']}")

    summary = question.get("question_summary", {})
    console.print(
        f"\n  Answers: {summary.get('total_answers', 0)} total, "
        f"resolved: {summary.get('is_resolved', False)}",
    )

    answers = question.get("answers", [])
    if answers:
        resolved_id = question.get("resolved_answer_id", "")
        console.print(f"\n[bold]Answers ({len(answers)}):[/bold]")
        for a in answers:
            marker = " [green][ACCEPTED][/green]" if a.get("answer_id") == resolved_id else ""
            src = f" (source: {a['source']})" if a.get("source") else ""
            console.print(f"  - {a.get('content', '')}{src}{marker}")

    if question.get("resolution_rationale"):
        console.print(f"\n[bold]Resolution:[/bold] {question['resolution_rationale']}")


# ---------------------------------------------------------------------------
# Assertion Registry v1 (PR #74)
# ---------------------------------------------------------------------------


@cli.command("assertion-create")
@click.option("--type", "assertion_type", required=True, help="Assertion type.")
@click.option("--description", required=True, help="Assertion description.")
@click.option("--expected-value", default="", help="Expected value.")
@click.option("--severity", default="medium", help="Severity (critical/high/medium/low).")
@click.option("--plan-id", default="", help="Linked plan ID.")
@click.option("--question-id", default="", help="Linked question ID.")
@click.option("--work-item-id", default="", help="Linked work item ID.")
@click.option("--capability", default="", help="Target capability.")
@click.option("--rationale", default="", help="Why this assertion matters.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def assertion_create_cmd(
    assertion_type: str,
    description: str,
    expected_value: str,
    severity: str,
    plan_id: str,
    question_id: str,
    work_item_id: str,
    capability: str,
    rationale: str,
    json_output: bool,
):
    """Create a new assertion."""
    from axiom_core.assertion_registry import AssertionRegistry

    try:
        registry = AssertionRegistry()
        assertion = registry.create_assertion(
            assertion_type=assertion_type,
            description=description,
            expected_value=expected_value,
            severity=severity,
            plan_id=plan_id,
            question_id=question_id,
            work_item_id=work_item_id,
            capability=capability,
            rationale=rationale,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(assertion["assertion_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(assertion, indent=2, default=str))
    else:
        _render_assertion_rich(assertion)


@cli.command("assertions")
@click.option("--status", default="", help="Filter by status.")
@click.option("--type", "assertion_type", default="", help="Filter by type.")
@click.option("--capability", default="", help="Filter by capability.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def assertions_cmd(
    status: str, assertion_type: str, capability: str, json_output: bool,
):
    """List all assertions."""
    from axiom_core.assertion_registry import AssertionRegistry

    try:
        registry = AssertionRegistry()
        assertions = registry.list_assertions(
            status=status,
            assertion_type=assertion_type,
            capability=capability,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(assertions, indent=2, default=str))
    else:
        console.print(f"\n[bold]Assertions ({len(assertions)})[/bold]\n")
        for a in assertions:
            summary = a.get("assertion_summary", {})
            console.print(
                f"  [{a.get('status', '')}] {a.get('assertion_id', '')[:12]}… "
                f"— [{a.get('assertion_type', '')}] {a.get('description', '')[:50]} "
                f"(results: {summary.get('total_results', 0)})",
            )


@cli.command("assertion-results")
@click.option("--assertion-id", required=True, help="Assertion ID.")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def assertion_results_cmd(assertion_id: str, json_output: bool):
    """List results for an assertion."""
    from axiom_core.assertion_registry import AssertionRegistry

    try:
        registry = AssertionRegistry()
        assertion = registry.get_assertion(assertion_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if assertion is None:
        msg = {"error": f"Assertion not found: {assertion_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Assertion not found: {assertion_id}")
        raise SystemExit(2)

    results = assertion.get("results", [])
    if json_output:
        click.echo(json.dumps(results, indent=2, default=str))
    else:
        console.print(
            f"\n[bold]Assertion Results ({len(results)})[/bold]\n",
        )
        console.print(f"  Assertion: {assertion.get('description', '')}")
        console.print(f"  Type: {assertion.get('assertion_type', '')}")
        console.print(f"  Expected: {assertion.get('expected_value', '')}")
        console.print(f"  Status: {assertion.get('status', '')}\n")
        for r in results:
            src = f" (source: {r['source']})" if r.get("source") else ""
            console.print(
                f"  [{r.get('status', '')}] "
                f"actual={r.get('actual_value', '')}{src}",
            )
            if r.get("message"):
                console.print(f"    {r['message']}")


def _render_assertion_rich(assertion: dict) -> None:
    """Rich text rendering for an assertion."""
    status = assertion.get("status", "").upper()
    console.print(f"\n[bold]Assertion ({status})[/bold]\n")
    console.print(f"  Assertion ID: {assertion.get('assertion_id', '')}")
    console.print(f"  Type:         {assertion.get('assertion_type', '')}")
    console.print(f"  Description:  {assertion.get('description', '')}")
    console.print(f"  Expected:     {assertion.get('expected_value', '')}")
    console.print(f"  Severity:     {assertion.get('severity', '')}")
    console.print(f"  Status:       {assertion.get('status', '')}")
    if assertion.get("capability"):
        console.print(f"  Capability:   {assertion['capability']}")
    if assertion.get("plan_id"):
        console.print(f"  Plan ID:      {assertion['plan_id']}")
    if assertion.get("question_id"):
        console.print(f"  Question ID:  {assertion['question_id']}")
    if assertion.get("work_item_id"):
        console.print(f"  Work Item:    {assertion['work_item_id']}")
    if assertion.get("rationale"):
        console.print(f"  Rationale:    {assertion['rationale']}")

    summary = assertion.get("assertion_summary", {})
    console.print(
        f"\n  Results: {summary.get('total_results', 0)} total, "
        f"{summary.get('passed', 0)} passed, "
        f"{summary.get('failed', 0)} failed",
    )


# ---------------------------------------------------------------------------
# Session Report Generator CLI
# ---------------------------------------------------------------------------


@cli.command("session-report")
@click.option("--title", required=True, help="Report title")
@click.option("--session-id", default="", help="Session ID")
@click.option("--plan-id", default="", help="Linked plan ID")
@click.option("--work-item-id", default="", help="Linked work item ID")
@click.option("--rationale", default="", help="Rationale for the report")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_report_cmd(
    title: str,
    session_id: str,
    plan_id: str,
    work_item_id: str,
    rationale: str,
    json_output: bool,
) -> None:
    """Create a new session report."""
    from axiom_core.session_report_generator import SessionReportGenerator

    try:
        gen = SessionReportGenerator()
        report = gen.create_report(
            title=title,
            session_id=session_id,
            plan_id=plan_id,
            work_item_id=work_item_id,
            rationale=rationale,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        gen.write_evidence(report["report_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_report_rich(report)


@cli.command("session-reports")
@click.option("--status", default="", help="Filter by status (draft/final/superseded)")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_reports_cmd(
    status: str,
    json_output: bool,
) -> None:
    """List session reports."""
    from axiom_core.session_report_generator import SessionReportGenerator

    try:
        gen = SessionReportGenerator()
        reports = gen.list_reports(status=status)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        if not reports:
            console.print("[dim]No reports found.[/dim]")
            return
        for r in reports:
            _render_report_rich(r)


@cli.command("session-report-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_report_show_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Show details of a session report."""
    from axiom_core.session_report_generator import SessionReportGenerator

    try:
        gen = SessionReportGenerator()
        report = gen.get_report(report_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        msg = {"error": f"Report not found: {report_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_report_rich(report)


@cli.command("session-report-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_report_export_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Export a session report as markdown."""
    from axiom_core.session_report_generator import SessionReportGenerator

    try:
        gen = SessionReportGenerator()
        report = gen.get_report(report_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        msg = {"error": f"Report not found: {report_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = gen.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_report_rich(report: dict) -> None:
    """Rich text rendering for a session report."""
    status = report.get("status", "").upper()
    console.print(f"\n[bold]Session Report ({status})[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Title:        {report.get('title', '')}")
    console.print(f"  Status:       {report.get('status', '')}")
    if report.get("session_id"):
        console.print(f"  Session ID:   {report['session_id']}")
    if report.get("plan_id"):
        console.print(f"  Plan ID:      {report['plan_id']}")
    if report.get("work_item_id"):
        console.print(f"  Work Item:    {report['work_item_id']}")
    if report.get("rationale"):
        console.print(f"  Rationale:    {report['rationale']}")

    sections = report.get("sections", [])
    if sections:
        console.print(f"\n  Sections: {len(sections)}")
        for s in sections:
            console.print(
                f"    [{s.get('section_type', 'custom')}] "
                f"{s.get('title', '(untitled)')}",
            )

    recs = report.get("recommendations", [])
    if recs:
        console.print(f"\n  Recommendations: {len(recs)}")
        for r in recs:
            console.print(
                f"    [{r.get('priority', 'medium')}] "
                f"{r.get('description', '')}",
            )

    summary = report.get("report_summary", {})
    console.print(
        f"\n  Summary: {summary.get('total_sections', 0)} sections, "
        f"{summary.get('total_recommendations', 0)} recommendations, "
        f"{summary.get('critical_recommendations', 0)} critical",
    )


# ---------------------------------------------------------------------------
# Session Review Registry CLI
# ---------------------------------------------------------------------------


@cli.command("review-create")
@click.option("--title", required=True, help="Review title")
@click.option("--source", default="", help="Review source (devin_review/human_review/ci_failure/cli_testing/automated_agent/other)")
@click.option("--severity", default="", help="Severity (critical/high/medium/low/info)")
@click.option("--pr-id", default="", help="Linked PR ID")
@click.option("--coding-session-id", default="", help="Linked coding session ID")
@click.option("--session-report-id", default="", help="Linked session report ID")
@click.option("--rationale", default="", help="Rationale for the review")
@click.option("--json-output", is_flag=True, help="Output JSON")
def review_create_cmd(
    title: str,
    source: str,
    severity: str,
    pr_id: str,
    coding_session_id: str,
    session_report_id: str,
    rationale: str,
    json_output: bool,
) -> None:
    """Create a new session review."""
    from axiom_core.session_review_registry import SessionReviewRegistry

    try:
        registry = SessionReviewRegistry()
        review = registry.create_review(
            title=title,
            source=source,
            severity=severity,
            pr_id=pr_id,
            coding_session_id=coding_session_id,
            session_report_id=session_report_id,
            rationale=rationale,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(review["review_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(review, indent=2, default=str))
    else:
        _render_review_rich(review)


@cli.command("review-add-finding")
@click.argument("review_id")
@click.option("--summary", required=True, help="Finding summary")
@click.option("--details", default="", help="Finding details")
@click.option("--severity", default="", help="Severity (critical/high/medium/low/info)")
@click.option("--source", default="", help="Finding source")
@click.option("--file-path", default="", help="File path reference")
@click.option("--line-number", default=0, type=int, help="Line number")
@click.option("--json-output", is_flag=True, help="Output JSON")
def review_add_finding_cmd(
    review_id: str,
    summary: str,
    details: str,
    severity: str,
    source: str,
    file_path: str,
    line_number: int,
    json_output: bool,
) -> None:
    """Add a finding to a session review."""
    from axiom_core.session_review_registry import SessionReviewRegistry

    try:
        registry = SessionReviewRegistry()
        finding = registry.add_finding(
            review_id=review_id,
            summary=summary,
            details=details,
            severity=severity,
            source=source,
            file_path=file_path,
            line_number=line_number,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        if "not found" in str(exc).lower():
            raise SystemExit(2)
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(finding, indent=2, default=str))
    else:
        console.print(f"\n[bold]Finding added[/bold]: {finding['finding_id']}")
        console.print(f"  Summary:  {finding['summary']}")
        console.print(f"  Severity: {finding['severity']}")
        console.print(f"  Status:   {finding['status']}")


@cli.command("review-resolve")
@click.argument("review_id")
@click.option("--finding-id", required=True, help="Finding ID to resolve")
@click.option("--status", required=True, help="Resolution status (fixed/acknowledged/rejected/deferred)")
@click.option("--note", default="", help="Resolution note")
@click.option("--resolved-by", default="", help="Who resolved it")
@click.option("--commit-id", default="", help="Fix commit ID")
@click.option("--json-output", is_flag=True, help="Output JSON")
def review_resolve_cmd(
    review_id: str,
    finding_id: str,
    status: str,
    note: str,
    resolved_by: str,
    commit_id: str,
    json_output: bool,
) -> None:
    """Resolve a finding in a session review."""
    from axiom_core.session_review_registry import SessionReviewRegistry

    try:
        registry = SessionReviewRegistry()
        resolution = registry.resolve_finding(
            review_id=review_id,
            finding_id=finding_id,
            status=status,
            resolution_note=note,
            resolved_by=resolved_by,
            commit_id=commit_id,
        )
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        if "not found" in str(exc).lower():
            raise SystemExit(2)
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(resolution, indent=2, default=str))
    else:
        console.print(f"\n[bold]Finding resolved[/bold]: {finding_id}")
        console.print(f"  Status: {status}")
        if note:
            console.print(f"  Note:   {note}")
        if commit_id:
            console.print(f"  Commit: {commit_id}")


@cli.command("reviews")
@click.option("--status", default="", help="Filter by status (open/in_progress/resolved/closed)")
@click.option("--source", default="", help="Filter by source")
@click.option("--json-output", is_flag=True, help="Output JSON")
def reviews_cmd(
    status: str,
    source: str,
    json_output: bool,
) -> None:
    """List session reviews."""
    from axiom_core.session_review_registry import SessionReviewRegistry

    try:
        registry = SessionReviewRegistry()
        reviews = registry.list_reviews(status=status, source=source)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reviews, indent=2, default=str))
    else:
        if not reviews:
            console.print("[dim]No reviews found.[/dim]")
            return
        console.print(f"\n[bold]Session Reviews ({len(reviews)})[/bold]\n")
        for r in reviews:
            summary = r.get("review_summary", {})
            console.print(
                f"  [{r.get('status', '')}] {r.get('review_id', '')[:12]}… "
                f"— {r.get('title', '')} "
                f"({summary.get('total_findings', 0)} findings, "
                f"{summary.get('open_findings', 0)} open)",
            )


@cli.command("review-show")
@click.argument("review_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def review_show_cmd(
    review_id: str,
    json_output: bool,
) -> None:
    """Show details of a session review."""
    from axiom_core.session_review_registry import SessionReviewRegistry

    try:
        registry = SessionReviewRegistry()
        review = registry.get_review(review_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if review is None:
        msg = {"error": f"Review not found: {review_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Review not found: {review_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(review, indent=2, default=str))
    else:
        _render_review_rich(review)


@cli.command("review-export")
@click.argument("review_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def review_export_cmd(
    review_id: str,
    json_output: bool,
) -> None:
    """Export a session review as markdown."""
    from axiom_core.session_review_registry import SessionReviewRegistry

    try:
        registry = SessionReviewRegistry()
        review = registry.get_review(review_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if review is None:
        msg = {"error": f"Review not found: {review_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] Review not found: {review_id}")
        raise SystemExit(2)

    md = registry.export_review(review_id)

    if json_output:
        click.echo(
            json.dumps(
                {"review_id": review_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_review_rich(review: dict) -> None:
    """Rich text rendering for a session review."""
    status = review.get("status", "").upper()
    console.print(f"\n[bold]Session Review ({status})[/bold]\n")
    console.print(f"  Review ID:       {review.get('review_id', '')}")
    console.print(f"  Title:           {review.get('title', '')}")
    console.print(f"  Source:          {review.get('source', '')}")
    console.print(f"  Status:          {review.get('status', '')}")
    console.print(f"  Severity:        {review.get('severity', '')}")
    if review.get("pr_id"):
        console.print(f"  PR ID:           {review['pr_id']}")
    if review.get("coding_session_id"):
        console.print(f"  Coding Session:  {review['coding_session_id']}")
    if review.get("session_report_id"):
        console.print(f"  Session Report:  {review['session_report_id']}")
    if review.get("rationale"):
        console.print(f"  Rationale:       {review['rationale']}")

    summary = review.get("review_summary", {})
    console.print(
        f"\n  Summary: {summary.get('total_findings', 0)} findings, "
        f"{summary.get('open_findings', 0)} open, "
        f"{summary.get('fixed_findings', 0)} fixed, "
        f"{summary.get('critical_findings', 0)} critical",
    )

    findings = review.get("findings", [])
    if findings:
        console.print("\n  [bold]Findings:[/bold]")
        for f in findings:
            sev = f.get("severity", "medium").upper()
            st = f.get("status", "open").upper()
            console.print(f"    [{sev}/{st}] {f.get('summary', '')}")


# ---------------------------------------------------------------------------
# Escalation Framework CLI
# ---------------------------------------------------------------------------


@cli.command("escalation-create")
@click.option("--title", required=True, help="Escalation title")
@click.option("--description", default="", help="Escalation description")
@click.option("--reason", default="", help="Escalation reason")
@click.option("--severity", default="", help="Severity (none/info/warning/blocker/human_required)")
@click.option("--category", default="", help="Category (evidence_gap/architecture/validation/repeated_failure/dependency/conflict/other)")
@click.option("--source", default="", help="Escalation source")
@click.option("--json-output", is_flag=True, help="Output JSON")
def escalation_create_cmd(
    title: str,
    description: str,
    reason: str,
    severity: str,
    category: str,
    source: str,
    json_output: bool,
) -> None:
    """Create a new escalation."""
    from axiom_core.escalation_registry import EscalationRegistry

    try:
        registry = EscalationRegistry()
        escalation = registry.create_escalation(
            title=title,
            description=description,
            reason=reason,
            severity=severity,
            category=category,
            source=source,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(escalation["escalation_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(escalation, indent=2, default=str))
    else:
        _render_escalation_rich(escalation)


@cli.command("escalations")
@click.option("--status", default="", help="Filter by status")
@click.option("--severity", default="", help="Filter by severity")
@click.option("--category", default="", help="Filter by category")
@click.option("--json-output", is_flag=True, help="Output JSON")
def escalations_cmd(
    status: str,
    severity: str,
    category: str,
    json_output: bool,
) -> None:
    """List escalations."""
    from axiom_core.escalation_registry import EscalationRegistry

    try:
        registry = EscalationRegistry()
        escalations = registry.list_escalations(
            status=status, severity=severity, category=category,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(escalations, indent=2, default=str))
    else:
        if not escalations:
            console.print("[dim]No escalations found.[/dim]")
            return
        console.print(f"\n[bold]Escalations ({len(escalations)})[/bold]\n")
        for e in escalations:
            sev = e.get("severity", "info").upper()
            console.print(
                f"  [{e.get('status', '')}] {e.get('escalation_id', '')[:12]}… "
                f"— [{sev}] {e.get('title', '')}",
            )


@cli.command("escalation-show")
@click.argument("escalation_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def escalation_show_cmd(
    escalation_id: str,
    json_output: bool,
) -> None:
    """Show details of an escalation."""
    from axiom_core.escalation_registry import EscalationRegistry

    try:
        registry = EscalationRegistry()
        escalation = registry.get_escalation(escalation_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if escalation is None:
        msg = {"error": f"Escalation not found: {escalation_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Escalation not found: {escalation_id}",
            )
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(escalation, indent=2, default=str))
    else:
        _render_escalation_rich(escalation)


@cli.command("escalation-export")
@click.argument("escalation_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def escalation_export_cmd(
    escalation_id: str,
    json_output: bool,
) -> None:
    """Export an escalation as markdown."""
    from axiom_core.escalation_registry import EscalationRegistry

    try:
        registry = EscalationRegistry()
        escalation = registry.get_escalation(escalation_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if escalation is None:
        msg = {"error": f"Escalation not found: {escalation_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Escalation not found: {escalation_id}",
            )
        raise SystemExit(2)

    md = registry.export_escalation(escalation_id)

    if json_output:
        click.echo(
            json.dumps(
                {"escalation_id": escalation_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_escalation_rich(escalation: dict) -> None:
    """Rich text rendering for an escalation."""
    status = escalation.get("status", "").upper()
    sev = escalation.get("severity", "").upper()
    console.print(f"\n[bold]Escalation ({status})[/bold]\n")
    console.print(f"  Escalation ID: {escalation.get('escalation_id', '')}")
    console.print(f"  Title:         {escalation.get('title', '')}")
    console.print(f"  Severity:      {sev}")
    console.print(f"  Category:      {escalation.get('category', '')}")
    console.print(f"  Status:        {escalation.get('status', '')}")
    if escalation.get("source"):
        console.print(f"  Source:        {escalation['source']}")
    if escalation.get("reason"):
        console.print(f"  Reason:        {escalation['reason']}")
    if escalation.get("description"):
        console.print(f"  Description:   {escalation['description']}")
    if escalation.get("resolution_notes"):
        console.print(f"  Resolution:    {escalation['resolution_notes']}")


# ---------------------------------------------------------------------------
# Repair Proposal Framework CLI
# ---------------------------------------------------------------------------


@cli.command("repair-proposal-create")
@click.option("--title", required=True, help="Proposal title")
@click.option("--escalation-id", default="", help="Linked escalation ID")
@click.option("--description", default="", help="Proposal description")
@click.option("--source", default="", help="Source (escalation/assertion/review_finding/validation)")
@click.option("--proposal-type", default="", help="Type (code_change/test_change/configuration/documentation/other)")
@click.option("--rationale", default="", help="Rationale for the proposal")
@click.option("--recommendations", default="", help="Recommendations")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_proposal_create_cmd(
    title: str,
    escalation_id: str,
    description: str,
    source: str,
    proposal_type: str,
    rationale: str,
    recommendations: str,
    json_output: bool,
) -> None:
    """Create a new repair proposal."""
    from axiom_core.repair_proposal_registry import RepairProposalRegistry

    try:
        registry = RepairProposalRegistry()
        proposal = registry.create_proposal(
            title=title,
            escalation_id=escalation_id,
            description=description,
            source=source,
            proposal_type=proposal_type,
            rationale=rationale,
            recommendations=recommendations,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(proposal["proposal_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(proposal, indent=2, default=str))
    else:
        _render_repair_proposal_rich(proposal)


@cli.command("repair-proposals")
@click.option("--status", default="", help="Filter by status")
@click.option("--proposal-type", default="", help="Filter by proposal type")
@click.option("--source", default="", help="Filter by source")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_proposals_cmd(
    status: str,
    proposal_type: str,
    source: str,
    json_output: bool,
) -> None:
    """List repair proposals."""
    from axiom_core.repair_proposal_registry import RepairProposalRegistry

    try:
        registry = RepairProposalRegistry()
        proposals = registry.list_proposals(
            status=status, proposal_type=proposal_type, source=source,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(proposals, indent=2, default=str))
    else:
        if not proposals:
            console.print("[dim]No repair proposals found.[/dim]")
            return
        console.print(f"\n[bold]Repair Proposals ({len(proposals)})[/bold]\n")
        for p in proposals:
            ptype = p.get("proposal_type", "other").upper()
            console.print(
                f"  [{p.get('status', '')}] {p.get('proposal_id', '')[:12]}… "
                f"— [{ptype}] {p.get('title', '')}",
            )


@cli.command("repair-proposal-show")
@click.argument("proposal_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_proposal_show_cmd(
    proposal_id: str,
    json_output: bool,
) -> None:
    """Show details of a repair proposal."""
    from axiom_core.repair_proposal_registry import RepairProposalRegistry

    try:
        registry = RepairProposalRegistry()
        proposal = registry.get_proposal(proposal_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if proposal is None:
        msg = {"error": f"Repair proposal not found: {proposal_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Repair proposal not found: {proposal_id}",
            )
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(proposal, indent=2, default=str))
    else:
        _render_repair_proposal_rich(proposal)


@cli.command("repair-proposal-export")
@click.argument("proposal_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_proposal_export_cmd(
    proposal_id: str,
    json_output: bool,
) -> None:
    """Export a repair proposal as markdown."""
    from axiom_core.repair_proposal_registry import RepairProposalRegistry

    try:
        registry = RepairProposalRegistry()
        proposal = registry.get_proposal(proposal_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if proposal is None:
        msg = {"error": f"Repair proposal not found: {proposal_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Repair proposal not found: {proposal_id}",
            )
        raise SystemExit(2)

    md = registry.export_proposal(proposal_id)

    if json_output:
        click.echo(
            json.dumps(
                {"proposal_id": proposal_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_repair_proposal_rich(proposal: dict) -> None:
    """Rich text rendering for a repair proposal."""
    status = proposal.get("status", "").upper()
    ptype = proposal.get("proposal_type", "").upper()
    console.print(f"\n[bold]Repair Proposal ({status})[/bold]\n")
    console.print(f"  Proposal ID:   {proposal.get('proposal_id', '')}")
    console.print(f"  Title:         {proposal.get('title', '')}")
    console.print(f"  Type:          {ptype}")
    console.print(f"  Source:        {proposal.get('source', '')}")
    console.print(f"  Status:        {proposal.get('status', '')}")
    if proposal.get("escalation_id"):
        console.print(f"  Escalation ID: {proposal['escalation_id']}")
    if proposal.get("rationale"):
        console.print(f"  Rationale:     {proposal['rationale']}")
    if proposal.get("description"):
        console.print(f"  Description:   {proposal['description']}")
    if proposal.get("recommendations"):
        console.print(f"  Recommendations: {proposal['recommendations']}")


# ---------------------------------------------------------------------------
# Repair Decision Framework CLI
# ---------------------------------------------------------------------------


@cli.command("repair-decision-create")
@click.option("--title", required=True, help="Decision title")
@click.option("--proposal-id", default="", help="Linked proposal ID")
@click.option("--description", default="", help="Decision description")
@click.option("--source", default="", help="Source (repair_proposal/escalation/review_finding/validation)")
@click.option("--status", default="", help="Status (accepted/rejected/deferred/superseded)")
@click.option("--reason", default="", help="Reason (technical/policy/risk/duplicate/human_judgment/other)")
@click.option("--rationale", default="", help="Rationale for the decision")
@click.option("--notes", default="", help="Additional notes")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_decision_create_cmd(
    title: str,
    proposal_id: str,
    description: str,
    source: str,
    status: str,
    reason: str,
    rationale: str,
    notes: str,
    json_output: bool,
) -> None:
    """Create a new repair decision."""
    from axiom_core.repair_decision_registry import RepairDecisionRegistry

    try:
        registry = RepairDecisionRegistry()
        decision = registry.create_decision(
            title=title,
            proposal_id=proposal_id,
            description=description,
            source=source,
            status=status,
            reason=reason,
            rationale=rationale,
            notes=notes,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(decision["decision_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(decision, indent=2, default=str))
    else:
        _render_repair_decision_rich(decision)


@cli.command("repair-decisions")
@click.option("--status", default="", help="Filter by status")
@click.option("--reason", default="", help="Filter by reason")
@click.option("--source", default="", help="Filter by source")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_decisions_cmd(
    status: str,
    reason: str,
    source: str,
    json_output: bool,
) -> None:
    """List repair decisions."""
    from axiom_core.repair_decision_registry import RepairDecisionRegistry

    try:
        registry = RepairDecisionRegistry()
        decisions = registry.list_decisions(
            status=status, reason=reason, source=source,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(decisions, indent=2, default=str))
    else:
        if not decisions:
            console.print("[dim]No repair decisions found.[/dim]")
            return
        console.print(f"\n[bold]Repair Decisions ({len(decisions)})[/bold]\n")
        for d in decisions:
            reason_str = d.get("reason", "other").upper()
            console.print(
                f"  [{d.get('status', '')}] {d.get('decision_id', '')[:12]}… "
                f"— [{reason_str}] {d.get('title', '')}",
            )


@cli.command("repair-decision-show")
@click.argument("decision_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_decision_show_cmd(
    decision_id: str,
    json_output: bool,
) -> None:
    """Show details of a repair decision."""
    from axiom_core.repair_decision_registry import RepairDecisionRegistry

    try:
        registry = RepairDecisionRegistry()
        decision = registry.get_decision(decision_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if decision is None:
        msg = {"error": f"Repair decision not found: {decision_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Repair decision not found: {decision_id}",
            )
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(decision, indent=2, default=str))
    else:
        _render_repair_decision_rich(decision)


@cli.command("repair-decision-export")
@click.argument("decision_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def repair_decision_export_cmd(
    decision_id: str,
    json_output: bool,
) -> None:
    """Export a repair decision as markdown."""
    from axiom_core.repair_decision_registry import RepairDecisionRegistry

    try:
        registry = RepairDecisionRegistry()
        decision = registry.get_decision(decision_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if decision is None:
        msg = {"error": f"Repair decision not found: {decision_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Repair decision not found: {decision_id}",
            )
        raise SystemExit(2)

    md = registry.export_decision(decision_id)

    if json_output:
        click.echo(
            json.dumps(
                {"decision_id": decision_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_repair_decision_rich(decision: dict) -> None:
    """Rich text rendering for a repair decision."""
    status = decision.get("status", "").upper()
    reason_str = decision.get("reason", "").upper()
    console.print(f"\n[bold]Repair Decision ({status})[/bold]\n")
    console.print(f"  Decision ID:   {decision.get('decision_id', '')}")
    console.print(f"  Title:         {decision.get('title', '')}")
    console.print(f"  Reason:        {reason_str}")
    console.print(f"  Source:        {decision.get('source', '')}")
    console.print(f"  Status:        {decision.get('status', '')}")
    if decision.get("proposal_id"):
        console.print(f"  Proposal ID:   {decision['proposal_id']}")
    if decision.get("rationale"):
        console.print(f"  Rationale:     {decision['rationale']}")
    if decision.get("description"):
        console.print(f"  Description:   {decision['description']}")
    if decision.get("notes"):
        console.print(f"  Notes:         {decision['notes']}")


# ---------------------------------------------------------------------------
# Conflict Resolution Framework CLI
# ---------------------------------------------------------------------------


@cli.command("conflict-create")
@click.option("--title", required=True, help="Conflict title")
@click.option("--description", default="", help="Conflict description")
@click.option("--conflict-type", default="", help="Type (proposal_conflict/decision_conflict/assertion_conflict/validation_conflict/review_finding_conflict/escalation_conflict/other)")
@click.option("--severity", default="", help="Severity (none/info/warning/blocker/human_required)")
@click.option("--source", default="", help="Source (repair_decision/repair_proposal/escalation/assertion/review_finding/validation/other)")
@click.option("--left-ref", default="", help="Left reference ID")
@click.option("--right-ref", default="", help="Right reference ID")
@click.option("--rationale", default="", help="Rationale")
@click.option("--recommendation", default="", help="Recommendation")
@click.option("--json-output", is_flag=True, help="Output JSON")
def conflict_create_cmd(
    title: str,
    description: str,
    conflict_type: str,
    severity: str,
    source: str,
    left_ref: str,
    right_ref: str,
    rationale: str,
    recommendation: str,
    json_output: bool,
) -> None:
    """Create a new conflict."""
    from axiom_core.conflict_registry import ConflictRegistry

    try:
        registry = ConflictRegistry()
        conflict = registry.create_conflict(
            title=title,
            description=description,
            conflict_type=conflict_type,
            severity=severity,
            source=source,
            left_ref=left_ref,
            right_ref=right_ref,
            rationale=rationale,
            recommendation=recommendation,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(conflict["conflict_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(conflict, indent=2, default=str))
    else:
        _render_conflict_rich(conflict)


@cli.command("conflicts")
@click.option("--status", default="", help="Filter by status")
@click.option("--severity", default="", help="Filter by severity")
@click.option("--conflict-type", default="", help="Filter by conflict type")
@click.option("--source", default="", help="Filter by source")
@click.option("--json-output", is_flag=True, help="Output JSON")
def conflicts_cmd(
    status: str,
    severity: str,
    conflict_type: str,
    source: str,
    json_output: bool,
) -> None:
    """List conflicts."""
    from axiom_core.conflict_registry import ConflictRegistry

    try:
        registry = ConflictRegistry()
        conflicts = registry.list_conflicts(
            status=status, severity=severity,
            conflict_type=conflict_type, source=source,
        )
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(conflicts, indent=2, default=str))
    else:
        if not conflicts:
            console.print("[dim]No conflicts found.[/dim]")
            return
        console.print(f"\n[bold]Conflicts ({len(conflicts)})[/bold]\n")
        for c in conflicts:
            sev = c.get("severity", "info").upper()
            console.print(
                f"  [{c.get('status', '')}] {c.get('conflict_id', '')[:12]}… "
                f"— [{sev}] {c.get('title', '')}",
            )


@cli.command("conflict-show")
@click.argument("conflict_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def conflict_show_cmd(
    conflict_id: str,
    json_output: bool,
) -> None:
    """Show details of a conflict."""
    from axiom_core.conflict_registry import ConflictRegistry

    try:
        registry = ConflictRegistry()
        conflict = registry.get_conflict(conflict_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if conflict is None:
        msg = {"error": f"Conflict not found: {conflict_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Conflict not found: {conflict_id}",
            )
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(conflict, indent=2, default=str))
    else:
        _render_conflict_rich(conflict)


@cli.command("conflict-export")
@click.argument("conflict_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def conflict_export_cmd(
    conflict_id: str,
    json_output: bool,
) -> None:
    """Export a conflict as markdown."""
    from axiom_core.conflict_registry import ConflictRegistry

    try:
        registry = ConflictRegistry()
        conflict = registry.get_conflict(conflict_id)
    except ValueError as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        msg = {"error": str(exc)}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if conflict is None:
        msg = {"error": f"Conflict not found: {conflict_id}"}
        if json_output:
            click.echo(json.dumps(msg, indent=2))
        else:
            console.print(
                f"[red]Error:[/red] Conflict not found: {conflict_id}",
            )
        raise SystemExit(2)

    md = registry.export_conflict(conflict_id)

    if json_output:
        click.echo(
            json.dumps(
                {"conflict_id": conflict_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_conflict_rich(conflict: dict) -> None:
    """Rich text rendering for a conflict."""
    status = conflict.get("status", "").upper()
    sev = conflict.get("severity", "").upper()
    console.print(f"\n[bold]Conflict ({status})[/bold]\n")
    console.print(f"  Conflict ID:   {conflict.get('conflict_id', '')}")
    console.print(f"  Title:         {conflict.get('title', '')}")
    console.print(f"  Severity:      {sev}")
    console.print(f"  Type:          {conflict.get('conflict_type', '')}")
    console.print(f"  Source:        {conflict.get('source', '')}")
    console.print(f"  Status:        {conflict.get('status', '')}")
    if conflict.get("left_ref"):
        console.print(f"  Left Ref:      {conflict['left_ref']}")
    if conflict.get("right_ref"):
        console.print(f"  Right Ref:     {conflict['right_ref']}")
    if conflict.get("rationale"):
        console.print(f"  Rationale:     {conflict['rationale']}")
    if conflict.get("description"):
        console.print(f"  Description:   {conflict['description']}")
    if conflict.get("recommendation"):
        console.print(f"  Recommendation: {conflict['recommendation']}")
    if conflict.get("resolution_notes"):
        console.print(f"  Resolution:    {conflict['resolution_notes']}")


# ---------------------------------------------------------------------------
# Session State Machine CLI
# ---------------------------------------------------------------------------


@cli.command("session-state-create")
@click.option("--session-id", required=True, help="Session ID")
@click.option("--current-state", default="", help="Initial state (created/planning/executing/validating/repairing/reviewing/reporting/completed/failed)")
@click.option("--reason", default="", help="Reason")
@click.option("--source", default="", help="Source")
@click.option("--rationale", default="", help="Rationale")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_state_create_cmd(
    session_id: str,
    current_state: str,
    reason: str,
    source: str,
    rationale: str,
    json_output: bool,
) -> None:
    """Create a new session state."""
    from axiom_core.session_state_machine import SessionStateMachineRegistry

    try:
        registry = SessionStateMachineRegistry()
        state = registry.create_state(
            session_id=session_id,
            current_state=current_state,
            reason=reason,
            source=source,
            rationale=rationale,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(state["state_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(state, indent=2, default=str))
    else:
        _render_session_state_rich(state)


@cli.command("session-states")
@click.option("--session-id", default="", help="Filter by session ID")
@click.option("--current-state", default="", help="Filter by current state")
@click.option("--source", default="", help="Filter by source")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_states_cmd(
    session_id: str,
    current_state: str,
    source: str,
    json_output: bool,
) -> None:
    """List session states."""
    from axiom_core.session_state_machine import SessionStateMachineRegistry

    try:
        registry = SessionStateMachineRegistry()
        states = registry.list_states(
            session_id=session_id,
            current_state=current_state,
            source=source,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(states, indent=2, default=str))
    else:
        if not states:
            console.print("[dim]No session states found.[/dim]")
            return
        console.print(f"\n[bold]Session States ({len(states)})[/bold]\n")
        for s in states:
            console.print(
                f"  [{s.get('current_state', '').upper()}] "
                f"{s.get('state_id', '')[:12]}… — {s.get('session_id', '')}",
            )


@cli.command("session-state-show")
@click.argument("state_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_state_show_cmd(
    state_id: str,
    json_output: bool,
) -> None:
    """Show details of a session state."""
    from axiom_core.session_state_machine import SessionStateMachineRegistry

    try:
        registry = SessionStateMachineRegistry()
        state = registry.get_state(state_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if state is None:
        if json_output:
            click.echo(json.dumps({"error": f"Session state not found: {state_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session state not found: {state_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(state, indent=2, default=str))
    else:
        _render_session_state_rich(state)


@cli.command("session-state-transition")
@click.argument("state_id")
@click.option("--to-state", required=True, help="Target state")
@click.option("--reason", default="", help="Reason")
@click.option("--source", default="", help="Source")
@click.option("--rationale", default="", help="Rationale")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_state_transition_cmd(
    state_id: str,
    to_state: str,
    reason: str,
    source: str,
    rationale: str,
    json_output: bool,
) -> None:
    """Transition a session state."""
    from axiom_core.session_state_machine import SessionStateMachineRegistry

    try:
        registry = SessionStateMachineRegistry()
        transition = registry.transition_state(
            state_id=state_id,
            to_state=to_state,
            reason=reason,
            source=source,
            rationale=rationale,
        )
    except ValueError as exc:
        err_msg = str(exc)
        if json_output:
            click.echo(json.dumps({"error": err_msg}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        if "not found" in err_msg:
            raise SystemExit(2)
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(state_id)
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(transition, indent=2, default=str))
    else:
        console.print(f"\n[bold]Transition: {transition['from_state']} → {transition['to_state']}[/bold]\n")
        console.print(f"  Transition ID: {transition['transition_id']}")
        console.print(f"  Session ID:    {transition['session_id']}")
        console.print(f"  Reason:        {transition['reason']}")
        console.print(f"  Source:        {transition['source']}")
        if transition.get("rationale"):
            console.print(f"  Rationale:     {transition['rationale']}")


@cli.command("session-state-export")
@click.argument("state_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_state_export_cmd(
    state_id: str,
    json_output: bool,
) -> None:
    """Export a session state as markdown."""
    from axiom_core.session_state_machine import SessionStateMachineRegistry

    try:
        registry = SessionStateMachineRegistry()
        state = registry.get_state(state_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if state is None:
        if json_output:
            click.echo(json.dumps({"error": f"Session state not found: {state_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session state not found: {state_id}")
        raise SystemExit(2)

    md = registry.export_state(state_id)

    if json_output:
        click.echo(
            json.dumps(
                {"state_id": state_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_session_state_rich(state: dict) -> None:
    """Rich text rendering for a session state."""
    cur = state.get("current_state", "").upper()
    console.print(f"\n[bold]Session State ({cur})[/bold]\n")
    console.print(f"  State ID:      {state.get('state_id', '')}")
    console.print(f"  Session ID:    {state.get('session_id', '')}")
    console.print(f"  Current:       {state.get('current_state', '')}")
    if state.get("previous_state"):
        console.print(f"  Previous:      {state['previous_state']}")
    console.print(f"  Reason:        {state.get('reason', '')}")
    console.print(f"  Source:        {state.get('source', '')}")
    if state.get("rationale"):
        console.print(f"  Rationale:     {state['rationale']}")


# ---------------------------------------------------------------------------
# Session Task Graph CLI
# ---------------------------------------------------------------------------


@cli.command("session-task-create")
@click.option("--title", required=True, help="Task title")
@click.option("--parent-task-id", default="", help="Parent task ID")
@click.option("--description", default="", help="Description")
@click.option("--task-type", default="", help="Task type (implementation/validation/review/repair/reporting/other)")
@click.option("--status", default="", help="Status")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_task_create_cmd(
    title: str,
    parent_task_id: str,
    description: str,
    task_type: str,
    status: str,
    json_output: bool,
) -> None:
    """Create a new session task."""
    from axiom_core.session_task_graph import SessionTaskGraphRegistry

    try:
        registry = SessionTaskGraphRegistry()
        task = registry.create_task(
            title=title,
            parent_task_id=parent_task_id,
            description=description,
            task_type=task_type,
            status=status,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(task["task_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(task, indent=2, default=str))
    else:
        _render_session_task_rich(task)


@cli.command("session-tasks")
@click.option("--task-type", default="", help="Filter by task type")
@click.option("--status", default="", help="Filter by status")
@click.option("--parent-task-id", default="", help="Filter by parent task ID")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_tasks_cmd(
    task_type: str,
    status: str,
    parent_task_id: str,
    json_output: bool,
) -> None:
    """List session tasks."""
    from axiom_core.session_task_graph import SessionTaskGraphRegistry

    try:
        registry = SessionTaskGraphRegistry()
        tasks = registry.list_tasks(
            task_type=task_type,
            status=status,
            parent_task_id=parent_task_id,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(tasks, indent=2, default=str))
    else:
        if not tasks:
            console.print("[dim]No session tasks found.[/dim]")
            return
        console.print(f"\n[bold]Session Tasks ({len(tasks)})[/bold]\n")
        for t in tasks:
            console.print(
                f"  [{t.get('status', '').upper()}] "
                f"{t.get('task_id', '')[:12]}… — {t.get('title', '')}",
            )


@cli.command("session-task-show")
@click.argument("task_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_task_show_cmd(
    task_id: str,
    json_output: bool,
) -> None:
    """Show details of a session task."""
    from axiom_core.session_task_graph import SessionTaskGraphRegistry

    try:
        registry = SessionTaskGraphRegistry()
        task = registry.get_task(task_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if task is None:
        if json_output:
            click.echo(json.dumps({"error": f"Session task not found: {task_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session task not found: {task_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(task, indent=2, default=str))
    else:
        _render_session_task_rich(task)


@cli.command("session-task-export")
@click.argument("task_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_task_export_cmd(
    task_id: str,
    json_output: bool,
) -> None:
    """Export a session task as markdown."""
    from axiom_core.session_task_graph import SessionTaskGraphRegistry

    try:
        registry = SessionTaskGraphRegistry()
        task = registry.get_task(task_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if task is None:
        if json_output:
            click.echo(json.dumps({"error": f"Session task not found: {task_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Session task not found: {task_id}")
        raise SystemExit(2)

    md = registry.export_task(task_id)

    if json_output:
        click.echo(
            json.dumps(
                {"task_id": task_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_session_task_rich(task: dict) -> None:
    """Rich text rendering for a session task."""
    status = task.get("status", "").upper()
    console.print(f"\n[bold]Session Task ({status})[/bold]\n")
    console.print(f"  Task ID:     {task.get('task_id', '')}")
    console.print(f"  Title:       {task.get('title', '')}")
    console.print(f"  Type:        {task.get('task_type', '')}")
    console.print(f"  Status:      {task.get('status', '')}")
    if task.get("parent_task_id"):
        console.print(f"  Parent:      {task['parent_task_id']}")
    if task.get("description"):
        console.print(f"  Description: {task['description']}")


# ---------------------------------------------------------------------------
# Live Coding Trial CLI
# ---------------------------------------------------------------------------


@cli.command("live-coding-trial")
@click.option("--code-file", default="src/axiom_core/text_utils.py", help="Code file to validate")
@click.option("--test-file", default="tests/test_text_utils.py", help="Test file to run")
@click.option("--function-name", default="safe_slug", help="Function being tested")
@click.option("--description", default="", help="Trial description")
@click.option("--json-output", is_flag=True, help="Output JSON")
def live_coding_trial_cmd(
    code_file: str,
    test_file: str,
    function_name: str,
    description: str,
    json_output: bool,
) -> None:
    """Run a minimal live coding trial."""
    from axiom_core.live_coding_trial import LiveCodingTrialRunner

    try:
        runner = LiveCodingTrialRunner()
        trial = runner.run_trial(
            code_file=code_file,
            test_file=test_file,
            function_name=function_name,
            description=description,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(trial, indent=2, default=str))
    else:
        status = "PASSED" if trial["all_passed"] else "FAILED"
        console.print(f"\n[bold]Live Coding Trial ({status})[/bold]\n")
        console.print(f"  Trial ID:  {trial['trial_id']}")
        console.print(f"  Function:  {trial['function_name']}")
        console.print(f"  Code:      {trial['code_file']}")
        console.print(f"  Tests:     {trial['test_file']}")
        console.print(f"  Status:    {status}")
        for vr in trial.get("validation_results", []):
            vr_status = "PASS" if vr["exit_code"] == 0 else "FAIL"
            console.print(f"  {vr['label']}: {vr_status}")
        if trial["escalation_needed"]:
            console.print("  [red]Escalation needed[/red]")
        else:
            console.print("  No escalation or repair needed")


# ---------------------------------------------------------------------------
# Parser Coding Trial CLI
# ---------------------------------------------------------------------------


@cli.command("parser-coding-trial")
@click.option("--code-file", default="src/axiom_core/text_utils.py", help="Code file to validate")
@click.option("--test-file", default="tests/test_text_utils.py", help="Test file to run")
@click.option("--function-name", default="parse_key_value_lines", help="Function being tested")
@click.option("--description", default="", help="Trial description")
@click.option("--json-output", is_flag=True, help="Output JSON")
def parser_coding_trial_cmd(
    code_file: str,
    test_file: str,
    function_name: str,
    description: str,
    json_output: bool,
) -> None:
    """Run a minimal parser coding trial."""
    from axiom_core.parser_coding_trial import ParserCodingTrialRunner

    try:
        runner = ParserCodingTrialRunner()
        trial = runner.run_trial(
            code_file=code_file,
            test_file=test_file,
            function_name=function_name,
            description=description,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(trial, indent=2, default=str))
    else:
        status = "PASSED" if trial["all_passed"] else "FAILED"
        console.print(f"\n[bold]Parser Coding Trial ({status})[/bold]\n")
        console.print(f"  Trial ID:  {trial['trial_id']}")
        console.print(f"  Function:  {trial['function_name']}")
        console.print(f"  Code:      {trial['code_file']}")
        console.print(f"  Tests:     {trial['test_file']}")
        console.print(f"  Status:    {status}")
        for vr in trial.get("validation_results", []):
            vr_status = "PASS" if vr["exit_code"] == 0 else "FAIL"
            console.print(f"  {vr['label']}: {vr_status}")
        if trial["escalation_needed"]:
            console.print("  [red]Escalation needed[/red]")
        else:
            console.print("  No escalation or repair needed")


# ---------------------------------------------------------------------------
# Structured Configuration CLI
# ---------------------------------------------------------------------------


@cli.command("config-load")
@click.option("--text", default="", help="Key=value text to load")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--file-name", default="", help="Logical file name for evidence")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_load_cmd(
    text: str,
    file_path: str,
    file_name: str,
    json_output: bool,
) -> None:
    """Load and validate a key=value configuration."""
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
            if not file_name:
                file_name = file_path
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        registry = ConfigurationRegistry()
        config = registry.load_config(text=text, file_name=file_name)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        registry.write_evidence(config["config_id"])
    except Exception as exc:
        _logger.warning("Evidence write failed: %s", exc)

    if json_output:
        click.echo(json.dumps(config, indent=2, default=str))
    else:
        _render_config_rich(config)


@cli.command("config-show")
@click.argument("config_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_show_cmd(
    config_id: str,
    json_output: bool,
) -> None:
    """Show a configuration by ID."""
    from axiom_core.configuration_registry import ConfigurationRegistry

    try:
        registry = ConfigurationRegistry()
        config = registry.get_config(config_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if config is None:
        if json_output:
            click.echo(json.dumps({"error": f"Configuration not found: {config_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Configuration not found: {config_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(config, indent=2, default=str))
    else:
        _render_config_rich(config)


@cli.command("config-export")
@click.argument("config_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_export_cmd(
    config_id: str,
    json_output: bool,
) -> None:
    """Export a configuration as markdown."""
    from axiom_core.configuration_registry import ConfigurationRegistry

    try:
        registry = ConfigurationRegistry()
        config = registry.get_config(config_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if config is None:
        if json_output:
            click.echo(json.dumps({"error": f"Configuration not found: {config_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Configuration not found: {config_id}")
        raise SystemExit(2)

    md = registry.export_config(config_id)

    if json_output:
        click.echo(
            json.dumps(
                {"config_id": config_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_config_rich(config: dict) -> None:
    """Rich text rendering for a configuration."""
    validation = config.get("validation", {})
    valid = validation.get("valid", True)
    status = "VALID" if valid else "INVALID"
    console.print(f"\n[bold]Configuration ({status})[/bold]\n")
    console.print(f"  Config ID:  {config.get('config_id', '')}")
    if config.get("file_name"):
        console.print(f"  File:       {config['file_name']}")
    console.print(f"  Entries:    {config.get('entry_count', 0)}")
    if validation.get("errors"):
        for err in validation["errors"]:
            console.print(f"  [red]ERROR:[/red] {err}")
    if validation.get("warnings"):
        for warn in validation["warnings"]:
            console.print(f"  [yellow]WARNING:[/yellow] {warn}")
    entries = config.get("entries", [])
    if entries:
        console.print("  Entries:")
        for e in entries:
            console.print(f"    {e['key']} = {e['value']}")


# ---------------------------------------------------------------------------
# Configuration Validation CLI
# ---------------------------------------------------------------------------


@cli.command("config-validate")
@click.option("--text", default="", help="Key=value text to validate")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--require-keys", default="", help="Comma-separated required keys")
@click.option("--non-empty-keys", default="", help="Comma-separated non-empty keys")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_validate_cmd(
    text: str,
    file_path: str,
    require_keys: str,
    non_empty_keys: str,
    json_output: bool,
) -> None:
    """Validate a key=value configuration against rules."""
    import re as re_mod

    from axiom_core.config_validation import (
        ConfigurationRule,
        ConfigurationRuleType,
        ConfigurationValidator,
    )
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=text, file_name=file_path or "")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    rules: list[ConfigurationRule] = []
    if require_keys:
        for key in require_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.REQUIRED_KEY,
                    )
                )
    if non_empty_keys:
        for key in non_empty_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.NON_EMPTY,
                    )
                )

    try:
        validator = ConfigurationValidator()
        report = validator.validate(config=config, rules=rules)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_validation_report_rich(report)


@cli.command("config-validation-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_validation_show_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Show a validation report by ID."""
    from axiom_core.config_validation import ConfigurationValidator

    try:
        validator = ConfigurationValidator()
        report = validator.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_validation_report_rich(report)


@cli.command("config-validation-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_validation_export_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Export a validation report as markdown."""
    from axiom_core.config_validation import ConfigurationValidator

    try:
        validator = ConfigurationValidator()
        report = validator.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = validator.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_validation_report_rich(report: dict) -> None:
    """Rich text rendering for a validation report."""
    valid = report.get("valid", True)
    status = "PASSED" if valid else "FAILED"
    console.print(f"\n[bold]Configuration Validation ({status})[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Config ID:    {report.get('config_id', '')}")
    console.print(f"  Rules:        {report.get('rules_checked', 0)}")
    console.print(f"  Errors:       {report.get('error_count', 0)}")
    console.print(f"  Warnings:     {report.get('warning_count', 0)}")
    violations = report.get("violations", [])
    if violations:
        console.print("  Violations:")
        for v in violations:
            sev = v.get("severity", "error").upper()
            console.print(f"    [{sev}] {v.get('key', '')}: {v.get('message', '')}")
    else:
        console.print("  No violations found")


# ---------------------------------------------------------------------------
# Configuration Repair Recommendation CLI
# ---------------------------------------------------------------------------


@cli.command("config-repair-recommend")
@click.option("--text", default="", help="Key=value text to validate and repair")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--require-keys", default="", help="Comma-separated required keys")
@click.option("--non-empty-keys", default="", help="Comma-separated non-empty keys")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_repair_recommend_cmd(
    text: str,
    file_path: str,
    require_keys: str,
    non_empty_keys: str,
    json_output: bool,
) -> None:
    """Generate repair recommendations for a key=value configuration."""
    import re as re_mod

    from axiom_core.config_repair import ConfigurationRepairEngine
    from axiom_core.config_validation import (
        ConfigurationRule,
        ConfigurationRuleType,
        ConfigurationValidator,
    )
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=text, file_name=file_path or "")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    rules: list[ConfigurationRule] = []
    if require_keys:
        for key in require_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.REQUIRED_KEY,
                    )
                )
    if non_empty_keys:
        for key in non_empty_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.NON_EMPTY,
                    )
                )

    try:
        validator = ConfigurationValidator()
        validation_report = validator.validate(config=config, rules=rules)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        engine = ConfigurationRepairEngine()
        repair_report = engine.recommend(
            validation_report=validation_report,
            config=config,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(repair_report, indent=2, default=str))
    else:
        _render_repair_report_rich(repair_report)


@cli.command("config-repair-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_repair_show_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Show a repair recommendation report by ID."""
    from axiom_core.config_repair import ConfigurationRepairEngine

    try:
        engine = ConfigurationRepairEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_repair_report_rich(report)


@cli.command("config-repair-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_repair_export_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Export a repair recommendation report as markdown."""
    from axiom_core.config_repair import ConfigurationRepairEngine

    try:
        engine = ConfigurationRepairEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_repair_report_rich(report: dict) -> None:
    """Rich text rendering for a repair report."""
    repairable = report.get("repairable_count", 0)
    unrepairable = report.get("unrepairable_count", 0)
    no_action = report.get("no_action_count", 0)
    status = "ALL REPAIRABLE" if unrepairable == 0 and repairable > 0 else (
        "NO ACTION NEEDED" if repairable == 0 and unrepairable == 0
        else "HAS UNREPAIRABLE"
    )
    console.print(f"\n[bold]Configuration Repair ({status})[/bold]\n")
    console.print(f"  Report ID:      {report.get('report_id', '')}")
    console.print(f"  Config ID:      {report.get('config_id', '')}")
    console.print(f"  Validation ID:  {report.get('validation_report_id', '')}")
    console.print(f"  Repairable:     {repairable}")
    console.print(f"  Unrepairable:   {unrepairable}")
    console.print(f"  No action:      {no_action}")
    recommendations = report.get("recommendations", [])
    if recommendations:
        console.print("  Recommendations:")
        for rec in recommendations:
            action = rec.get("action", "no_action").upper()
            key = rec.get("key", "")
            rationale = rec.get("rationale", "")
            console.print(f"    [{action}] {key}: {rationale}")
    else:
        console.print("  No recommendations")


# ---------------------------------------------------------------------------
# Configuration Explanation CLI
# ---------------------------------------------------------------------------


@cli.command("config-explain")
@click.option("--text", default="", help="Key=value text to explain")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--require-keys", default="", help="Comma-separated required keys")
@click.option("--non-empty-keys", default="", help="Comma-separated non-empty keys")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_explain_cmd(
    text: str,
    file_path: str,
    require_keys: str,
    non_empty_keys: str,
    json_output: bool,
) -> None:
    """Generate explanations for configuration validation and repair."""
    import re as re_mod

    from axiom_core.config_explanation import ConfigurationExplanationEngine
    from axiom_core.config_repair import ConfigurationRepairEngine
    from axiom_core.config_validation import (
        ConfigurationRule,
        ConfigurationRuleType,
        ConfigurationValidator,
    )
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=text, file_name=file_path or "")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    rules: list[ConfigurationRule] = []
    if require_keys:
        for key in require_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.REQUIRED_KEY,
                    )
                )
    if non_empty_keys:
        for key in non_empty_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.NON_EMPTY,
                    )
                )

    try:
        validator = ConfigurationValidator()
        validation_report = validator.validate(config=config, rules=rules)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    repair_report = None
    if not validation_report.get("valid", True):
        try:
            repair_engine = ConfigurationRepairEngine()
            repair_report = repair_engine.recommend(
                validation_report=validation_report,
                config=config,
            )
        except Exception:
            pass

    try:
        engine = ConfigurationExplanationEngine()
        explanation_report = engine.explain(
            validation_report=validation_report,
            repair_report=repair_report,
            config=config,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(explanation_report, indent=2, default=str))
    else:
        _render_explanation_report_rich(explanation_report)


@cli.command("config-explanation-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_explanation_show_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Show an explanation report by ID."""
    from axiom_core.config_explanation import ConfigurationExplanationEngine

    try:
        engine = ConfigurationExplanationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_explanation_report_rich(report)


@cli.command("config-explanation-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_explanation_export_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Export an explanation report as markdown."""
    from axiom_core.config_explanation import ConfigurationExplanationEngine

    try:
        engine = ConfigurationExplanationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_explanation_report_rich(report: dict) -> None:
    """Rich text rendering for an explanation report."""
    explanation_count = report.get("explanation_count", 0)
    console.print("\n[bold]Configuration Explanation Report[/bold]\n")
    console.print(f"  Report ID:          {report.get('report_id', '')}")
    console.print(f"  Config ID:          {report.get('config_id', '')}")
    console.print(f"  Explanation count:  {explanation_count}")
    sections = report.get("sections", [])
    if sections:
        console.print("  Sections:")
        for sec in sections:
            console.print(f"    [{sec.get('title', '')}]")
            for line in sec.get("content", "").split("\n"):
                if line.strip():
                    console.print(f"      {line}")
    explanations = report.get("explanations", [])
    if explanations:
        console.print("  Explanations:")
        for exp in explanations:
            exp_type = exp.get("explanation_type", "").upper()
            summary = exp.get("summary", "")
            console.print(f"    [{exp_type}] {summary}")
    else:
        console.print("  No explanations generated")


@cli.command("config-execute")
@click.option("--text", default="", help="Key=value text to execute against")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--require-keys", default="", help="Comma-separated required keys")
@click.option("--non-empty-keys", default="", help="Comma-separated non-empty keys")
@click.option(
    "--actions",
    default="verify_only",
    help="Comma-separated actions: apply_valid_configuration, apply_repair_recommendations, verify_only, no_action",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_execute_cmd(
    text: str,
    file_path: str,
    require_keys: str,
    non_empty_keys: str,
    actions: str,
    json_output: bool,
) -> None:
    """Execute configuration actions with evidence generation."""
    import re as re_mod

    from axiom_core.config_execution import ConfigurationExecutionEngine
    from axiom_core.config_repair import ConfigurationRepairEngine
    from axiom_core.config_validation import (
        ConfigurationRule,
        ConfigurationRuleType,
        ConfigurationValidator,
    )
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=text, file_name=file_path or "")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    rules: list[ConfigurationRule] = []
    if require_keys:
        for key in require_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.REQUIRED_KEY,
                    )
                )
    if non_empty_keys:
        for key in non_empty_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.NON_EMPTY,
                    )
                )

    try:
        validator = ConfigurationValidator()
        validation_report = validator.validate(config=config, rules=rules)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    repair_report = None
    if not validation_report.get("valid", True):
        try:
            repair_engine = ConfigurationRepairEngine()
            repair_report = repair_engine.recommend(
                validation_report=validation_report,
                config=config,
            )
        except Exception:
            pass

    action_list = [a.strip() for a in actions.split(",") if a.strip()]

    try:
        engine = ConfigurationExecutionEngine()
        execution_report = engine.execute(
            config=config,
            validation_report=validation_report,
            repair_report=repair_report,
            actions=action_list,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(execution_report, indent=2, default=str))
    else:
        _render_execution_report_rich(execution_report)


@cli.command("config-execution-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_execution_show_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Show an execution report by ID."""
    from axiom_core.config_execution import ConfigurationExecutionEngine

    try:
        engine = ConfigurationExecutionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_report_rich(report)


@cli.command("config-execution-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_execution_export_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Export an execution report as markdown."""
    from axiom_core.config_execution import ConfigurationExecutionEngine

    try:
        engine = ConfigurationExecutionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_execution_report_rich(report: dict) -> None:
    """Rich text rendering for an execution report."""
    console.print("\n[bold]Configuration Execution Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Request ID: {report.get('request_id', '')}")
    console.print(f"  Status:     {report.get('status', '').upper()}")
    console.print(f"  Summary:    {report.get('execution_summary', '')}")

    result = report.get("result")
    if result:
        applied = result.get("applied_actions", [])
        failed = result.get("failed_actions", [])
        warnings = result.get("warnings", [])
        console.print(f"  Applied:    {', '.join(applied) or '(none)'}")
        console.print(f"  Failed:     {', '.join(failed) or '(none)'}")
        if warnings:
            console.print("  Warnings:")
            for w in warnings:
                console.print(f"    - {w}")

    request = report.get("request")
    if request:
        actions = request.get("requested_actions", [])
        console.print(f"  Actions:    {', '.join(actions)}")


@cli.command("config-rollback")
@click.option("--text", default="", help="Key=value text to rollback against")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--require-keys", default="", help="Comma-separated required keys")
@click.option("--non-empty-keys", default="", help="Comma-separated non-empty keys")
@click.option(
    "--actions",
    default="verify_only",
    help="Comma-separated rollback actions: revert_applied_configuration, revert_repair_application, verify_only, no_action",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_rollback_cmd(
    text: str,
    file_path: str,
    require_keys: str,
    non_empty_keys: str,
    actions: str,
    json_output: bool,
) -> None:
    """Roll back configuration execution actions."""
    import re as re_mod

    from axiom_core.config_execution import ConfigurationExecutionEngine
    from axiom_core.config_repair import ConfigurationRepairEngine
    from axiom_core.config_rollback import ConfigurationRollbackEngine
    from axiom_core.config_validation import (
        ConfigurationRule,
        ConfigurationRuleType,
        ConfigurationValidator,
    )
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=text, file_name=file_path or "")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    rules: list[ConfigurationRule] = []
    if require_keys:
        for key in require_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.REQUIRED_KEY,
                    )
                )
    if non_empty_keys:
        for key in non_empty_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.NON_EMPTY,
                    )
                )

    try:
        validator = ConfigurationValidator()
        validation_report = validator.validate(config=config, rules=rules)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    repair_report = None
    if not validation_report.get("valid", True):
        try:
            repair_engine = ConfigurationRepairEngine()
            repair_report = repair_engine.recommend(
                validation_report=validation_report,
                config=config,
            )
        except Exception:
            pass

    try:
        exec_engine = ConfigurationExecutionEngine()
        exec_actions = ["apply_valid_configuration"]
        if repair_report and repair_report.get("repairable_count", 0) > 0:
            exec_actions = ["apply_repair_recommendations"]
        execution_report = exec_engine.execute(
            config=config,
            validation_report=validation_report,
            repair_report=repair_report,
            actions=exec_actions,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    execution_result = execution_report.get("result")

    action_list = [a.strip() for a in actions.split(",") if a.strip()]

    try:
        engine = ConfigurationRollbackEngine()
        rollback_report = engine.rollback(
            execution_result=execution_result,
            actions=action_list,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(rollback_report, indent=2, default=str))
    else:
        _render_rollback_report_rich(rollback_report)


@cli.command("config-rollback-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_rollback_show_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Show a rollback report by ID."""
    from axiom_core.config_rollback import ConfigurationRollbackEngine

    try:
        engine = ConfigurationRollbackEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_rollback_report_rich(report)


@cli.command("config-rollback-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_rollback_export_cmd(
    report_id: str,
    json_output: bool,
) -> None:
    """Export a rollback report as markdown."""
    from axiom_core.config_rollback import ConfigurationRollbackEngine

    try:
        engine = ConfigurationRollbackEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_rollback_report_rich(report: dict) -> None:
    """Rich text rendering for a rollback report."""
    console.print("\n[bold]Configuration Rollback Report[/bold]\n")
    console.print(f"  Report ID:   {report.get('report_id', '')}")
    console.print(f"  Rollback ID: {report.get('rollback_id', '')}")
    console.print(f"  Status:      {report.get('status', '').upper()}")
    console.print(f"  Summary:     {report.get('rollback_summary', '')}")

    result = report.get("result")
    if result:
        reverted = result.get("reverted_actions", [])
        failed = result.get("failed_actions", [])
        warnings = result.get("warnings", [])
        console.print(f"  Reverted:    {', '.join(reverted) or '(none)'}")
        console.print(f"  Failed:      {', '.join(failed) or '(none)'}")
        if warnings:
            console.print("  Warnings:")
            for w in warnings:
                console.print(f"    - {w}")

    request = report.get("request")
    if request:
        actions = request.get("requested_actions", [])
        console.print(f"  Actions:     {', '.join(actions)}")


@cli.command("config-history-create")
@click.option("--text", default="", help="Key=value text")
@click.option("--file", "file_path", default="", help="Path to key=value file")
@click.option("--require-keys", default="", help="Comma-separated required keys")
@click.option("--non-empty-keys", default="", help="Comma-separated non-empty keys")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_history_create_cmd(
    text: str,
    file_path: str,
    require_keys: str,
    non_empty_keys: str,
    json_output: bool,
) -> None:
    """Create configuration change history from lifecycle events."""
    import re as re_mod

    from axiom_core.config_execution import ConfigurationExecutionEngine
    from axiom_core.config_history import ConfigurationChangeHistoryEngine
    from axiom_core.config_repair import ConfigurationRepairEngine
    from axiom_core.config_rollback import ConfigurationRollbackEngine
    from axiom_core.config_validation import (
        ConfigurationRule,
        ConfigurationRuleType,
        ConfigurationValidator,
    )
    from axiom_core.configuration_registry import ConfigurationRegistry

    if file_path and not text:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=text, file_name=file_path or "")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    rules: list[ConfigurationRule] = []
    if require_keys:
        for key in require_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.REQUIRED_KEY,
                    )
                )
    if non_empty_keys:
        for key in non_empty_keys.split(","):
            key = key.strip()
            if key:
                rules.append(
                    ConfigurationRule(
                        key_pattern=re_mod.escape(key),
                        rule_type=ConfigurationRuleType.NON_EMPTY,
                    )
                )

    try:
        validator = ConfigurationValidator()
        validation_report = validator.validate(config=config, rules=rules)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    repair_report = None
    if not validation_report.get("valid", True):
        try:
            repair_engine = ConfigurationRepairEngine()
            repair_report = repair_engine.recommend(
                validation_report=validation_report,
                config=config,
            )
        except Exception:
            pass

    try:
        exec_engine = ConfigurationExecutionEngine()
        exec_actions = ["apply_valid_configuration"]
        if repair_report and repair_report.get("repairable_count", 0) > 0:
            exec_actions = ["apply_repair_recommendations"]
        execution_report = exec_engine.execute(
            config=config,
            validation_report=validation_report,
            repair_report=repair_report,
            actions=exec_actions,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    execution_result = execution_report.get("result")

    rollback_result = None
    try:
        rb_engine = ConfigurationRollbackEngine()
        rb_report = rb_engine.rollback(
            execution_result=execution_result,
            actions=["verify_only"],
        )
        rollback_result = rb_report.get("result")
    except Exception:
        pass

    try:
        history_engine = ConfigurationChangeHistoryEngine()
        report = history_engine.create_history(
            config=config,
            validation_report=validation_report,
            repair_report=repair_report,
            execution_result=execution_result,
            rollback_result=rollback_result,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_history_report_rich(report)


@cli.command("config-history-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_history_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a configuration change history report."""
    from axiom_core.config_history import ConfigurationChangeHistoryEngine

    try:
        engine = ConfigurationChangeHistoryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_history_report_rich(report)


@cli.command("config-history-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_history_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a configuration change history report as markdown."""
    from axiom_core.config_history import ConfigurationChangeHistoryEngine

    try:
        engine = ConfigurationChangeHistoryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_history_report_rich(report: dict) -> None:
    """Rich text rendering for a history report."""
    console.print("\n[bold]Configuration Change History Report[/bold]\n")
    console.print(f"  Report ID:   {report.get('report_id', '')}")
    console.print(f"  Config ID:   {report.get('config_id', '')}")
    console.print(f"  Event Count: {report.get('event_count', 0)}")
    console.print(f"  Summary:     {report.get('timeline_summary', '')}")

    history = report.get("history")
    if history:
        events = history.get("events", [])
        if events:
            console.print("\n  [bold]Timeline:[/bold]")
            for i, event in enumerate(events, 1):
                console.print(
                    f"    {i}. [{event.get('event_type', '').upper()}] "
                    f"{event.get('summary', '')}"
                )


@cli.command("config-diff")
@click.option("--left-text", default="", help="Left config key=value text")
@click.option("--right-text", default="", help="Right config key=value text")
@click.option("--left-file", default="", help="Path to left config file")
@click.option("--right-file", default="", help="Path to right config file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_diff_cmd(
    left_text: str,
    right_text: str,
    left_file: str,
    right_file: str,
    json_output: bool,
) -> None:
    """Diff two configuration states."""
    from axiom_core.config_diff import ConfigurationDiffEngine
    from axiom_core.configuration_registry import ConfigurationRegistry

    if left_file and not left_text:
        try:
            left_text = Path(left_file).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    if right_file and not right_text:
        try:
            right_text = Path(right_file).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        left_config = config_reg.load_config(text=left_text, file_name=left_file or "left")
        right_config = config_reg.load_config(text=right_text, file_name=right_file or "right")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        engine = ConfigurationDiffEngine()
        report = engine.diff(left_config=left_config, right_config=right_config)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_diff_report_rich(report)


@cli.command("config-diff-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_diff_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a configuration diff report."""
    from axiom_core.config_diff import ConfigurationDiffEngine

    try:
        engine = ConfigurationDiffEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_diff_report_rich(report)


@cli.command("config-diff-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_diff_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a configuration diff report as markdown."""
    from axiom_core.config_diff import ConfigurationDiffEngine

    try:
        engine = ConfigurationDiffEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_diff_report_rich(report: dict) -> None:
    """Rich text rendering for a diff report."""
    console.print("\n[bold]Configuration Diff Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Summary:    {report.get('diff_summary', '')}")

    result = report.get("result")
    if result:
        console.print(f"  Added:      {result.get('added_count', 0)}")
        console.print(f"  Removed:    {result.get('removed_count', 0)}")
        console.print(f"  Changed:    {result.get('changed_count', 0)}")
        console.print(f"  Unchanged:  {result.get('unchanged_count', 0)}")

        entries = result.get("entries", [])
        if entries:
            console.print("\n  [bold]Entries:[/bold]")
            for entry in entries:
                dt = entry.get("diff_type", "").upper()
                console.print(f"    [{dt}] {entry.get('summary', '')}")


@cli.command("config-merge")
@click.option("--left-text", default="", help="Left config key=value text")
@click.option("--right-text", default="", help="Right config key=value text")
@click.option("--left-file", default="", help="Path to left config file")
@click.option("--right-file", default="", help="Path to right config file")
@click.option(
    "--strategy",
    default="left_wins",
    type=click.Choice(["left_wins", "right_wins", "keep_identical_only", "fail_on_conflict"]),
    help="Merge strategy",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_merge_cmd(
    left_text: str,
    right_text: str,
    left_file: str,
    right_file: str,
    strategy: str,
    json_output: bool,
) -> None:
    """Merge two configuration states."""
    from axiom_core.config_merge import ConfigurationMergeEngine
    from axiom_core.configuration_registry import ConfigurationRegistry

    if left_file and not left_text:
        try:
            left_text = Path(left_file).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    if right_file and not right_text:
        try:
            right_text = Path(right_file).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        left_config = config_reg.load_config(text=left_text, file_name=left_file or "left")
        right_config = config_reg.load_config(text=right_text, file_name=right_file or "right")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        engine = ConfigurationMergeEngine()
        report = engine.merge(
            left_config=left_config,
            right_config=right_config,
            strategy=strategy,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_merge_report_rich(report)


@cli.command("config-merge-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_merge_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a configuration merge report."""
    from axiom_core.config_merge import ConfigurationMergeEngine

    try:
        engine = ConfigurationMergeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_merge_report_rich(report)


@cli.command("config-merge-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_merge_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a configuration merge report as markdown."""
    from axiom_core.config_merge import ConfigurationMergeEngine

    try:
        engine = ConfigurationMergeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_merge_report_rich(report: dict) -> None:
    """Rich text rendering for a merge report."""
    console.print("\n[bold]Configuration Merge Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Summary:    {report.get('merge_summary', '')}")

    result = report.get("result")
    if result:
        console.print(f"  Status:     {result.get('status', '').upper()}")
        console.print(f"  Merged:     {result.get('merged_count', 0)}")
        console.print(f"  Conflicts:  {result.get('conflict_count', 0)}")

        entries = result.get("merged_entries", [])
        if entries:
            console.print("\n  [bold]Entries:[/bold]")
            for entry in entries:
                conflict = " [CONFLICT]" if entry.get("conflict_detected") else ""
                console.print(
                    f"    {entry.get('key', '')}: "
                    f"merged='{entry.get('merged_value', '')}'{conflict}"
                )


@cli.command("config-policy-check")
@click.option("--config-text", default="", help="Config key=value text")
@click.option("--config-file", default="", help="Path to config file")
@click.option("--policy-file", default="", help="Path to policy JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_policy_check_cmd(
    config_text: str,
    config_file: str,
    policy_file: str,
    json_output: bool,
) -> None:
    """Check a configuration against a policy."""
    from axiom_core.config_policy import ConfigurationPolicyEngine
    from axiom_core.configuration_registry import ConfigurationRegistry

    if config_file and not config_text:
        try:
            config_text = Path(config_file).read_text(encoding="utf-8")
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    policy_data: dict = {}
    if policy_file:
        try:
            policy_data = json.loads(Path(policy_file).read_text(encoding="utf-8"))
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        config_reg = ConfigurationRegistry()
        config = config_reg.load_config(text=config_text, file_name=config_file or "input")
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        engine = ConfigurationPolicyEngine()
        report = engine.check(config=config, policy=policy_data)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_policy_report_rich(report)


@cli.command("config-policy-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_policy_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a configuration policy report."""
    from axiom_core.config_policy import ConfigurationPolicyEngine

    try:
        engine = ConfigurationPolicyEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_policy_report_rich(report)


@cli.command("config-policy-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_policy_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a configuration policy report as markdown."""
    from axiom_core.config_policy import ConfigurationPolicyEngine

    try:
        engine = ConfigurationPolicyEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_policy_report_rich(report: dict) -> None:
    """Rich text rendering for a policy report."""
    console.print("\n[bold]Configuration Policy Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Summary:    {report.get('policy_summary', '')}")

    result = report.get("result")
    if result:
        status = "PASSED" if result.get("passed") else "FAILED"
        console.print(f"  Status:     {status}")
        console.print(f"  Blockers:   {result.get('blocker_count', 0)}")
        console.print(f"  Errors:     {result.get('error_count', 0)}")
        console.print(f"  Warnings:   {result.get('warning_count', 0)}")
        console.print(f"  Info:       {result.get('info_count', 0)}")

        violations = result.get("violations", [])
        if violations:
            console.print("\n  [bold]Violations:[/bold]")
            for v in violations:
                sev = v.get("severity", "").upper()
                console.print(f"    [{sev}] {v.get('message', '')}")


@cli.command("config-scenario-run")
@click.option("--scenario-file", default="", help="Path to scenario JSON file")
@click.option("--policy-passed", type=bool, default=None, help="Policy passed")
@click.option("--policy-blocker-count", type=int, default=0, help="Policy blocker count")
@click.option("--validation-passed", type=bool, default=None, help="Validation passed")
@click.option("--execution-status", default="", help="Execution status")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_scenario_run_cmd(
    scenario_file: str,
    policy_passed: bool | None,
    policy_blocker_count: int,
    validation_passed: bool | None,
    execution_status: str,
    json_output: bool,
) -> None:
    """Run a configuration scenario evaluation."""
    from axiom_core.config_scenario import ConfigurationScenarioEngine

    scenario_data: dict = {}
    if scenario_file:
        try:
            scenario_data = json.loads(Path(scenario_file).read_text(encoding="utf-8"))
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    policy_result: dict = {}
    if policy_passed is not None:
        policy_result["passed"] = policy_passed
    if policy_blocker_count:
        policy_result["blocker_count"] = policy_blocker_count

    validation_result: dict = {}
    if validation_passed is not None:
        validation_result["passed"] = validation_passed

    execution_result: dict = {}
    if execution_status:
        execution_result["status"] = execution_status

    try:
        engine = ConfigurationScenarioEngine()
        report = engine.run(
            scenario=scenario_data,
            policy_result=policy_result,
            validation_result=validation_result,
            execution_result=execution_result,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_scenario_report_rich(report)


@cli.command("config-scenario-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_scenario_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a configuration scenario report."""
    from axiom_core.config_scenario import ConfigurationScenarioEngine

    try:
        engine = ConfigurationScenarioEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_scenario_report_rich(report)


@cli.command("config-scenario-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_scenario_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a configuration scenario report as markdown."""
    from axiom_core.config_scenario import ConfigurationScenarioEngine

    try:
        engine = ConfigurationScenarioEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_scenario_report_rich(report: dict) -> None:
    """Rich text rendering for a scenario report."""
    console.print("\n[bold]Configuration Scenario Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Summary:    {report.get('scenario_summary', '')}")

    result = report.get("result")
    if result:
        status = "PASSED" if result.get("passed") else "FAILED"
        console.print(f"  Status:     {status}")
        console.print(f"  Blockers:   {result.get('blocker_count', 0)}")
        console.print(f"  Warnings:   {result.get('warning_count', 0)}")

        exp_results = result.get("expectation_results", [])
        if exp_results:
            console.print("\n  [bold]Expectations:[/bold]")
            for er in exp_results:
                met = "MET" if er.get("met") else "NOT MET"
                console.print(
                    f"    [{er.get('severity', '').upper()}] "
                    f"{er.get('expectation_type', '')}: {met}"
                )


@cli.command("config-batch-run")
@click.option("--scenarios-file", default="", help="Path to scenarios JSON file (list of scenario objects)")
@click.option("--execution-mode", default="run_all", type=click.Choice(["run_all", "stop_on_failure", "verify_only"]), help="Execution mode")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_batch_run_cmd(
    scenarios_file: str,
    execution_mode: str,
    json_output: bool,
) -> None:
    """Run a batch of configuration scenarios."""
    from axiom_core.config_batch_execution import ConfigurationBatchExecutionEngine

    scenarios: list = []
    scenario_ids: list = []
    if scenarios_file:
        try:
            data = json.loads(Path(scenarios_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                scenarios = data
                scenario_ids = [s.get("scenario_id", "") for s in data]
            elif isinstance(data, dict):
                scenarios = data.get("scenarios", [])
                scenario_ids = [s.get("scenario_id", "") for s in scenarios]
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = ConfigurationBatchExecutionEngine()
        report = engine.run(
            scenario_ids=scenario_ids,
            execution_mode=execution_mode,
            scenarios=scenarios,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_batch_report_rich(report)


@cli.command("config-batch-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_batch_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a batch execution report."""
    from axiom_core.config_batch_execution import ConfigurationBatchExecutionEngine

    try:
        engine = ConfigurationBatchExecutionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_batch_report_rich(report)


@cli.command("config-batch-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_batch_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a batch execution report as markdown."""
    from axiom_core.config_batch_execution import ConfigurationBatchExecutionEngine

    try:
        engine = ConfigurationBatchExecutionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_batch_report_rich(report: dict) -> None:
    """Rich text rendering for a batch execution report."""
    console.print("\n[bold]Configuration Batch Execution Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Summary:    {report.get('batch_summary', '')}")

    result = report.get("result")
    if result:
        console.print(f"  Total:      {result.get('total_count', 0)}")
        console.print(f"  Succeeded:  {result.get('succeeded_count', 0)}")
        console.print(f"  Failed:     {result.get('failed_count', 0)}")
        console.print(f"  Skipped:    {result.get('skipped_count', 0)}")
        console.print(f"  Warnings:   {result.get('warning_count', 0)}")

        items = result.get("items", [])
        if items:
            console.print("\n  [bold]Items:[/bold]")
            for item in items:
                status = item.get("status", "").upper()
                console.print(
                    f"    [{status}] scenario={item.get('scenario_id', '')}"
                )


@cli.command("config-dependency-create")
@click.option("--dependencies-file", default="", help="Path to dependencies JSON file")
@click.option("--known-ids", default="", help="Comma-separated known node IDs for validation")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_dependency_create_cmd(
    dependencies_file: str,
    known_ids: str,
    json_output: bool,
) -> None:
    """Create a configuration dependency graph."""
    from axiom_core.config_dependency import ConfigurationDependencyEngine

    dependencies: list = []
    if dependencies_file:
        try:
            data = json.loads(Path(dependencies_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                dependencies = data
            elif isinstance(data, dict):
                dependencies = data.get("dependencies", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    known_id_list: list[str] | None = None
    if known_ids.strip():
        known_id_list = [k.strip() for k in known_ids.split(",") if k.strip()]

    try:
        engine = ConfigurationDependencyEngine()
        report = engine.create(dependencies=dependencies, known_ids=known_id_list)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_dependency_report_rich(report)


@cli.command("config-dependencies")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_dependencies_cmd(json_output: bool) -> None:
    """List all dependency reports."""
    from axiom_core.config_dependency import ConfigurationDependencyEngine

    try:
        engine = ConfigurationDependencyEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(f"\n[bold]Dependency Reports ({len(reports)}):[/bold]\n")
        for r in reports:
            console.print(f"  {r.get('report_id', '')} — {r.get('dependency_summary', '')}")


@cli.command("config-dependency-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_dependency_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a dependency report."""
    from axiom_core.config_dependency import ConfigurationDependencyEngine

    try:
        engine = ConfigurationDependencyEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_dependency_report_rich(report)


@cli.command("config-dependency-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def config_dependency_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a dependency report as markdown."""
    from axiom_core.config_dependency import ConfigurationDependencyEngine

    try:
        engine = ConfigurationDependencyEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_dependency_report_rich(report: dict) -> None:
    """Rich text rendering for a dependency report."""
    console.print("\n[bold]Configuration Dependency Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Summary:    {report.get('dependency_summary', '')}")
    console.print(f"  Blocked:    {report.get('blocked_count', 0)}")
    console.print(f"  Invalid:    {report.get('invalid_count', 0)}")

    graph = report.get("graph")
    if graph:
        console.print(f"  Nodes:      {graph.get('node_count', 0)}")
        console.print(f"  Edges:      {graph.get('edge_count', 0)}")

        deps = graph.get("dependencies", [])
        if deps:
            console.print("\n  [bold]Dependencies:[/bold]")
            for dep in deps:
                status = dep.get("status", "").upper()
                dtype = dep.get("dependency_type", "")
                console.print(
                    f"    [{status}] {dep.get('source_id', '')} "
                    f"--{dtype}--> {dep.get('target_id', '')}"
                )


@cli.command("capability-create")
@click.option("--capabilities-file", default="", help="Path to capabilities JSON file")
@click.option("--known-dependency-ids", default="", help="Comma-separated known dependency IDs")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_create_cmd(
    capabilities_file: str,
    known_dependency_ids: str,
    json_output: bool,
) -> None:
    """Create a capability registry."""
    from axiom_core.capability_definition import CapabilityDefinitionEngine

    capabilities: list = []
    if capabilities_file:
        try:
            data = json.loads(Path(capabilities_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                capabilities = data
            elif isinstance(data, dict):
                capabilities = data.get("capabilities", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    known_ids_list: list[str] | None = None
    if known_dependency_ids.strip():
        known_ids_list = [
            k.strip() for k in known_dependency_ids.split(",") if k.strip()
        ]

    try:
        engine = CapabilityDefinitionEngine()
        report = engine.create(
            capabilities=capabilities, known_dependency_ids=known_ids_list
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_report_rich(report)


@cli.command("capabilities")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capabilities_cmd(json_output: bool) -> None:
    """List all capability reports."""
    from axiom_core.capability_definition import CapabilityDefinitionEngine

    try:
        engine = CapabilityDefinitionEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(f"\n[bold]Capability Reports ({len(reports)}):[/bold]\n")
        for r in reports:
            console.print(f"  {r.get('report_id', '')} — {r.get('summary', '')}")


@cli.command("capability-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability report."""
    from axiom_core.capability_definition import CapabilityDefinitionEngine

    try:
        engine = CapabilityDefinitionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_report_rich(report)


@cli.command("capability-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability report as markdown."""
    from axiom_core.capability_definition import CapabilityDefinitionEngine

    try:
        engine = CapabilityDefinitionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_report_rich(report: dict) -> None:
    """Rich text rendering for a capability report."""
    console.print("\n[bold]Capability Definition Report[/bold]\n")
    console.print(f"  Report ID:     {report.get('report_id', '')}")
    console.print(f"  Summary:       {report.get('summary', '')}")
    console.print(f"  Active:        {report.get('active_count', 0)}")
    console.print(f"  Disabled:      {report.get('disabled_count', 0)}")
    console.print(f"  Experimental:  {report.get('experimental_count', 0)}")
    console.print(f"  Deprecated:    {report.get('deprecated_count', 0)}")

    registry = report.get("registry")
    if registry:
        caps = registry.get("capabilities", [])
        if caps:
            console.print("\n  [bold]Capabilities:[/bold]")
            for cap in caps:
                status = cap.get("status", "").upper()
                ctype = cap.get("capability_type", "")
                console.print(
                    f"    [{status}] {cap.get('name', '')} (type: {ctype})"
                )


@cli.command("capability-input-create")
@click.option("--inputs-file", default="", help="Path to inputs JSON file")
@click.option("--capability-id", default="", help="Capability ID for inputs")
@click.option("--known-capability-ids", default="", help="Comma-separated known capability IDs")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_input_create_cmd(
    inputs_file: str,
    capability_id: str,
    known_capability_ids: str,
    json_output: bool,
) -> None:
    """Create capability inputs and validate them."""
    from axiom_core.capability_input import CapabilityInputEngine

    inputs: list = []
    if inputs_file:
        try:
            data = json.loads(Path(inputs_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                inputs = data
            elif isinstance(data, dict):
                inputs = data.get("inputs", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    known_ids_list: list[str] | None = None
    if known_capability_ids.strip():
        known_ids_list = [
            k.strip() for k in known_capability_ids.split(",") if k.strip()
        ]

    try:
        engine = CapabilityInputEngine()
        report = engine.create(
            capability_id=capability_id,
            inputs=inputs,
            known_capability_ids=known_ids_list,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_input_report_rich(report)


@cli.command("capability-inputs")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_inputs_cmd(json_output: bool) -> None:
    """List all capability input reports."""
    from axiom_core.capability_input import CapabilityInputEngine

    try:
        engine = CapabilityInputEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(f"\n[bold]Capability Input Reports ({len(reports)}):[/bold]\n")
        for r in reports:
            console.print(
                f"  {r.get('report_id', '')} — "
                f"cap={r.get('capability_id', '')} "
                f"valid={r.get('valid_count', 0)} invalid={r.get('invalid_count', 0)}"
            )


@cli.command("capability-input-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_input_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability input report."""
    from axiom_core.capability_input import CapabilityInputEngine

    try:
        engine = CapabilityInputEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_input_report_rich(report)


@cli.command("capability-input-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_input_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability input report as markdown."""
    from axiom_core.capability_input import CapabilityInputEngine

    try:
        engine = CapabilityInputEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_input_report_rich(report: dict) -> None:
    """Rich text rendering for a capability input report."""
    console.print("\n[bold]Capability Input Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Capability:   {report.get('capability_id', '')}")
    console.print(f"  Inputs:       {report.get('input_count', 0)}")
    console.print(f"  Valid:        {report.get('valid_count', 0)}")
    console.print(f"  Invalid:      {report.get('invalid_count', 0)}")
    console.print(f"  Missing:      {report.get('missing_count', 0)}")
    console.print(f"  Unsupported:  {report.get('unsupported_count', 0)}")

    inputs = report.get("inputs", [])
    if inputs:
        console.print("\n  [bold]Inputs:[/bold]")
        for inp in inputs:
            status = inp.get("status", "").upper()
            itype = inp.get("input_type", "")
            console.print(
                f"    [{status}] {inp.get('name', '')} (type: {itype})"
            )


@cli.command("capability-output-create")
@click.option("--outputs-file", default="", help="Path to outputs JSON file")
@click.option("--capability-id", default="", help="Capability ID for outputs")
@click.option("--known-capability-ids", default="", help="Comma-separated known capability IDs")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_output_create_cmd(
    outputs_file: str,
    capability_id: str,
    known_capability_ids: str,
    json_output: bool,
) -> None:
    """Create capability outputs and validate them."""
    from axiom_core.capability_output import CapabilityOutputEngine

    outputs: list = []
    if outputs_file:
        try:
            data = json.loads(Path(outputs_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                outputs = data
            elif isinstance(data, dict):
                outputs = data.get("outputs", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    known_ids_list: list[str] | None = None
    if known_capability_ids.strip():
        known_ids_list = [
            k.strip() for k in known_capability_ids.split(",") if k.strip()
        ]

    try:
        engine = CapabilityOutputEngine()
        report = engine.create(
            capability_id=capability_id,
            outputs=outputs,
            known_capability_ids=known_ids_list,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_output_report_rich(report)


@cli.command("capability-outputs")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_outputs_cmd(json_output: bool) -> None:
    """List all capability output reports."""
    from axiom_core.capability_output import CapabilityOutputEngine

    try:
        engine = CapabilityOutputEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(f"\n[bold]Capability Output Reports ({len(reports)}):[/bold]\n")
        for r in reports:
            console.print(
                f"  {r.get('report_id', '')} — "
                f"cap={r.get('capability_id', '')} "
                f"valid={r.get('valid_count', 0)} invalid={r.get('invalid_count', 0)}"
            )


@cli.command("capability-output-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_output_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability output report."""
    from axiom_core.capability_output import CapabilityOutputEngine

    try:
        engine = CapabilityOutputEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_output_report_rich(report)


@cli.command("capability-output-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_output_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability output report as markdown."""
    from axiom_core.capability_output import CapabilityOutputEngine

    try:
        engine = CapabilityOutputEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_output_report_rich(report: dict) -> None:
    """Rich text rendering for a capability output report."""
    console.print("\n[bold]Capability Output Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Capability:   {report.get('capability_id', '')}")
    console.print(f"  Outputs:      {report.get('output_count', 0)}")
    console.print(f"  Valid:        {report.get('valid_count', 0)}")
    console.print(f"  Invalid:      {report.get('invalid_count', 0)}")
    console.print(f"  Missing:      {report.get('missing_count', 0)}")
    console.print(f"  Unsupported:  {report.get('unsupported_count', 0)}")

    outputs = report.get("outputs", [])
    if outputs:
        console.print("\n  [bold]Outputs:[/bold]")
        for out in outputs:
            status = out.get("status", "").upper()
            otype = out.get("output_type", "")
            console.print(
                f"    [{status}] {out.get('name', '')} (type: {otype})"
            )


@cli.command("capability-report-create")
@click.option("--capability-id", default="", help="Capability ID")
@click.option("--execution-status", default="succeeded", help="Execution status")
@click.option("--started-at", default="", help="Execution start timestamp")
@click.option("--completed-at", default="", help="Execution completion timestamp")
@click.option("--duration-ms", default=0, type=int, help="Duration in milliseconds")
@click.option("--events-file", default="", help="Path to events JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_report_create_cmd(
    capability_id: str,
    execution_status: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    events_file: str,
    json_output: bool,
) -> None:
    """Create a capability execution report."""
    from axiom_core.capability_execution_report import CapabilityExecutionReportEngine

    events: list = []
    if events_file:
        try:
            data = json.loads(Path(events_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                events = data
            elif isinstance(data, dict):
                events = data.get("events", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilityExecutionReportEngine()
        report = engine.create(
            capability_id=capability_id,
            execution_status=execution_status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            events=events,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_execution_report_rich(report)


@cli.command("capability-reports")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_reports_cmd(json_output: bool) -> None:
    """List all capability execution reports."""
    from axiom_core.capability_execution_report import CapabilityExecutionReportEngine

    try:
        engine = CapabilityExecutionReportEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(f"\n[bold]Capability Execution Reports ({len(reports)}):[/bold]\n")
        for r in reports:
            console.print(
                f"  {r.get('report_id', '')} — "
                f"cap={r.get('capability_id', '')} "
                f"status={r.get('execution_status', '')} "
                f"duration={r.get('duration_ms', 0)}ms"
            )


@cli.command("capability-report-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_report_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability execution report."""
    from axiom_core.capability_execution_report import CapabilityExecutionReportEngine

    try:
        engine = CapabilityExecutionReportEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_execution_report_rich(report)


@cli.command("capability-report-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_report_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability execution report as markdown."""
    from axiom_core.capability_execution_report import CapabilityExecutionReportEngine

    try:
        engine = CapabilityExecutionReportEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_execution_report_rich(report: dict) -> None:
    """Rich text rendering for a capability execution report."""
    console.print("\n[bold]Capability Execution Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Capability: {report.get('capability_id', '')}")
    console.print(f"  Status:     {report.get('execution_status', '')}")
    console.print(f"  Duration:   {report.get('duration_ms', 0)}ms")
    console.print(f"  Started:    {report.get('started_at', '')}")
    console.print(f"  Completed:  {report.get('completed_at', '')}")

    summary = report.get("summary", {})
    if summary:
        console.print("\n  [bold]Summary:[/bold]")
        console.print(f"    Events:   {summary.get('event_count', 0)}")
        console.print(f"    Warnings: {summary.get('warning_count', 0)}")
        console.print(f"    Errors:   {summary.get('error_count', 0)}")

    events = report.get("events", [])
    if events:
        console.print("\n  [bold]Events:[/bold]")
        for ev in events:
            etype = ev.get("event_type", "").upper()
            msg = ev.get("message", "")
            console.print(f"    [{etype}] {msg}")


@cli.command("capability-failure-create")
@click.option("--failures-file", default="", help="Path to failures JSON file")
@click.option("--report-id", default="", help="Execution report ID to associate")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_failure_create_cmd(
    failures_file: str,
    report_id: str,
    json_output: bool,
) -> None:
    """Create a capability failure report."""
    from axiom_core.capability_failure import CapabilityFailureEngine

    failures: list = []
    if failures_file:
        try:
            data = json.loads(Path(failures_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                failures = data
            elif isinstance(data, dict):
                failures = data.get("failures", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilityFailureEngine()
        result = engine.create(failures=failures, report_id=report_id)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_failure_report_rich(result)


@cli.command("capability-failures")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_failures_cmd(json_output: bool) -> None:
    """List all capability failure reports."""
    from axiom_core.capability_failure import CapabilityFailureEngine

    try:
        engine = CapabilityFailureEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(f"\n[bold]Capability Failure Reports ({len(reports)}):[/bold]\n")
        for r in reports:
            console.print(
                f"  {r.get('report_id', '')} — "
                f"failures={r.get('failure_count', 0)} "
                f"blockers={r.get('blocker_count', 0)} "
                f"errors={r.get('error_count', 0)}"
            )


@cli.command("capability-failure-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_failure_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability failure report."""
    from axiom_core.capability_failure import CapabilityFailureEngine

    try:
        engine = CapabilityFailureEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_failure_report_rich(report)


@cli.command("capability-failure-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_failure_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability failure report as markdown."""
    from axiom_core.capability_failure import CapabilityFailureEngine

    try:
        engine = CapabilityFailureEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(json.dumps({"error": f"Report not found: {report_id}"}, indent=2))
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_failure_report_rich(report: dict) -> None:
    """Rich text rendering for a capability failure report."""
    console.print("\n[bold]Capability Failure Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Failures:   {report.get('failure_count', 0)}")
    console.print(f"  Blockers:   {report.get('blocker_count', 0)}")
    console.print(f"  Errors:     {report.get('error_count', 0)}")
    console.print(f"  Warnings:   {report.get('warning_count', 0)}")
    console.print(f"  Info:       {report.get('info_count', 0)}")

    failures = report.get("failures", [])
    if failures:
        console.print("\n  [bold]Failures:[/bold]")
        for f in failures:
            sev = f.get("severity", "").upper()
            ftype = f.get("failure_type", "")
            msg = f.get("message", "")
            console.print(f"    [{sev}] ({ftype}) {msg}")


@cli.command("capability-repair-outcome-create")
@click.option("--outcomes-file", default="", help="Path to outcomes JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_repair_outcome_create_cmd(
    outcomes_file: str,
    json_output: bool,
) -> None:
    """Create a capability repair outcome report."""
    from axiom_core.capability_repair_outcome import CapabilityRepairOutcomeEngine

    outcomes: list = []
    if outcomes_file:
        try:
            data = json.loads(Path(outcomes_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                outcomes = data
            elif isinstance(data, dict):
                outcomes = data.get("outcomes", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilityRepairOutcomeEngine()
        result = engine.create(outcomes=outcomes)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_repair_outcome_report_rich(result)


@cli.command("capability-repair-outcomes")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_repair_outcomes_cmd(json_output: bool) -> None:
    """List all capability repair outcome reports."""
    from axiom_core.capability_repair_outcome import CapabilityRepairOutcomeEngine

    try:
        engine = CapabilityRepairOutcomeEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(
            f"\n[bold]Capability Repair Outcome Reports ({len(reports)}):[/bold]\n"
        )
        for r in reports:
            console.print(
                f"  {r.get('report_id', '')} — "
                f"outcomes={r.get('outcome_count', 0)} "
                f"recoveries={r.get('recovery_count', 0)} "
                f"regressions={r.get('regression_count', 0)}"
            )


@cli.command("capability-repair-outcome-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_repair_outcome_show_cmd(
    report_id: str, json_output: bool
) -> None:
    """Show a capability repair outcome report."""
    from axiom_core.capability_repair_outcome import CapabilityRepairOutcomeEngine

    try:
        engine = CapabilityRepairOutcomeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_repair_outcome_report_rich(report)


@cli.command("capability-repair-outcome-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_repair_outcome_export_cmd(
    report_id: str, json_output: bool
) -> None:
    """Export a capability repair outcome report as markdown."""
    from axiom_core.capability_repair_outcome import CapabilityRepairOutcomeEngine

    try:
        engine = CapabilityRepairOutcomeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_repair_outcome_report_rich(report: dict) -> None:
    """Rich text rendering for a capability repair outcome report."""
    console.print("\n[bold]Capability Repair Outcome Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Outcomes:     {report.get('outcome_count', 0)}")
    console.print(f"  Recoveries:   {report.get('recovery_count', 0)}")
    console.print(f"  Regressions:  {report.get('regression_count', 0)}")

    outcomes = report.get("outcomes", [])
    if outcomes:
        console.print("\n  [bold]Outcomes:[/bold]")
        for o in outcomes:
            otype = o.get("outcome_type", "").upper()
            status = o.get("status", "").upper()
            summary = o.get("summary", "")
            console.print(f"    [{otype}] ({status}) {summary}")


@cli.command("capability-confidence-create")
@click.option("--capability-id", default="", help="Capability ID")
@click.option("--execution-count", default=0, type=int, help="Total executions")
@click.option("--success-count", default=0, type=int, help="Successful executions")
@click.option("--failure-count", default=0, type=int, help="Failed executions")
@click.option("--repair-count", default=0, type=int, help="Repair attempts")
@click.option("--recovery-count", default=0, type=int, help="Successful recoveries")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_confidence_create_cmd(
    capability_id: str,
    execution_count: int,
    success_count: int,
    failure_count: int,
    repair_count: int,
    recovery_count: int,
    json_output: bool,
) -> None:
    """Create a capability confidence report."""
    from axiom_core.capability_confidence import CapabilityConfidenceEngine

    try:
        engine = CapabilityConfidenceEngine()
        result = engine.create(
            capability_id=capability_id,
            execution_count=execution_count,
            success_count=success_count,
            failure_count=failure_count,
            repair_count=repair_count,
            recovery_count=recovery_count,
        )
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_confidence_report_rich(result)


@cli.command("capability-confidences")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_confidences_cmd(json_output: bool) -> None:
    """List all capability confidence reports."""
    from axiom_core.capability_confidence import CapabilityConfidenceEngine

    try:
        engine = CapabilityConfidenceEngine()
        reports = engine.list_reports()
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
    else:
        console.print(
            f"\n[bold]Capability Confidence Reports ({len(reports)}):[/bold]\n"
        )
        for r in reports:
            console.print(
                f"  {r.get('report_id', '')} — "
                f"capability={r.get('capability_id', '')} "
                f"score={r.get('score', 0.0)} "
                f"level={r.get('confidence_level', '')}"
            )


@cli.command("capability-confidence-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_confidence_show_cmd(
    report_id: str, json_output: bool
) -> None:
    """Show a capability confidence report."""
    from axiom_core.capability_confidence import CapabilityConfidenceEngine

    try:
        engine = CapabilityConfidenceEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_confidence_report_rich(report)


@cli.command("capability-confidence-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_confidence_export_cmd(
    report_id: str, json_output: bool
) -> None:
    """Export a capability confidence report as markdown."""
    from axiom_core.capability_confidence import CapabilityConfidenceEngine

    try:
        engine = CapabilityConfidenceEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_confidence_report_rich(report: dict) -> None:
    """Rich text rendering for a capability confidence report."""
    console.print("\n[bold]Capability Confidence Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Capability:   {report.get('capability_id', '')}")
    console.print(f"  Score:        {report.get('score', 0.0)}")
    console.print(f"  Level:        {report.get('confidence_level', '')}")

    confidence = report.get("confidence", {})
    factors = confidence.get("factors", {})
    if factors:
        console.print("\n  [bold]Factors:[/bold]")
        console.print(f"    Executions: {factors.get('execution_count', 0)}")
        console.print(f"    Successes:  {factors.get('success_count', 0)}")
        console.print(f"    Failures:   {factors.get('failure_count', 0)}")
        console.print(f"    Repairs:    {factors.get('repair_count', 0)}")
        console.print(f"    Recoveries: {factors.get('recovery_count', 0)}")


@cli.command("capability-history-create")
@click.option("--capability-id", default="", help="Capability ID")
@click.option("--events-file", default="", help="Path to events JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_history_create_cmd(
    capability_id: str,
    events_file: str,
    json_output: bool,
) -> None:
    """Create a capability history report."""
    from axiom_core.capability_history import CapabilityHistoryEngine

    events: list = []
    if events_file:
        try:
            data = json.loads(Path(events_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                events = data
            elif isinstance(data, dict):
                events = data.get("events", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilityHistoryEngine()
        result = engine.create(capability_id=capability_id, events=events)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_history_report_rich(result)


@cli.command("capability-history-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_history_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability history report."""
    from axiom_core.capability_history import CapabilityHistoryEngine

    try:
        engine = CapabilityHistoryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_history_report_rich(report)


@cli.command("capability-history-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_history_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability history report as markdown."""
    from axiom_core.capability_history import CapabilityHistoryEngine

    try:
        engine = CapabilityHistoryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_history_report_rich(report: dict) -> None:
    """Rich text rendering for a capability history report."""
    console.print("\n[bold]Capability History Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Capability:   {report.get('capability_id', '')}")
    console.print(f"  Event Count:  {report.get('event_count', 0)}")

    history = report.get("history", {})
    events = history.get("events", [])
    if events:
        console.print("\n  [bold]Timeline:[/bold]")
        for e in events:
            etype = e.get("event_type", "").upper()
            source = e.get("source_id", "")
            esummary = e.get("summary", "")
            created = e.get("created_at", "")
            source_part = f" <- {source}" if source else ""
            console.print(f"    [{created}] {etype}{source_part}: {esummary}")


@cli.command("capability-skill-create")
@click.option("--capability-id", default="", help="Capability ID")
@click.option("--skills-file", default="", help="Path to skills JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_skill_create_cmd(
    capability_id: str,
    skills_file: str,
    json_output: bool,
) -> None:
    """Create a capability skill report."""
    from axiom_core.capability_skill import CapabilitySkillEngine

    skills: list = []
    if skills_file:
        try:
            data = json.loads(Path(skills_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                skills = data
            elif isinstance(data, dict):
                skills = data.get("skills", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilitySkillEngine()
        result = engine.create(capability_id=capability_id, skills=skills)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_skill_report_rich(result)


@cli.command("capability-skill-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_skill_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability skill report."""
    from axiom_core.capability_skill import CapabilitySkillEngine

    try:
        engine = CapabilitySkillEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_skill_report_rich(report)


@cli.command("capability-skill-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_skill_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability skill report as markdown."""
    from axiom_core.capability_skill import CapabilitySkillEngine

    try:
        engine = CapabilitySkillEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_skill_report_rich(report: dict) -> None:
    """Rich text rendering for a capability skill report."""
    console.print("\n[bold]Capability Skill Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Capability:   {report.get('capability_id', '')}")
    console.print(f"  Skill Count:  {report.get('skill_count', 0)}")

    skills = report.get("skills", [])
    if skills:
        console.print("\n  [bold]Skills:[/bold]")
        for s in skills:
            stype = s.get("skill_type", "").upper()
            name = s.get("name", "")
            score = s.get("confidence_score", 0.0)
            console.print(f"    {name} [{stype}] (confidence {score})")
            for o in s.get("observations", []):
                source = o.get("source_id", "")
                osummary = o.get("summary", "")
                created = o.get("created_at", "")
                source_part = f" <- {source}" if source else ""
                console.print(f"      [{created}]{source_part}: {osummary}")


@cli.command("work-create")
@click.option("--items-file", default="", help="Path to work items JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_create_cmd(items_file: str, json_output: bool) -> None:
    """Create a work queue report."""
    from axiom_core.work_queue import WorkQueueEngine

    work_items: list = []
    if items_file:
        try:
            data = json.loads(Path(items_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                work_items = data
            elif isinstance(data, dict):
                work_items = data.get("work_items", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = WorkQueueEngine()
        result = engine.create(work_items=work_items)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_work_queue_report_rich(result)


@cli.command("work-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a work queue report."""
    from axiom_core.work_queue import WorkQueueEngine

    try:
        engine = WorkQueueEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_work_queue_report_rich(report)


@cli.command("work-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a work queue report as markdown."""
    from axiom_core.work_queue import WorkQueueEngine

    try:
        engine = WorkQueueEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_work_queue_report_rich(report: dict) -> None:
    """Rich text rendering for a work queue report."""
    console.print("\n[bold]Work Queue Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Queue ID:   {report.get('queue_id', '')}")
    console.print(f"  Pending:    {report.get('pending_count', 0)}")
    console.print(f"  Running:    {report.get('running_count', 0)}")
    console.print(f"  Blocked:    {report.get('blocked_count', 0)}")
    console.print(f"  Completed:  {report.get('completed_count', 0)}")
    console.print(f"  Failed:     {report.get('failed_count', 0)}")

    queue = report.get("queue", {})
    work_items = queue.get("work_items", [])
    if work_items:
        console.print("\n  [bold]Work Items:[/bold]")
        for w in work_items:
            priority = w.get("priority", "").upper()
            status = w.get("status", "").upper()
            title = w.get("title", "")
            console.print(f"    [{priority}] [{status}] {title}")


@cli.command("work-dependency-create")
@click.option("--deps-file", default="", help="Path to dependencies JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_dependency_create_cmd(deps_file: str, json_output: bool) -> None:
    """Create a work dependency graph report."""
    from axiom_core.work_dependency import WorkDependencyEngine

    dependencies: list = []
    if deps_file:
        try:
            data = json.loads(Path(deps_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                dependencies = data
            elif isinstance(data, dict):
                dependencies = data.get("dependencies", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = WorkDependencyEngine()
        result = engine.create(dependencies=dependencies)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_work_dependency_report_rich(result)


@cli.command("work-dependency-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_dependency_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a work dependency graph report."""
    from axiom_core.work_dependency import WorkDependencyEngine

    try:
        engine = WorkDependencyEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_work_dependency_report_rich(report)


@cli.command("work-dependency-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_dependency_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a work dependency graph report as markdown."""
    from axiom_core.work_dependency import WorkDependencyEngine

    try:
        engine = WorkDependencyEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_work_dependency_report_rich(report: dict) -> None:
    """Rich text rendering for a work dependency graph report."""
    console.print("\n[bold]Work Dependency Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Graph ID:   {report.get('graph_id', '')}")
    graph = report.get("graph", {})
    console.print(f"  Nodes:      {graph.get('node_count', 0)}")
    console.print(f"  Edges:      {graph.get('edge_count', 0)}")
    console.print(f"  Blocked:    {report.get('blocked_count', 0)}")
    console.print(f"  Invalid:    {report.get('invalid_count', 0)}")
    console.print(f"  Has Cycle:  {report.get('has_cycle', False)}")
    cycle = report.get("cycle", [])
    if cycle:
        console.print(f"  Cycle:      {' -> '.join(cycle)}")

    dependencies = graph.get("dependencies", [])
    if dependencies:
        console.print("\n  [bold]Dependencies:[/bold]")
        for d in dependencies:
            dep_type = d.get("dependency_type", "").upper()
            status = d.get("status", "").upper()
            source = d.get("source_work_id", "")
            target = d.get("target_work_id", "")
            console.print(f"    [{dep_type}] [{status}] {source} -> {target}")


@cli.command("work-priority-create")
@click.option("--rules-file", default="", help="Path to rules JSON file")
@click.option("--factors-file", default="", help="Path to factors JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_priority_create_cmd(
    rules_file: str, factors_file: str, json_output: bool
) -> None:
    """Create a work prioritization report."""
    from axiom_core.work_prioritization import WorkPrioritizationEngine

    rules: list = []
    factors: list = []
    try:
        if rules_file:
            data = json.loads(Path(rules_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                rules = data
            elif isinstance(data, dict):
                rules = data.get("rules", [])
        if factors_file:
            data = json.loads(Path(factors_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                factors = data
            elif isinstance(data, dict):
                factors = data.get("factors", [])
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    try:
        engine = WorkPrioritizationEngine()
        result = engine.create(rules=rules, factors=factors)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_work_priority_report_rich(result)


@cli.command("work-priority-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_priority_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a work prioritization report."""
    from axiom_core.work_prioritization import WorkPrioritizationEngine

    try:
        engine = WorkPrioritizationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_work_priority_report_rich(report)


@cli.command("work-priority-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def work_priority_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a work prioritization report as markdown."""
    from axiom_core.work_prioritization import WorkPrioritizationEngine

    try:
        engine = WorkPrioritizationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_work_priority_report_rich(report: dict) -> None:
    """Rich text rendering for a work prioritization report."""
    console.print("\n[bold]Work Prioritization Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Items:      {report.get('item_count', 0)}")
    console.print(
        f"  Highest:    {report.get('highest_priority_work_id', '') or 'none'}"
    )

    results = report.get("results", [])
    if results:
        console.print("\n  [bold]Ranking:[/bold]")
        for r in results:
            rank = r.get("execution_rank", 0)
            work_id = r.get("work_id", "")
            score = r.get("priority_score", 0)
            console.print(f"    {rank}. {work_id} (score={score})")


@cli.command("execution-attempt-create")
@click.option("--attempts-file", default="", help="Path to attempts JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def execution_attempt_create_cmd(attempts_file: str, json_output: bool) -> None:
    """Create an execution attempt report."""
    from axiom_core.execution_attempt import ExecutionAttemptEngine

    attempts: list = []
    if attempts_file:
        try:
            data = json.loads(Path(attempts_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                attempts = data
            elif isinstance(data, dict):
                attempts = data.get("attempts", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = ExecutionAttemptEngine()
        result = engine.create(attempts=attempts)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_execution_attempt_report_rich(result)


@cli.command("execution-attempt-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def execution_attempt_show_cmd(report_id: str, json_output: bool) -> None:
    """Show an execution attempt report."""
    from axiom_core.execution_attempt import ExecutionAttemptEngine

    try:
        engine = ExecutionAttemptEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_attempt_report_rich(report)


@cli.command("execution-attempt-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def execution_attempt_export_cmd(report_id: str, json_output: bool) -> None:
    """Export an execution attempt report as markdown."""
    from axiom_core.execution_attempt import ExecutionAttemptEngine

    try:
        engine = ExecutionAttemptEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_execution_attempt_report_rich(report: dict) -> None:
    """Rich text rendering for an execution attempt report."""
    console.print("\n[bold]Execution Attempt Report[/bold]\n")
    console.print(f"  Report ID:        {report.get('report_id', '')}")
    console.print(f"  Attempts:         {report.get('attempt_count', 0)}")
    console.print(f"  Succeeded:        {report.get('succeeded_count', 0)}")
    console.print(f"  Failed:           {report.get('failed_count', 0)}")
    console.print(f"  Partial Success:  {report.get('partial_success_count', 0)}")
    console.print(f"  Cancelled:        {report.get('cancelled_count', 0)}")

    attempts = report.get("attempts", [])
    if attempts:
        console.print("\n  [bold]Attempts:[/bold]")
        for a in attempts:
            attempt_type = a.get("attempt_type", "").upper()
            status = a.get("status", "").upper()
            work_id = a.get("work_id", "")
            duration = a.get("duration_ms", 0)
            console.print(
                f"    [{attempt_type}] [{status}] {work_id} ({duration} ms)"
            )


@cli.command("execution-outcome-create")
@click.option("--outcomes-file", default="", help="Path to outcomes JSON file")
@click.option("--json-output", is_flag=True, help="Output JSON")
def execution_outcome_create_cmd(outcomes_file: str, json_output: bool) -> None:
    """Create an execution outcome report."""
    from axiom_core.execution_outcome import ExecutionOutcomeEngine

    outcomes: list = []
    if outcomes_file:
        try:
            data = json.loads(Path(outcomes_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                outcomes = data
            elif isinstance(data, dict):
                outcomes = data.get("outcomes", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = ExecutionOutcomeEngine()
        result = engine.create(outcomes=outcomes)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_execution_outcome_report_rich(result)


@cli.command("execution-outcome-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def execution_outcome_show_cmd(report_id: str, json_output: bool) -> None:
    """Show an execution outcome report."""
    from axiom_core.execution_outcome import ExecutionOutcomeEngine

    try:
        engine = ExecutionOutcomeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_outcome_report_rich(report)


@cli.command("execution-outcome-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def execution_outcome_export_cmd(report_id: str, json_output: bool) -> None:
    """Export an execution outcome report as markdown."""
    from axiom_core.execution_outcome import ExecutionOutcomeEngine

    try:
        engine = ExecutionOutcomeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_execution_outcome_report_rich(report: dict) -> None:
    """Rich text rendering for an execution outcome report."""
    console.print("\n[bold]Execution Outcome Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Outcomes:     {report.get('outcome_count', 0)}")
    console.print(f"  Success:      {report.get('success_count', 0)}")
    console.print(f"  Failure:      {report.get('failure_count', 0)}")
    console.print(f"  Partial:      {report.get('partial_count', 0)}")
    console.print(f"  Cancelled:    {report.get('cancelled_count', 0)}")

    outcomes = report.get("outcomes", [])
    if outcomes:
        console.print("\n  [bold]Outcomes:[/bold]")
        for o in outcomes:
            outcome_type = o.get("outcome_type", "").upper()
            status = o.get("status", "").upper()
            attempt_id = o.get("attempt_id", "")
            summary = o.get("summary", "")
            line = f"    [{outcome_type}] [{status}] {attempt_id}"
            if summary:
                line += f" — {summary}"
            console.print(line)


@cli.command("failure-classification-create")
@click.option(
    "--classifications-file",
    default="",
    help="Path to classifications JSON file",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def failure_classification_create_cmd(
    classifications_file: str, json_output: bool
) -> None:
    """Create a failure classification report."""
    from axiom_core.failure_classification_framework import (
        FailureClassificationEngine,
    )

    classifications: list = []
    if classifications_file:
        try:
            data = json.loads(
                Path(classifications_file).read_text(encoding="utf-8")
            )
            if isinstance(data, list):
                classifications = data
            elif isinstance(data, dict):
                classifications = data.get("classifications", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = FailureClassificationEngine()
        result = engine.create(classifications=classifications)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_failure_classification_report_rich(result)


@cli.command("failure-classification-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def failure_classification_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a failure classification report."""
    from axiom_core.failure_classification_framework import (
        FailureClassificationEngine,
    )

    try:
        engine = FailureClassificationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_failure_classification_report_rich(report)


@cli.command("failure-classification-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def failure_classification_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a failure classification report as markdown."""
    from axiom_core.failure_classification_framework import (
        FailureClassificationEngine,
    )

    try:
        engine = FailureClassificationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_failure_classification_report_rich(report: dict) -> None:
    """Rich text rendering for a failure classification report."""
    console.print("\n[bold]Failure Classification Report[/bold]\n")
    console.print(f"  Report ID:        {report.get('report_id', '')}")
    console.print(f"  Classifications:  {report.get('classification_count', 0)}")
    console.print(f"  Info:             {report.get('info_count', 0)}")
    console.print(f"  Warning:          {report.get('warning_count', 0)}")
    console.print(f"  Error:            {report.get('error_count', 0)}")
    console.print(f"  Critical:         {report.get('critical_count', 0)}")

    classifications = report.get("classifications", [])
    if classifications:
        console.print("\n  [bold]Classifications:[/bold]")
        for c in classifications:
            failure_type = c.get("failure_type", "").upper()
            category = c.get("category", "").upper()
            severity = c.get("severity", "").upper()
            outcome_id = c.get("outcome_id", "")
            summary = c.get("summary", "")
            line = f"    [{severity}] [{failure_type}] [{category}] {outcome_id}"
            if summary:
                line += f" — {summary}"
            console.print(line)


@cli.command("recovery-recommendation-create")
@click.option(
    "--recommendations-file",
    default="",
    help="Path to recommendations JSON file",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def recovery_recommendation_create_cmd(
    recommendations_file: str, json_output: bool
) -> None:
    """Create a recovery recommendation report."""
    from axiom_core.recovery_recommendation import RecoveryRecommendationEngine

    recommendations: list = []
    if recommendations_file:
        try:
            data = json.loads(
                Path(recommendations_file).read_text(encoding="utf-8")
            )
            if isinstance(data, list):
                recommendations = data
            elif isinstance(data, dict):
                recommendations = data.get("recommendations", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = RecoveryRecommendationEngine()
        result = engine.create(recommendations=recommendations)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_recovery_recommendation_report_rich(result)


@cli.command("recovery-recommendation-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def recovery_recommendation_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a recovery recommendation report."""
    from axiom_core.recovery_recommendation import RecoveryRecommendationEngine

    try:
        engine = RecoveryRecommendationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_recovery_recommendation_report_rich(report)


@cli.command("recovery-recommendation-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def recovery_recommendation_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a recovery recommendation report as markdown."""
    from axiom_core.recovery_recommendation import RecoveryRecommendationEngine

    try:
        engine = RecoveryRecommendationEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_recovery_recommendation_report_rich(report: dict) -> None:
    """Rich text rendering for a recovery recommendation report."""
    console.print("\n[bold]Recovery Recommendation Report[/bold]\n")
    console.print(f"  Report ID:        {report.get('report_id', '')}")
    console.print(f"  Recommendations:  {report.get('recommendation_count', 0)}")
    console.print(f"  Low:              {report.get('low_count', 0)}")
    console.print(f"  Normal:           {report.get('normal_count', 0)}")
    console.print(f"  High:             {report.get('high_count', 0)}")
    console.print(f"  Critical:         {report.get('critical_count', 0)}")

    recommendations = report.get("recommendations", [])
    if recommendations:
        console.print("\n  [bold]Recommendations:[/bold]")
        for r in recommendations:
            rec_type = r.get("recommendation_type", "").upper()
            priority = r.get("priority", "").upper()
            classification_id = r.get("classification_id", "")
            summary = r.get("summary", "")
            line = f"    [{priority}] [{rec_type}] {classification_id}"
            if summary:
                line += f" — {summary}"
            console.print(line)


@cli.command("recovery-execution-create")
@click.option(
    "--executions-file",
    default="",
    help="Path to executions JSON file",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def recovery_execution_create_cmd(
    executions_file: str, json_output: bool
) -> None:
    """Create a recovery execution report."""
    from axiom_core.recovery_execution import RecoveryExecutionEngine

    executions: list = []
    if executions_file:
        try:
            data = json.loads(Path(executions_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                executions = data
            elif isinstance(data, dict):
                executions = data.get("executions", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = RecoveryExecutionEngine()
        result = engine.create(executions=executions)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_recovery_execution_report_rich(result)


@cli.command("recovery-execution-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def recovery_execution_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a recovery execution report."""
    from axiom_core.recovery_execution import RecoveryExecutionEngine

    try:
        engine = RecoveryExecutionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_recovery_execution_report_rich(report)


@cli.command("recovery-execution-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def recovery_execution_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a recovery execution report as markdown."""
    from axiom_core.recovery_execution import RecoveryExecutionEngine

    try:
        engine = RecoveryExecutionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_recovery_execution_report_rich(report: dict) -> None:
    """Rich text rendering for a recovery execution report."""
    console.print("\n[bold]Recovery Execution Report[/bold]\n")
    console.print(f"  Report ID:         {report.get('report_id', '')}")
    console.print(f"  Executions:        {report.get('execution_count', 0)}")
    console.print(f"  Succeeded:         {report.get('succeeded_count', 0)}")
    console.print(f"  Failed:            {report.get('failed_count', 0)}")
    console.print(f"  Partial Success:   {report.get('partial_success_count', 0)}")
    console.print(f"  Cancelled:         {report.get('cancelled_count', 0)}")

    executions = report.get("executions", [])
    if executions:
        console.print("\n  [bold]Executions:[/bold]")
        for e in executions:
            exec_type = e.get("execution_type", "").upper()
            status = e.get("status", "").upper()
            recommendation_id = e.get("recommendation_id", "")
            summary = e.get("summary", "")
            line = f"    [{status}] [{exec_type}] {recommendation_id}"
            if summary:
                line += f" — {summary}"
            console.print(line)


@cli.command("session-memory-create")
@click.option(
    "--entries-file",
    default="",
    help="Path to memory entries JSON file",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_memory_create_cmd(entries_file: str, json_output: bool) -> None:
    """Create a session memory report."""
    from axiom_core.session_memory import SessionMemoryEngine

    entries: list = []
    if entries_file:
        try:
            data = json.loads(Path(entries_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("entries", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = SessionMemoryEngine()
        result = engine.create(entries=entries)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_session_memory_report_rich(result)


@cli.command("session-memory-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_memory_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a session memory report."""
    from axiom_core.session_memory import SessionMemoryEngine

    try:
        engine = SessionMemoryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_session_memory_report_rich(report)


@cli.command("session-memory-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def session_memory_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a session memory report as markdown."""
    from axiom_core.session_memory import SessionMemoryEngine

    try:
        engine = SessionMemoryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_session_memory_report_rich(report: dict) -> None:
    """Rich text rendering for a session memory report."""
    console.print("\n[bold]Session Memory Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Memory ID:  {report.get('memory_id', '')}")
    console.print(f"  Entries:    {report.get('entry_count', 0)}")

    memory_type_counts = report.get("memory_type_counts", {})
    if memory_type_counts:
        console.print("\n  [bold]Type Counts:[/bold]")
        for memory_type in sorted(memory_type_counts):
            console.print(
                f"    {memory_type.upper()}: {memory_type_counts[memory_type]}"
            )

    entries = report.get("entries", [])
    if entries:
        console.print("\n  [bold]Entries:[/bold]")
        for e in entries:
            memory_type = e.get("memory_type", "").upper()
            source_id = e.get("source_id", "")
            summary = e.get("summary", "")
            line = f"    [{memory_type}] {source_id}"
            if summary:
                line += f" — {summary}"
            console.print(line)


@cli.command("skill-composition-create")
@click.option(
    "--compositions-file",
    default="",
    help="Path to skill compositions JSON file",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def skill_composition_create_cmd(compositions_file: str, json_output: bool) -> None:
    """Create a skill composition report."""
    from axiom_core.skill_composition import SkillCompositionEngine

    compositions: list = []
    if compositions_file:
        try:
            data = json.loads(Path(compositions_file).read_text(encoding="utf-8"))
            if isinstance(data, list):
                compositions = data
            elif isinstance(data, dict):
                compositions = data.get("compositions", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = SkillCompositionEngine()
        result = engine.create(compositions=compositions)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_skill_composition_report_rich(result)


@cli.command("skill-composition-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def skill_composition_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a skill composition report."""
    from axiom_core.skill_composition import SkillCompositionEngine

    try:
        engine = SkillCompositionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_skill_composition_report_rich(report)


@cli.command("skill-composition-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def skill_composition_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a skill composition report as markdown."""
    from axiom_core.skill_composition import SkillCompositionEngine

    try:
        engine = SkillCompositionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_skill_composition_report_rich(report: dict) -> None:
    """Rich text rendering for a skill composition report."""
    console.print("\n[bold]Skill Composition Report[/bold]\n")
    console.print(f"  Report ID:     {report.get('report_id', '')}")
    console.print(f"  Compositions:  {report.get('composition_count', 0)}")

    composition_type_counts = report.get("composition_type_counts", {})
    if composition_type_counts:
        console.print("\n  [bold]Type Counts:[/bold]")
        for composition_type in sorted(composition_type_counts):
            console.print(
                f"    {composition_type.upper()}: "
                f"{composition_type_counts[composition_type]}"
            )

    compositions = report.get("compositions", [])
    if compositions:
        console.print("\n  [bold]Compositions:[/bold]")
        for c in compositions:
            composition_type = c.get("composition_type", "").upper()
            name = c.get("name", "")
            console.print(f"    [{composition_type}] {name}")
            for el in c.get("elements", []):
                order_index = el.get("order_index", 0)
                skill_id = el.get("skill_id", "")
                console.print(f"      {order_index}. {skill_id}")


@cli.command("capability-routing-create")
@click.option(
    "--routing-file",
    default="",
    help="Path to capability routing JSON file (routes/rules/decisions)",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_routing_create_cmd(routing_file: str, json_output: bool) -> None:
    """Create a capability routing report."""
    from axiom_core.capability_routing import CapabilityRoutingEngine

    routes: list = []
    rules: list = []
    decisions: list = []
    if routing_file:
        try:
            data = json.loads(Path(routing_file).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                routes = data.get("routes", [])
                rules = data.get("rules", [])
                decisions = data.get("decisions", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilityRoutingEngine()
        result = engine.create(routes=routes, rules=rules, decisions=decisions)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_routing_report_rich(result)


@cli.command("capability-routing-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_routing_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability routing report."""
    from axiom_core.capability_routing import CapabilityRoutingEngine

    try:
        engine = CapabilityRoutingEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_routing_report_rich(report)


@cli.command("capability-routing-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_routing_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability routing report as markdown."""
    from axiom_core.capability_routing import CapabilityRoutingEngine

    try:
        engine = CapabilityRoutingEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_routing_report_rich(report: dict) -> None:
    """Rich text rendering for a capability routing report."""
    console.print("\n[bold]Capability Routing Report[/bold]\n")
    console.print(f"  Report ID:  {report.get('report_id', '')}")
    console.print(f"  Decisions:  {report.get('decision_count', 0)}")
    console.print(f"  Routes:     {len(report.get('routes', []))}")
    console.print(f"  Rules:      {len(report.get('rules', []))}")

    capability_counts = report.get("capability_counts", {})
    if capability_counts:
        console.print("\n  [bold]Capability Counts:[/bold]")
        for capability_id in sorted(capability_counts):
            console.print(
                f"    {_rich_escape(capability_id)}: "
                f"{capability_counts[capability_id]}"
            )

    routes = report.get("routes", [])
    if routes:
        console.print("\n  [bold]Routes:[/bold]")
        for r in routes:
            work_type = _rich_escape(f"[{r.get('work_type', '')}]")
            capability_id = _rich_escape(r.get("capability_id", ""))
            console.print(
                f"    {work_type} -> {capability_id} "
                f"(priority {r.get('priority', 0)})"
            )

    rules = report.get("rules", [])
    if rules:
        console.print("\n  [bold]Rules:[/bold]")
        for r in rules:
            work_pattern = _rich_escape(f"[{r.get('work_pattern', '')}]")
            capability_id = _rich_escape(r.get("capability_id", ""))
            console.print(
                f"    {work_pattern} -> "
                f"{capability_id} (weight {r.get('weight', 0)})"
            )

    decisions = report.get("decisions", [])
    if decisions:
        console.print("\n  [bold]Decisions:[/bold]")
        for d in decisions:
            selected = _rich_escape(
                d.get("selected_capability_id", "") or "(unrouted)"
            )
            work_id = _rich_escape(d.get("work_id", ""))
            console.print(
                f"    {work_id} -> {selected} "
                f"(score {d.get('routing_score', 0)}, "
                f"{d.get('candidate_count', 0)} candidates)"
            )


@cli.command("capability-selection-create")
@click.option(
    "--selection-file",
    default="",
    help="Path to capability selection JSON file (candidates/decisions)",
)
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_selection_create_cmd(selection_file: str, json_output: bool) -> None:
    """Create a capability selection report."""
    from axiom_core.capability_selection import CapabilitySelectionEngine

    candidates: list = []
    decisions: list = []
    if selection_file:
        try:
            data = json.loads(Path(selection_file).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                candidates = data.get("candidates", [])
                decisions = data.get("decisions", [])
        except Exception as exc:
            if json_output:
                click.echo(json.dumps({"error": str(exc)}, indent=2))
            else:
                console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1)

    try:
        engine = CapabilitySelectionEngine()
        result = engine.create(candidates=candidates, decisions=decisions)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        _render_capability_selection_report_rich(result)


@cli.command("capability-selection-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_selection_show_cmd(report_id: str, json_output: bool) -> None:
    """Show a capability selection report."""
    from axiom_core.capability_selection import CapabilitySelectionEngine

    try:
        engine = CapabilitySelectionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_selection_report_rich(report)


@cli.command("capability-selection-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, help="Output JSON")
def capability_selection_export_cmd(report_id: str, json_output: bool) -> None:
    """Export a capability selection report as markdown."""
    from axiom_core.capability_selection import CapabilitySelectionEngine

    try:
        engine = CapabilitySelectionEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    if report is None:
        if json_output:
            click.echo(
                json.dumps({"error": f"Report not found: {report_id}"}, indent=2)
            )
        else:
            console.print(f"[red]Error:[/red] Report not found: {report_id}")
        raise SystemExit(2)

    md = engine.export_report(report_id)

    if json_output:
        click.echo(
            json.dumps(
                {"report_id": report_id, "markdown": md},
                indent=2,
                default=str,
            ),
        )
    else:
        click.echo(md)


def _render_capability_selection_report_rich(report: dict) -> None:
    """Rich text rendering for a capability selection report."""
    console.print("\n[bold]Capability Selection Report[/bold]\n")
    console.print(f"  Report ID:     {report.get('report_id', '')}")
    console.print(f"  Decisions:     {report.get('decision_count', 0)}")
    console.print(f"  Candidates:    {len(report.get('candidates', []))}")
    console.print(f"  Selected:      {report.get('selected_count', 0)}")
    console.print(f"  No candidate:  {report.get('no_candidate_count', 0)}")

    capability_counts = report.get("capability_counts", {})
    if capability_counts:
        console.print("\n  [bold]Capability Counts:[/bold]")
        for capability_id in sorted(capability_counts):
            console.print(
                f"    {_rich_escape(capability_id)}: "
                f"{capability_counts[capability_id]}"
            )

    candidates = report.get("candidates", [])
    if candidates:
        console.print("\n  [bold]Candidates:[/bold]")
        for c in candidates:
            work_id = _rich_escape(f"[{c.get('work_id', '')}]")
            capability_id = _rich_escape(c.get("capability_id", ""))
            console.print(
                f"    {work_id} {capability_id} "
                f"(final {c.get('final_score', 0)}, "
                f"routing {c.get('routing_score', 0)}, "
                f"confidence {c.get('confidence_score', 0)}, "
                f"priority {c.get('priority_score', 0)})"
            )

    decisions = report.get("decisions", [])
    if decisions:
        console.print("\n  [bold]Decisions:[/bold]")
        for d in decisions:
            selected = _rich_escape(
                d.get("selected_capability_id", "") or "(no candidate)"
            )
            work_id = _rich_escape(d.get("work_id", ""))
            console.print(
                f"    {work_id} -> {selected} "
                f"(final {d.get('final_score', 0)}, "
                f"{d.get('candidate_count', 0)} candidates)"
            )
            for reason in d.get("reasons", []):
                console.print(
                    f"      - {_rich_escape(reason.get('reason_type', ''))}: "
                    f"{_rich_escape(reason.get('summary', ''))}"
                )


# ---------------------------------------------------------------------------
# Capability Chain Framework CLI
# ---------------------------------------------------------------------------


@cli.command("capability-chain-create")
@click.option(
    "--chain-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with chain definitions.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_chain_create(
    chain_file: str | None, json_output: bool
) -> None:
    """Create a capability chain report from chain definitions."""
    from axiom_core.capability_chain import CapabilityChainEngine

    try:
        chains_data: list = []
        if chain_file:
            with open(chain_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            chains_data = payload.get("chains", [])

        engine = CapabilityChainEngine()
        report = engine.create(chains=chains_data)

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_chain_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-chain-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_chain_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability chain report."""
    from axiom_core.capability_chain import CapabilityChainEngine

    try:
        engine = CapabilityChainEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_chain_report_rich(report)


@cli.command("capability-chain-export")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_chain_export(report_id: str, json_output: bool) -> None:
    """Export a capability chain report as markdown."""
    from axiom_core.capability_chain import CapabilityChainEngine

    try:
        engine = CapabilityChainEngine()
        md = engine.export_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    if json_output:
        click.echo(
            json.dumps({"report_id": report_id, "markdown": md}, indent=2)
        )
    else:
        click.echo(md)


def _render_capability_chain_report_rich(report: dict) -> None:
    """Rich text rendering for a capability chain report."""
    console.print("\n[bold]Capability Chain Report[/bold]\n")
    console.print(f"  Report ID:     {report.get('report_id', '')}")
    console.print(f"  Chains:        {report.get('chain_count', 0)}")
    console.print(f"  Steps:         {report.get('step_count', 0)}")
    console.print(f"  Empty chains:  {report.get('empty_step_count', 0)}")

    chain_type_counts = report.get("chain_type_counts", {})
    if chain_type_counts:
        console.print("\n  [bold]Type Counts:[/bold]")
        for chain_type in sorted(chain_type_counts):
            console.print(
                f"    {_rich_escape(chain_type.upper())}: "
                f"{chain_type_counts[chain_type]}"
            )

    chains_data = report.get("chains", [])
    if chains_data:
        console.print("\n  [bold]Chains:[/bold]")
        for c in chains_data:
            chain_type = _rich_escape(c.get("chain_type", "").upper())
            work_id = _rich_escape(f"[{c.get('work_id', '')}]")
            steps = c.get("steps", [])
            step_label = f"{len(steps)} steps" if steps else "(empty)"
            console.print(f"    {work_id} {chain_type} ({step_label})")
            for s in steps:
                order_index = s.get("order_index", 0)
                capability_id = _rich_escape(s.get("capability_id", ""))
                description = s.get("description", "")
                desc_suffix = f" - {_rich_escape(description)}" if description else ""
                console.print(
                    f"      {order_index}. {capability_id}{desc_suffix}"
                )


# ---------------------------------------------------------------------------
# Global Capability Registry Framework CLI
# ---------------------------------------------------------------------------


@cli.command("global-capability-create")
@click.option(
    "--registry-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with global capability entries.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def global_capability_create(
    registry_file: str | None, json_output: bool
) -> None:
    """Create a global capability registry report from entries."""
    from axiom_core.global_capability_registry import (
        GlobalCapabilityRegistryEngine,
    )

    try:
        entries_data: list = []
        if registry_file:
            with open(registry_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            entries_data = payload.get("entries", [])

        engine = GlobalCapabilityRegistryEngine()
        report = engine.create(entries=entries_data)

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_global_capability_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("global-capability-list")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def global_capability_list(json_output: bool) -> None:
    """List all persisted global capability registry reports."""
    from axiom_core.global_capability_registry import (
        GlobalCapabilityRegistryEngine,
    )

    engine = GlobalCapabilityRegistryEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No global capability registry reports found.")
        return

    console.print("\n[bold]Global Capability Registry Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('entry_count', 0)} entries, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("global-capability-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def global_capability_show(report_id: str, json_output: bool) -> None:
    """Show a persisted global capability registry report."""
    from axiom_core.global_capability_registry import (
        GlobalCapabilityRegistryEngine,
    )

    try:
        engine = GlobalCapabilityRegistryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_global_capability_report_rich(report)


@cli.command("global-capability-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def global_capability_export(report_id: str, fmt: str) -> None:
    """Export a global capability registry report (markdown/json/csv)."""
    from axiom_core.global_capability_registry import (
        GlobalCapabilityRegistryEngine,
    )

    try:
        engine = GlobalCapabilityRegistryEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_global_capability_report_rich(report: dict) -> None:
    """Rich text rendering for a global capability registry report."""
    console.print("\n[bold]Global Capability Registry[/bold]\n")
    console.print(f"  Report ID:       {report.get('report_id', '')}")
    console.print(f"  Entries:         {report.get('entry_count', 0)}")
    console.print(
        f"  Schema Version:  {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status.upper())}: {status_counts[status]}"
            )

    program_counts = report.get("program_counts", {})
    if program_counts:
        console.print("\n  [bold]Program Counts:[/bold]")
        for program in sorted(program_counts):
            console.print(
                f"    {_rich_escape(program)}: {program_counts[program]}"
            )

    entries = report.get("entries", [])
    if entries:
        console.print("\n  [bold]Timeline:[/bold]")
        for e in entries:
            number = e.get("global_capability_number", 0)
            name = _rich_escape(e.get("capability_name", ""))
            status = _rich_escape(e.get("status", "").upper())
            repo = e.get("repository", {})
            owner = repo.get("repository_owner", "")
            repo_name = repo.get("repository_name", "")
            pr_number = repo.get("repository_pr_number", 0)
            ref = _rich_escape(f"{owner}/{repo_name} PR #{pr_number}")
            console.print(f"    #{number} {name} [{status}] ({ref})")


# ---------------------------------------------------------------------------
# Capability Event Timeline Framework CLI
# ---------------------------------------------------------------------------


@cli.command("capability-event-create")
@click.option(
    "--timeline-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability events.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_event_create(
    timeline_file: str | None, json_output: bool
) -> None:
    """Create a capability event timeline from events."""
    from axiom_core.capability_event_timeline import (
        CapabilityEventTimelineEngine,
    )

    try:
        global_capability_id = ""
        events_data: list = []
        if timeline_file:
            with open(timeline_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            global_capability_id = payload.get("global_capability_id", "")
            events_data = payload.get("events", [])

        engine = CapabilityEventTimelineEngine()
        report = engine.create(
            global_capability_id=global_capability_id, events=events_data
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_event_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-event-append")
@click.argument("timeline_id")
@click.option(
    "--timeline-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability events to append.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_event_append(
    timeline_id: str, timeline_file: str | None, json_output: bool
) -> None:
    """Append events to an existing capability event timeline."""
    from axiom_core.capability_event_timeline import (
        CapabilityEventTimelineEngine,
    )

    try:
        events_data: list = []
        if timeline_file:
            with open(timeline_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            events_data = payload.get("events", [])

        engine = CapabilityEventTimelineEngine()
        report = engine.append(timeline_id, events=events_data)

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_event_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc


@cli.command("capability-event-list")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_event_list(json_output: bool) -> None:
    """List all persisted capability event timelines."""
    from axiom_core.capability_event_timeline import (
        CapabilityEventTimelineEngine,
    )

    engine = CapabilityEventTimelineEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No capability event timelines found.")
        return

    console.print("\n[bold]Capability Event Timelines[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('timeline_id', '')}  "
            f"({r.get('event_count', 0)} events, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("capability-event-show")
@click.argument("timeline_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_event_show(timeline_id: str, json_output: bool) -> None:
    """Show a persisted capability event timeline."""
    from axiom_core.capability_event_timeline import (
        CapabilityEventTimelineEngine,
    )

    try:
        engine = CapabilityEventTimelineEngine()
        report = engine.get_report(timeline_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Timeline not found: {timeline_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_event_report_rich(report)


@cli.command("capability-event-export")
@click.argument("timeline_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_event_export(timeline_id: str, fmt: str) -> None:
    """Export a capability event timeline (markdown/json/csv)."""
    from axiom_core.capability_event_timeline import (
        CapabilityEventTimelineEngine,
    )

    try:
        engine = CapabilityEventTimelineEngine()
        output = engine.export_report(timeline_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_event_report_rich(report: dict) -> None:
    """Rich text rendering for a capability event timeline."""
    console.print("\n[bold]Capability Event Timeline[/bold]\n")
    console.print(f"  Timeline ID:     {report.get('timeline_id', '')}")
    console.print(
        f"  Global Cap ID:   {report.get('global_capability_id', '')}"
    )
    console.print(f"  Events:          {report.get('event_count', 0)}")
    console.print(
        f"  Schema Version:  {report.get('schema_version', '')}"
    )

    summary = report.get("summary", {})
    type_counts = summary.get("event_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Event Type Counts:[/bold]")
        for event_type in sorted(type_counts):
            console.print(
                f"    {_rich_escape(event_type.upper())}: "
                f"{type_counts[event_type]}"
            )

    events = report.get("events", [])
    if events:
        console.print("\n  [bold]Timeline:[/bold]")
        for e in events:
            seq = e.get("event_sequence", 0)
            etype = _rich_escape(e.get("event_type", "").upper())
            ts = _rich_escape(e.get("timestamp", ""))
            summary_text = _rich_escape(e.get("summary", ""))
            console.print(f"    [{seq}] {ts} [{etype}] {summary_text}")


@cli.command("github-import")
@click.option(
    "--metadata-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with GitHub PR metadata.",
)
@click.option(
    "--repo",
    default=None,
    help="Repository in 'owner/name' form (overrides metadata).",
)
@click.option(
    "--pr",
    "pr_number",
    type=int,
    default=None,
    help="Repository PR number (overrides metadata).",
)
@click.option(
    "--global-capability-number",
    "global_capability_number",
    type=int,
    default=None,
    help="Global capability number (overrides metadata).",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def github_import(
    metadata_file: str | None,
    repo: str | None,
    pr_number: int | None,
    global_capability_number: int | None,
    json_output: bool,
) -> None:
    """Import GitHub PR metadata into registry/timeline shapes."""
    from axiom_core.github_metadata_import import GitHubMetadataImportEngine

    try:
        metadata: dict = {}
        if metadata_file:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.loads(f.read())

        engine = GitHubMetadataImportEngine()
        report = engine.import_metadata(
            metadata=metadata,
            repo=repo,
            pr_number=pr_number,
            global_capability_number=global_capability_number,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_github_import_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("github-import-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def github_import_show(report_id: str, json_output: bool) -> None:
    """Show a persisted GitHub metadata import."""
    from axiom_core.github_metadata_import import GitHubMetadataImportEngine

    try:
        engine = GitHubMetadataImportEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(
            f"Error: GitHub metadata import not found: {report_id}", err=True
        )
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_github_import_report_rich(report)


@cli.command("github-import-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def github_import_export(report_id: str, fmt: str) -> None:
    """Export a GitHub metadata import (markdown/json/csv)."""
    from axiom_core.github_metadata_import import GitHubMetadataImportEngine

    try:
        engine = GitHubMetadataImportEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_github_import_report_rich(report: dict) -> None:
    """Rich text rendering for a GitHub metadata import."""
    console.print("\n[bold]GitHub Metadata Import[/bold]\n")
    console.print(f"  Report ID:       {report.get('report_id', '')}")
    console.print(f"  Repository:      {_rich_escape(report.get('repository', ''))}")
    console.print(
        f"  PR Number:       {report.get('repository_pr_number', 0)}"
    )
    console.print(
        f"  Global Cap No.:  {report.get('global_capability_number', 0)}"
    )
    console.print(
        f"  Import Status:   {_rich_escape(report.get('status', ''))}"
    )
    console.print(f"  Commits:         {report.get('commit_count', 0)}")
    console.print(f"  Files:           {report.get('file_count', 0)}")
    console.print(f"  Labels:          {report.get('label_count', 0)}")
    console.print(
        f"  Schema Version:  {report.get('schema_version', '')}"
    )

    type_counts = report.get("timeline_event_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Timeline Event Counts:[/bold]")
        for event_type in sorted(type_counts):
            console.print(
                f"    {_rich_escape(event_type.upper())}: "
                f"{type_counts[event_type]}"
            )

    events = report.get("timeline_events", [])
    if events:
        console.print("\n  [bold]Timeline Events:[/bold]")
        for e in events:
            seq = e.get("event_sequence", 0)
            etype = _rich_escape(e.get("event_type", "").upper())
            ts = _rich_escape(e.get("timestamp", ""))
            summary_text = _rich_escape(e.get("summary", ""))
            console.print(f"    [{seq}] {ts} [{etype}] {summary_text}")


@cli.command("capability-summary-create")
@click.option(
    "--summary-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability summaries and narratives.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_summary_create(
    summary_file: str | None, json_output: bool
) -> None:
    """Create a capability summary report from summaries and narratives."""
    from axiom_core.capability_summary import CapabilitySummaryEngine

    try:
        summaries_data: list = []
        narratives_data: list = []
        raw_metadata: dict = {}
        if summary_file:
            with open(summary_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            summaries_data = payload.get("summaries", [])
            narratives_data = payload.get("narratives", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = CapabilitySummaryEngine()
        report = engine.create(
            summaries=summaries_data,
            narratives=narratives_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_summary_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-summary-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_summary_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability summary report."""
    from axiom_core.capability_summary import CapabilitySummaryEngine

    try:
        engine = CapabilitySummaryEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_summary_report_rich(report)


@cli.command("capability-summary-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_summary_export(report_id: str, fmt: str) -> None:
    """Export a capability summary report (markdown/json/csv)."""
    from axiom_core.capability_summary import CapabilitySummaryEngine

    try:
        engine = CapabilitySummaryEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_summary_report_rich(report: dict) -> None:
    """Rich text rendering for a capability summary report."""
    console.print("\n[bold]Capability Summary Report[/bold]\n")
    console.print(f"  Report ID:    {report.get('report_id', '')}")
    console.print(f"  Summaries:    {report.get('summary_count', 0)}")
    console.print(f"  Narratives:   {report.get('narrative_count', 0)}")
    console.print(
        f"  Schema Version: {report.get('schema_version', '')}"
    )

    capability_counts = report.get("capability_counts", {})
    if capability_counts:
        console.print("\n  [bold]Capability Counts:[/bold]")
        for cap_id in sorted(capability_counts):
            console.print(
                f"    {_rich_escape(cap_id)}: {capability_counts[cap_id]}"
            )

    summaries = report.get("summaries", [])
    if summaries:
        console.print("\n  [bold]Summaries:[/bold]")
        for s in summaries:
            name = _rich_escape(s.get("capability_name", ""))
            cap_id = _rich_escape(s.get("capability_id", ""))
            purpose = _rich_escape(s.get("purpose", ""))
            console.print(f"    [{cap_id}] {name}: {purpose}")

    narratives = report.get("narratives", [])
    if narratives:
        console.print("\n  [bold]Narratives:[/bold]")
        for n in narratives:
            cap_id = _rich_escape(n.get("capability_id", ""))
            context = _rich_escape(n.get("context", ""))
            console.print(f"    [{cap_id}] {context}")


@cli.command("capability-relationship-create")
@click.option(
    "--relationship-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability relationships.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_relationship_create(
    relationship_file: str | None, json_output: bool
) -> None:
    """Create a capability relationship report (graph-ready edges)."""
    from axiom_core.capability_relationship import (
        CapabilityRelationshipEngine,
    )

    try:
        relationships_data: list = []
        known_capability_ids: list = []
        raw_metadata: dict = {}
        if relationship_file:
            with open(relationship_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            relationships_data = payload.get("relationships", [])
            known_capability_ids = payload.get("known_capability_ids", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = CapabilityRelationshipEngine()
        report = engine.create(
            relationships=relationships_data,
            known_capability_ids=known_capability_ids,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_relationship_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-relationships")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_relationships(json_output: bool) -> None:
    """List all persisted capability relationship reports."""
    from axiom_core.capability_relationship import (
        CapabilityRelationshipEngine,
    )

    engine = CapabilityRelationshipEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No capability relationship reports found.")
        return

    console.print("\n[bold]Capability Relationship Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('relationship_count', 0)} relationships, "
            f"{r.get('orphan_capability_count', 0)} orphans, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("capability-relationship-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_relationship_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability relationship report."""
    from axiom_core.capability_relationship import (
        CapabilityRelationshipEngine,
    )

    try:
        engine = CapabilityRelationshipEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_relationship_report_rich(report)


@cli.command("capability-relationship-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_relationship_export(report_id: str, fmt: str) -> None:
    """Export a capability relationship report (markdown/json/csv)."""
    from axiom_core.capability_relationship import (
        CapabilityRelationshipEngine,
    )

    try:
        engine = CapabilityRelationshipEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_relationship_report_rich(report: dict) -> None:
    """Rich text rendering for a capability relationship report."""
    console.print("\n[bold]Capability Relationship Report[/bold]\n")
    console.print(f"  Report ID:      {report.get('report_id', '')}")
    console.print(
        f"  Relationships:  {report.get('relationship_count', 0)}"
    )
    console.print(
        f"  Duplicates:     "
        f"{report.get('duplicate_relationship_count', 0)}"
    )
    console.print(
        f"  Orphans:        {report.get('orphan_capability_count', 0)}"
    )
    console.print(
        f"  Schema Version: {report.get('schema_version', '')}"
    )

    type_counts = report.get("relationship_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Relationship Type Counts:[/bold]")
        for rel_type in sorted(type_counts):
            console.print(
                f"    {_rich_escape(rel_type)}: {type_counts[rel_type]}"
            )

    relationships = report.get("relationships", [])
    if relationships:
        console.print("\n  [bold]Relationships:[/bold]")
        for r in relationships:
            source = r.get("source_capability_id", "")
            target = r.get("target_capability_id", "")
            rel_type = r.get("relationship_type", "")
            console.print(
                _rich_escape(
                    f"    [{source}] --[{rel_type}]--> [{target}]"
                )
            )

    orphans = report.get("orphan_capability_ids", [])
    if orphans:
        console.print("\n  [bold]Orphan Capabilities:[/bold]")
        for cap_id in orphans:
            console.print(_rich_escape(f"    [{cap_id}]"))


@cli.command("capability-impact-create")
@click.option(
    "--impact-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability impacts and opportunities.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_impact_create(
    impact_file: str | None, json_output: bool
) -> None:
    """Create a capability impact report (impacts + opportunities)."""
    from axiom_core.capability_impact import CapabilityImpactEngine

    try:
        impacts_data: list = []
        opportunities_data: list = []
        raw_metadata: dict = {}
        if impact_file:
            with open(impact_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            impacts_data = payload.get("impacts", [])
            opportunities_data = payload.get("opportunities", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = CapabilityImpactEngine()
        report = engine.create(
            impacts=impacts_data,
            opportunities=opportunities_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_impact_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-impacts")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_impacts(json_output: bool) -> None:
    """List all persisted capability impact reports."""
    from axiom_core.capability_impact import CapabilityImpactEngine

    engine = CapabilityImpactEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No capability impact reports found.")
        return

    console.print("\n[bold]Capability Impact Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('impact_count', 0)} impacts, "
            f"{r.get('opportunity_count', 0)} opportunities, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("capability-impact-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_impact_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability impact report."""
    from axiom_core.capability_impact import CapabilityImpactEngine

    try:
        engine = CapabilityImpactEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_impact_report_rich(report)


@cli.command("capability-impact-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_impact_export(report_id: str, fmt: str) -> None:
    """Export a capability impact report (markdown/json/csv)."""
    from axiom_core.capability_impact import CapabilityImpactEngine

    try:
        engine = CapabilityImpactEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_impact_report_rich(report: dict) -> None:
    """Rich text rendering for a capability impact report."""
    console.print("\n[bold]Capability Impact Report[/bold]\n")
    console.print(f"  Report ID:      {report.get('report_id', '')}")
    console.print(f"  Impacts:        {report.get('impact_count', 0)}")
    console.print(
        f"  Opportunities:  {report.get('opportunity_count', 0)}"
    )
    console.print(
        f"  Strategic:      "
        f"{report.get('strategic_opportunity_count', 0)}"
    )
    console.print(
        f"  Schema Version: {report.get('schema_version', '')}"
    )

    type_counts = report.get("impact_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Impact Type Counts:[/bold]")
        for impact_type in sorted(type_counts):
            console.print(
                f"    {_rich_escape(impact_type)}: {type_counts[impact_type]}"
            )

    area_counts = report.get("impact_area_counts", {})
    if area_counts:
        console.print("\n  [bold]Impact Area Counts:[/bold]")
        for area in sorted(area_counts):
            console.print(
                f"    {_rich_escape(area)}: {area_counts[area]}"
            )

    impacts = report.get("impacts", [])
    if impacts:
        console.print("\n  [bold]Impacts:[/bold]")
        for i in impacts:
            cap = i.get("capability_id", "")
            itype = i.get("impact_type", "")
            area = i.get("impact_area", "")
            console.print(
                _rich_escape(f"    [{cap}] [{itype}] [{area}]")
            )

    opportunities = report.get("opportunities", [])
    if opportunities:
        console.print("\n  [bold]Opportunities:[/bold]")
        for o in opportunities:
            cap = o.get("capability_id", "")
            priority = o.get("priority", "")
            title = o.get("title", "")
            console.print(
                _rich_escape(f"    [{priority}] [{cap}] {title}")
            )


@cli.command("capability-file-create")
@click.option(
    "--file-file",
    "file_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability file relationships.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_file_create(file_file: str | None, json_output: bool) -> None:
    """Create a capability file knowledge report."""
    from axiom_core.capability_file_knowledge import (
        CapabilityFileKnowledgeEngine,
    )

    try:
        relationships_data: list = []
        references_data: list = []
        knowledge_payloads: dict = {}
        raw_metadata: dict = {}
        if file_file:
            with open(file_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            relationships_data = payload.get("file_relationships", [])
            references_data = payload.get("file_references", [])
            knowledge_payloads = payload.get("knowledge_payloads", {})
            raw_metadata = payload.get("raw_metadata", {})

        engine = CapabilityFileKnowledgeEngine()
        report = engine.create(
            file_relationships=relationships_data,
            file_references=references_data,
            knowledge_payloads=knowledge_payloads,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_file_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-files")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_files(json_output: bool) -> None:
    """List all persisted capability file knowledge reports."""
    from axiom_core.capability_file_knowledge import (
        CapabilityFileKnowledgeEngine,
    )

    engine = CapabilityFileKnowledgeEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No capability file knowledge reports found.")
        return

    console.print("\n[bold]Capability File Knowledge Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('file_count', 0)} files, "
            f"{r.get('relationship_count', 0)} relationships, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("capability-file-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_file_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability file knowledge report."""
    from axiom_core.capability_file_knowledge import (
        CapabilityFileKnowledgeEngine,
    )

    try:
        engine = CapabilityFileKnowledgeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_file_report_rich(report)


@cli.command("capability-file-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_file_export(report_id: str, fmt: str) -> None:
    """Export a capability file knowledge report (markdown/json/csv)."""
    from axiom_core.capability_file_knowledge import (
        CapabilityFileKnowledgeEngine,
    )

    try:
        engine = CapabilityFileKnowledgeEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_file_report_rich(report: dict) -> None:
    """Rich text rendering for a capability file knowledge report."""
    console.print("\n[bold]Capability File Knowledge Report[/bold]\n")
    console.print(f"  Report ID:      {report.get('report_id', '')}")
    console.print(f"  Capabilities:   {report.get('capability_count', 0)}")
    console.print(f"  Files:          {report.get('file_count', 0)}")
    console.print(
        f"  Relationships:  {report.get('relationship_count', 0)}"
    )
    console.print(f"  Directories:    {report.get('directory_count', 0)}")
    console.print(
        f"  Duplicates:     "
        f"{report.get('duplicate_relationship_count', 0)}"
    )
    console.print(
        f"  Schema Version: {report.get('schema_version', '')}"
    )

    type_counts = report.get("relationship_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Relationship Type Counts:[/bold]")
        for rel_type in sorted(type_counts):
            console.print(
                f"    {_rich_escape(rel_type)}: {type_counts[rel_type]}"
            )

    directories = report.get("affected_directories", [])
    if directories:
        console.print("\n  [bold]Affected Directories:[/bold]")
        for directory in directories:
            console.print(f"    {_rich_escape(directory)}")

    relationships = report.get("relationships", [])
    if relationships:
        console.print("\n  [bold]File Relationships:[/bold]")
        for r in relationships:
            cap = r.get("capability_id", "")
            rel_type = r.get("relationship_type", "")
            file_path = r.get("file_path", "")
            console.print(
                _rich_escape(f"    [{cap}] [{rel_type}] {file_path}")
            )

    references = report.get("references", [])
    if references:
        console.print("\n  [bold]File References:[/bold]")
        for ref in references:
            cap = ref.get("capability_id", "")
            file_path = ref.get("file_path", "")
            ext = ref.get("file_extension", "")
            console.print(
                _rich_escape(f"    [{cap}] {file_path} ({ext})")
            )


@cli.command("capability-validation-create")
@click.option(
    "--validation-file",
    "validation_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability validation records.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_validation_create(
    validation_file: str | None, json_output: bool
) -> None:
    """Create a capability validation knowledge report."""
    from axiom_core.capability_validation_knowledge import (
        CapabilityValidationKnowledgeEngine,
    )

    try:
        records_data: list = []
        findings_data: list = []
        artifacts_data: list = []
        knowledge_payloads: dict = {}
        raw_metadata: dict = {}
        if validation_file:
            with open(validation_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            records_data = payload.get("validation_records", [])
            findings_data = payload.get("validation_findings", [])
            artifacts_data = payload.get("validation_artifacts", [])
            knowledge_payloads = payload.get("knowledge_payloads", {})
            raw_metadata = payload.get("raw_metadata", {})

        engine = CapabilityValidationKnowledgeEngine()
        report = engine.create(
            validation_records=records_data,
            validation_findings=findings_data,
            validation_artifacts=artifacts_data,
            knowledge_payloads=knowledge_payloads,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_validation_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-validations")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_validations(json_output: bool) -> None:
    """List all persisted capability validation knowledge reports."""
    from axiom_core.capability_validation_knowledge import (
        CapabilityValidationKnowledgeEngine,
    )

    engine = CapabilityValidationKnowledgeEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No capability validation knowledge reports found.")
        return

    console.print("\n[bold]Capability Validation Knowledge Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('validation_count', 0)} validations, "
            f"{r.get('finding_count', 0)} findings, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("capability-validation-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_validation_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability validation knowledge report."""
    from axiom_core.capability_validation_knowledge import (
        CapabilityValidationKnowledgeEngine,
    )

    try:
        engine = CapabilityValidationKnowledgeEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_validation_report_rich(report)


@cli.command("capability-validation-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_validation_export(report_id: str, fmt: str) -> None:
    """Export a capability validation knowledge report (markdown/json/csv)."""
    from axiom_core.capability_validation_knowledge import (
        CapabilityValidationKnowledgeEngine,
    )

    try:
        engine = CapabilityValidationKnowledgeEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_validation_report_rich(report: dict) -> None:
    """Rich text rendering for a capability validation knowledge report."""
    console.print(
        "\n[bold]Capability Validation Knowledge Report[/bold]\n"
    )
    console.print(f"  Report ID:      {report.get('report_id', '')}")
    console.print(f"  Capabilities:   {report.get('capability_count', 0)}")
    console.print(f"  Validations:    {report.get('validation_count', 0)}")
    console.print(f"  Findings:       {report.get('finding_count', 0)}")
    console.print(f"  Unresolved:     {report.get('unresolved_count', 0)}")
    console.print(
        f"  Duplicates:     "
        f"{report.get('duplicate_validation_count', 0)}"
    )
    console.print(f"  Schema Version: {report.get('schema_version', '')}")

    type_counts = report.get("validation_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Validation Type Counts:[/bold]")
        for vtype in sorted(type_counts):
            console.print(
                f"    {_rich_escape(vtype)}: {type_counts[vtype]}"
            )

    status_counts = report.get("validation_status_counts", {})
    if status_counts:
        console.print("\n  [bold]Validation Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    severity_counts = report.get("finding_severity_counts", {})
    if severity_counts:
        console.print("\n  [bold]Finding Severity Counts:[/bold]")
        for severity in sorted(severity_counts):
            console.print(
                f"    {_rich_escape(severity)}: {severity_counts[severity]}"
            )

    records = report.get("records", [])
    if records:
        console.print("\n  [bold]Validations:[/bold]")
        for r in records:
            cap = r.get("capability_id", "")
            vtype = r.get("validation_type", "")
            vstatus = r.get("validation_status", "")
            validator = r.get("validator", "")
            console.print(
                _rich_escape(
                    f"    [{cap}] [{vtype}] [{vstatus}] {validator}"
                )
            )

    findings = report.get("findings", [])
    if findings:
        console.print("\n  [bold]Findings:[/bold]")
        for f in findings:
            severity = f.get("severity", "")
            resolved = "resolved" if f.get("resolved") else "unresolved"
            summary = f.get("summary", "")
            console.print(
                _rich_escape(f"    [{severity}] [{resolved}] {summary}")
            )


@cli.command("capability-graph-create")
@click.option(
    "--graph-file",
    "graph_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with capability graph nodes and edges.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_graph_create(graph_file: str | None, json_output: bool) -> None:
    """Create a capability knowledge graph report."""
    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )

    try:
        nodes_data: list = []
        edges_data: list = []
        graph_raw_payload: dict = {}
        raw_metadata: dict = {}
        if graph_file:
            with open(graph_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            nodes_data = payload.get("nodes", [])
            edges_data = payload.get("edges", [])
            graph_raw_payload = payload.get("graph_raw_payload", {})
            raw_metadata = payload.get("raw_metadata", {})

        engine = CapabilityKnowledgeGraphEngine()
        report = engine.create(
            nodes=nodes_data,
            edges=edges_data,
            graph_raw_payload=graph_raw_payload,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_capability_graph_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("capability-graphs")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_graphs(json_output: bool) -> None:
    """List all persisted capability knowledge graph reports."""
    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )

    engine = CapabilityKnowledgeGraphEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No capability knowledge graph reports found.")
        return

    console.print("\n[bold]Capability Knowledge Graph Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('node_count', 0)} nodes, "
            f"{r.get('edge_count', 0)} edges, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("capability-graph-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def capability_graph_show(report_id: str, json_output: bool) -> None:
    """Show a persisted capability knowledge graph report."""
    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )

    try:
        engine = CapabilityKnowledgeGraphEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_capability_graph_report_rich(report)


@cli.command("capability-graph-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def capability_graph_export(report_id: str, fmt: str) -> None:
    """Export a capability knowledge graph report (markdown/json/csv)."""
    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )

    try:
        engine = CapabilityKnowledgeGraphEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_capability_graph_report_rich(report: dict) -> None:
    """Rich text rendering for a capability knowledge graph report."""
    console.print("\n[bold]Capability Knowledge Graph Report[/bold]\n")
    console.print(f"  Report ID:       {report.get('report_id', '')}")
    console.print(f"  Graph ID:        {report.get('graph_id', '')}")
    console.print(f"  Nodes:           {report.get('node_count', 0)}")
    console.print(f"  Edges:           {report.get('edge_count', 0)}")
    console.print(f"  Orphan Nodes:    {report.get('orphan_node_count', 0)}")
    console.print(
        f"  Duplicate Nodes: {report.get('duplicate_node_count', 0)}"
    )
    console.print(
        f"  Duplicate Edges: {report.get('duplicate_edge_count', 0)}"
    )
    console.print(f"  Schema Version:  {report.get('schema_version', '')}")

    node_type_counts = report.get("node_type_counts", {})
    if node_type_counts:
        console.print("\n  [bold]Node Type Counts:[/bold]")
        for ntype in sorted(node_type_counts):
            console.print(
                f"    {_rich_escape(ntype)}: {node_type_counts[ntype]}"
            )

    edge_type_counts = report.get("edge_type_counts", {})
    if edge_type_counts:
        console.print("\n  [bold]Edge Type Counts:[/bold]")
        for etype in sorted(edge_type_counts):
            console.print(
                f"    {_rich_escape(etype)}: {edge_type_counts[etype]}"
            )

    nodes = report.get("nodes", [])
    if nodes:
        console.print("\n  [bold]Nodes:[/bold]")
        for n in nodes:
            ntype = n.get("node_type", "")
            source_id = n.get("source_id", "")
            label = n.get("label", "")
            console.print(
                _rich_escape(f"    [{ntype}] [{source_id}] {label}")
            )

    edges = report.get("edges", [])
    if edges:
        console.print("\n  [bold]Edges:[/bold]")
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            etype = e.get("edge_type", "")
            console.print(
                _rich_escape(f"    [{src}] --[{etype}]--> [{tgt}]")
            )


@cli.command("self-model-build")
@click.option(
    "--repo-root",
    "repo_root",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Repository root to scan (default: current directory).",
)
@click.option(
    "--artifacts-root",
    "artifacts_root",
    type=click.Path(),
    default=None,
    help="Artifacts root for the populated reports (default: ./artifacts).",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def self_model_build(
    repo_root: str, artifacts_root: str | None, json_output: bool
) -> None:
    """Build Axiom's repository self-model and populate the existing graph.

    Reuses ``code-inventory`` as the producer and feeds the existing capability
    knowledge-graph and capability-relationship engines (no new framework).
    """
    from axiom_core.self_model import SelfModelBuilder

    try:
        builder = SelfModelBuilder(repo_root)
        model = builder.build()
        graph = builder.populate_graph(artifacts_root=artifacts_root, model=model)
        rel = builder.populate_relationships(
            artifacts_root=artifacts_root, model=model
        )
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    result = {
        "graph_report_id": graph.get("report_id", ""),
        "relationship_report_id": rel.get("report_id", ""),
        "module_count": graph.get("node_count", 0),
        "import_edge_count": graph.get("edge_count", 0),
        "isolated_module_count": graph.get("orphan_node_count", 0),
        "relationship_count": rel.get("relationship_count", 0),
    }

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    console.print("\n[bold]Repository Self-Model Populated[/bold]\n")
    console.print(f"  Graph report:        {result['graph_report_id']}")
    console.print(f"  Relationship report: {result['relationship_report_id']}")
    console.print(f"  Modules (nodes):     {result['module_count']}")
    console.print(f"  Import edges:        {result['import_edge_count']}")
    console.print(f"  Isolated modules:    {result['isolated_module_count']}")
    console.print(f"  Relationships:       {result['relationship_count']}")
    console.print(
        "\n[dim]Query with: axiom self-model-query --graph "
        f"{result['graph_report_id']} [--module MODULE][/dim]"
    )


@cli.command("self-model-query")
@click.option(
    "--graph",
    "graph_report_id",
    required=True,
    help="Graph report id produced by self-model-build.",
)
@click.option(
    "--module",
    "module",
    default=None,
    help="Module to inspect (omit to list modules and isolated modules).",
)
@click.option(
    "--artifacts-root",
    "artifacts_root",
    type=click.Path(),
    default=None,
    help="Artifacts root where the report lives (default: ./artifacts).",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def self_model_query(
    graph_report_id: str,
    module: str | None,
    artifacts_root: str | None,
    json_output: bool,
) -> None:
    """Answer repository dependency questions from the populated self-model graph.

    Without ``--module``: lists modules, import edges, and isolated modules.
    With ``--module``: lists what it depends on and what depends on it.
    """
    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )
    from axiom_core.self_model import (
        graph_dependencies,
        graph_dependents,
        graph_imports,
        graph_isolated,
        graph_modules,
    )

    try:
        engine = CapabilityKnowledgeGraphEngine(artifacts_root=artifacts_root)
        report = engine.get_report(graph_report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {graph_report_id}", err=True)
        raise SystemExit(2)

    if module is None:
        modules = graph_modules(report)
        imports = graph_imports(report)
        isolated = graph_isolated(report)
        result = {
            "module_count": len(modules),
            "import_edge_count": len(imports),
            "isolated_module_count": len(isolated),
            "modules": modules,
            "isolated_modules": isolated,
        }
        if json_output:
            click.echo(json.dumps(result, indent=2, default=str))
            return
        console.print("\n[bold]Repository Self-Model[/bold]\n")
        console.print(f"  Modules:          {result['module_count']}")
        console.print(f"  Import edges:     {result['import_edge_count']}")
        console.print(f"  Isolated modules: {result['isolated_module_count']}")
        if isolated:
            console.print("\n  [bold]Isolated modules:[/bold]")
            for m in isolated:
                console.print(_rich_escape(f"    {m}"))
        return

    dependencies = graph_dependencies(report, module)
    dependents = graph_dependents(report, module)
    known = set(graph_modules(report))
    result = {
        "module": module,
        "known": module in known,
        "depends_on": dependencies,
        "depended_on_by": dependents,
        "is_isolated": module in set(graph_isolated(report)),
    }
    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
        return
    console.print(f"\n[bold]Module:[/bold] {_rich_escape(module)}")
    if module not in known:
        console.print(
            "  [yellow]Not present in the populated graph.[/yellow]"
        )
    console.print(
        f"\n  [bold]Depends on ({len(dependencies)}):[/bold]"
    )
    for m in dependencies:
        console.print(_rich_escape(f"    -> {m}"))
    if not dependencies:
        console.print("    (none)")
    console.print(
        f"\n  [bold]Depended on by ({len(dependents)}):[/bold]"
    )
    for m in dependents:
        console.print(_rich_escape(f"    <- {m}"))
    if not dependents:
        console.print("    (none)")


def _self_model_module_classes(repo_root: str) -> dict[str, list[str]]:
    """Map each ``src/`` module to its class symbol names (evidence for the
    artifact/evidence-producer gap category). Reuses ``code-inventory``."""
    from axiom_core.codebase_inventory import CodebaseInventory, SymbolKind

    inventory = CodebaseInventory(repo_root)
    files, symbols, _ = inventory.scan()
    path_to_module = {
        f.path: f.module_name
        for f in files
        if f.module_name and f.path.startswith("src/")
    }
    module_classes: dict[str, list[str]] = {}
    for s in symbols:
        if s.kind is not SymbolKind.CLASS:
            continue
        module = path_to_module.get(s.file_path)
        if module is not None:
            module_classes.setdefault(module, []).append(s.name)
    return module_classes


def _self_model_documented_modules(artifacts_root: str | None) -> set[str] | None:
    """Module ids that already have a capability summary (purpose/layer
    linkage), or ``None`` if no summary metadata is available."""
    from axiom_core.capability_summary import CapabilitySummaryEngine

    try:
        engine = CapabilitySummaryEngine(artifacts_root=artifacts_root)
        reports = engine.list_reports()
    except (ValueError, OSError):
        return None
    if not reports:
        return None
    documented: set[str] = set()
    for report in reports:
        for summary in report.get("summaries", []):
            capability_id = summary.get("capability_id")
            if capability_id:
                documented.add(capability_id)
    return documented


@cli.command("self-model-gap-analysis")
@click.option(
    "--graph",
    "graph_report_id",
    required=True,
    help="Graph report id produced by self-model-build.",
)
@click.option(
    "--repo-root",
    "repo_root",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Repository root (for producer/class evidence; default: cwd).",
)
@click.option(
    "--artifacts-root",
    "artifacts_root",
    type=click.Path(),
    default=None,
    help="Artifacts root where the report lives (default: ./artifacts).",
)
@click.option(
    "--export",
    "export_path",
    type=click.Path(),
    default=None,
    help="Write the Markdown backlog here (a sibling .json is written too).",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def self_model_gap_analysis(
    graph_report_id: str,
    repo_root: str,
    artifacts_root: str | None,
    export_path: str | None,
    json_output: bool,
) -> None:
    """Enumerate Axiom's own integration gaps from its populated self-model.

    Executable negative discovery on top of self-model-build: classifies
    isolated/unconsumed/leaf/command-only modules, declared-but-unwired
    execution-chain transitions, evidence producers without consumers,
    missing purpose/layer linkage, and disconnected framework families, then
    emits a ranked integration backlog (JSON + Markdown). No new framework.
    """
    from pathlib import Path

    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )
    from axiom_core.self_model_gap_analysis import (
        SelfModelGapAnalyzer,
        to_markdown,
    )

    try:
        engine = CapabilityKnowledgeGraphEngine(artifacts_root=artifacts_root)
        report = engine.get_report(graph_report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc
    if report is None:
        click.echo(f"Error: Report not found: {graph_report_id}", err=True)
        raise SystemExit(2)

    try:
        module_classes = _self_model_module_classes(repo_root)
    except (ValueError, OSError):
        module_classes = None
    documented_modules = _self_model_documented_modules(artifacts_root)

    analyzer = SelfModelGapAnalyzer(
        report,
        module_classes=module_classes,
        documented_modules=documented_modules,
    )
    result = analyzer.analyze()

    if export_path is not None:
        md_path = Path(export_path)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(to_markdown(result), encoding="utf-8")
        json_path = md_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    console.print("\n[bold]Self-Model Gap Analysis[/bold]\n")
    console.print(
        f"  Modules: {result['module_count']}  "
        f"Edges: {result['edge_count']}  "
        f"Isolated: {result['isolated_module_count']}"
    )
    console.print(f"  Total gaps: {result['gap_count']}\n")
    console.print("  [bold]Gap counts by type:[/bold]")
    for gap_type, count in result["gap_counts_by_type"].items():
        console.print(_rich_escape(f"    {gap_type}: {count}"))
    console.print("\n  [bold]Ranked integration backlog:[/bold]")
    for gap in result["gaps"]:
        console.print(
            _rich_escape(
                f"    [{gap['priority'].upper()}] {gap['gap_id']} "
                f"{gap['title']} "
                f"(modules: {gap['affected_module_count']}, "
                f"score: {gap['score']})"
            )
        )
    if export_path is not None:
        console.print(
            _rich_escape(f"\n  Backlog written to: {export_path}")
        )


@cli.command("execution-context-create")
@click.option(
    "--context-file",
    "context_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution contexts.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_context_create(
    context_file: str | None, json_output: bool
) -> None:
    """Create an execution context report."""
    from axiom_core.execution_context import ExecutionContextEngine

    try:
        contexts_data: list = []
        raw_metadata: dict = {}
        if context_file:
            with open(context_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            contexts_data = payload.get("contexts", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionContextEngine()
        report = engine.create(
            contexts=contexts_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_context_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-contexts")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_contexts(json_output: bool) -> None:
    """List all persisted execution context reports."""
    from axiom_core.execution_context import ExecutionContextEngine

    engine = ExecutionContextEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution context reports found.")
        return

    console.print("\n[bold]Execution Context Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('context_count', 0)} contexts, "
            f"{r.get('blocked_count', 0)} blocked, "
            f"{r.get('failed_count', 0)} failed, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-context-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_context_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution context report."""
    from axiom_core.execution_context import ExecutionContextEngine

    try:
        engine = ExecutionContextEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_context_report_rich(report)


@cli.command("execution-context-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_context_export(report_id: str, fmt: str) -> None:
    """Export an execution context report (markdown/json/csv)."""
    from axiom_core.execution_context import ExecutionContextEngine

    try:
        engine = ExecutionContextEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_context_report_rich(report: dict) -> None:
    """Rich text rendering for an execution context report."""
    console.print("\n[bold]Execution Context Report[/bold]\n")
    console.print(f"  Report ID:          {report.get('report_id', '')}")
    console.print(f"  Contexts:           {report.get('context_count', 0)}")
    console.print(f"  Blocked:            {report.get('blocked_count', 0)}")
    console.print(f"  Failed:             {report.get('failed_count', 0)}")
    console.print(
        f"  Duplicate Contexts: {report.get('duplicate_context_count', 0)}"
    )
    console.print(f"  Schema Version:     {report.get('schema_version', '')}")

    state_counts = report.get("state_counts", {})
    if state_counts:
        console.print("\n  [bold]State Counts:[/bold]")
        for state in sorted(state_counts):
            console.print(
                f"    {_rich_escape(state)}: {state_counts[state]}"
            )

    context_type_counts = report.get("context_type_counts", {})
    if context_type_counts:
        console.print("\n  [bold]Context Type Counts:[/bold]")
        for ctype in sorted(context_type_counts):
            console.print(
                f"    {_rich_escape(ctype)}: {context_type_counts[ctype]}"
            )

    contexts = report.get("contexts", [])
    if contexts:
        console.print("\n  [bold]Contexts:[/bold]")
        for c in contexts:
            state = c.get("state", "")
            ctype = c.get("context_type", "")
            work_id = c.get("work_id", "")
            capability_id = c.get("capability_id", "")
            chain_id = c.get("chain_id", "")
            console.print(
                _rich_escape(
                    f"    [{state}] [{ctype}] work={work_id} "
                    f"capability={capability_id} chain={chain_id}"
                )
            )
            for r in c.get("references", []):
                rtype = r.get("reference_type", "")
                rvalue = r.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("execution-environment-create")
@click.option(
    "--environment-file",
    "environment_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution environments.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_environment_create(
    environment_file: str | None, json_output: bool
) -> None:
    """Create an execution environment report."""
    from axiom_core.execution_environment import ExecutionEnvironmentEngine

    try:
        environments_data: list = []
        raw_metadata: dict = {}
        if environment_file:
            with open(environment_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            environments_data = payload.get("environments", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionEnvironmentEngine()
        report = engine.create(
            environments=environments_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_environment_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-environments")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_environments(json_output: bool) -> None:
    """List all persisted execution environment reports."""
    from axiom_core.execution_environment import ExecutionEnvironmentEngine

    engine = ExecutionEnvironmentEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution environment reports found.")
        return

    console.print("\n[bold]Execution Environment Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('environment_count', 0)} environments, "
            f"{r.get('unavailable_count', 0)} unavailable, "
            f"{r.get('degraded_count', 0)} degraded, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-environment-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_environment_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution environment report."""
    from axiom_core.execution_environment import ExecutionEnvironmentEngine

    try:
        engine = ExecutionEnvironmentEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_environment_report_rich(report)


@cli.command("execution-environment-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_environment_export(report_id: str, fmt: str) -> None:
    """Export an execution environment report (markdown/json/csv)."""
    from axiom_core.execution_environment import ExecutionEnvironmentEngine

    try:
        engine = ExecutionEnvironmentEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_environment_report_rich(report: dict) -> None:
    """Rich text rendering for an execution environment report."""
    console.print("\n[bold]Execution Environment Report[/bold]\n")
    console.print(f"  Report ID:              {report.get('report_id', '')}")
    console.print(
        f"  Environments:           {report.get('environment_count', 0)}"
    )
    console.print(
        f"  Unavailable:            {report.get('unavailable_count', 0)}"
    )
    console.print(
        f"  Degraded:               {report.get('degraded_count', 0)}"
    )
    console.print(
        "  Duplicate Environments: "
        f"{report.get('duplicate_environment_count', 0)}"
    )
    console.print(
        f"  Schema Version:         {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    environment_type_counts = report.get("environment_type_counts", {})
    if environment_type_counts:
        console.print("\n  [bold]Environment Type Counts:[/bold]")
        for etype in sorted(environment_type_counts):
            console.print(
                f"    {_rich_escape(etype)}: "
                f"{environment_type_counts[etype]}"
            )

    environments = report.get("environments", [])
    if environments:
        console.print("\n  [bold]Environments:[/bold]")
        for e in environments:
            status = e.get("status", "")
            etype = e.get("environment_type", "")
            context_id = e.get("context_id", "")
            capability_id = e.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] [{etype}] context={context_id} "
                    f"capability={capability_id}"
                )
            )
            for r in e.get("references", []):
                rtype = r.get("reference_type", "")
                rvalue = r.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("execution-resource-create")
@click.option(
    "--resource-file",
    "resource_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution resources.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_resource_create(
    resource_file: str | None, json_output: bool
) -> None:
    """Create an execution resource report."""
    from axiom_core.execution_resource import ExecutionResourceEngine

    try:
        resources_data: list = []
        raw_metadata: dict = {}
        if resource_file:
            with open(resource_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            resources_data = payload.get("resources", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionResourceEngine()
        report = engine.create(
            resources=resources_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_resource_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-resources")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_resources(json_output: bool) -> None:
    """List all persisted execution resource reports."""
    from axiom_core.execution_resource import ExecutionResourceEngine

    engine = ExecutionResourceEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution resource reports found.")
        return

    console.print("\n[bold]Execution Resource Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('resource_count', 0)} resources, "
            f"{r.get('unavailable_count', 0)} unavailable, "
            f"{r.get('degraded_count', 0)} degraded, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-resource-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_resource_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution resource report."""
    from axiom_core.execution_resource import ExecutionResourceEngine

    try:
        engine = ExecutionResourceEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_resource_report_rich(report)


@cli.command("execution-resource-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_resource_export(report_id: str, fmt: str) -> None:
    """Export an execution resource report (markdown/json/csv)."""
    from axiom_core.execution_resource import ExecutionResourceEngine

    try:
        engine = ExecutionResourceEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_resource_report_rich(report: dict) -> None:
    """Rich text rendering for an execution resource report."""
    console.print("\n[bold]Execution Resource Report[/bold]\n")
    console.print(f"  Report ID:            {report.get('report_id', '')}")
    console.print(
        f"  Resources:            {report.get('resource_count', 0)}"
    )
    console.print(
        f"  Unavailable:          {report.get('unavailable_count', 0)}"
    )
    console.print(
        f"  Degraded:             {report.get('degraded_count', 0)}"
    )
    console.print(
        f"  Requirements:         {report.get('requirement_count', 0)}"
    )
    console.print(
        "  Duplicate Resources:  "
        f"{report.get('duplicate_resource_count', 0)}"
    )
    console.print(
        f"  Schema Version:       {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    resource_type_counts = report.get("resource_type_counts", {})
    if resource_type_counts:
        console.print("\n  [bold]Resource Type Counts:[/bold]")
        for rtype in sorted(resource_type_counts):
            console.print(
                f"    {_rich_escape(rtype)}: "
                f"{resource_type_counts[rtype]}"
            )

    resources = report.get("resources", [])
    if resources:
        console.print("\n  [bold]Resources:[/bold]")
        for r in resources:
            status = r.get("status", "")
            rtype = r.get("resource_type", "")
            context_id = r.get("context_id", "")
            environment_id = r.get("environment_id", "")
            capability_id = r.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] [{rtype}] context={context_id} "
                    f"environment={environment_id} "
                    f"capability={capability_id}"
                )
            )
            for req in r.get("requirements", []):
                rqtype = req.get("requirement_type", "")
                rqvalue = req.get("requirement_value", "")
                console.print(_rich_escape(f"      [{rqtype}] {rqvalue}"))


@cli.command("execution-constraint-create")
@click.option(
    "--constraint-file",
    "constraint_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution constraints.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_constraint_create(
    constraint_file: str | None, json_output: bool
) -> None:
    """Create an execution constraint report."""
    from axiom_core.execution_constraint import ExecutionConstraintEngine

    try:
        constraints_data: list = []
        raw_metadata: dict = {}
        if constraint_file:
            with open(constraint_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            constraints_data = payload.get("constraints", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionConstraintEngine()
        report = engine.create(
            constraints=constraints_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_constraint_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-constraints")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_constraints(json_output: bool) -> None:
    """List all persisted execution constraint reports."""
    from axiom_core.execution_constraint import ExecutionConstraintEngine

    engine = ExecutionConstraintEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution constraint reports found.")
        return

    console.print("\n[bold]Execution Constraint Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('constraint_count', 0)} constraints, "
            f"{r.get('critical_count', 0)} critical, "
            f"{r.get('error_count', 0)} error, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-constraint-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_constraint_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution constraint report."""
    from axiom_core.execution_constraint import ExecutionConstraintEngine

    try:
        engine = ExecutionConstraintEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_constraint_report_rich(report)


@cli.command("execution-constraint-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_constraint_export(report_id: str, fmt: str) -> None:
    """Export an execution constraint report (markdown/json/csv)."""
    from axiom_core.execution_constraint import ExecutionConstraintEngine

    try:
        engine = ExecutionConstraintEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_constraint_report_rich(report: dict) -> None:
    """Rich text rendering for an execution constraint report."""
    console.print("\n[bold]Execution Constraint Report[/bold]\n")
    console.print(f"  Report ID:              {report.get('report_id', '')}")
    console.print(
        f"  Constraints:            {report.get('constraint_count', 0)}"
    )
    console.print(
        f"  Critical:               {report.get('critical_count', 0)}"
    )
    console.print(
        f"  Error:                  {report.get('error_count', 0)}"
    )
    console.print(
        "  Duplicate Constraints:  "
        f"{report.get('duplicate_constraint_count', 0)}"
    )
    console.print(
        f"  Schema Version:         {report.get('schema_version', '')}"
    )

    severity_counts = report.get("severity_counts", {})
    if severity_counts:
        console.print("\n  [bold]Severity Counts:[/bold]")
        for severity in sorted(severity_counts):
            console.print(
                f"    {_rich_escape(severity)}: {severity_counts[severity]}"
            )

    constraint_type_counts = report.get("constraint_type_counts", {})
    if constraint_type_counts:
        console.print("\n  [bold]Constraint Type Counts:[/bold]")
        for ctype in sorted(constraint_type_counts):
            console.print(
                f"    {_rich_escape(ctype)}: "
                f"{constraint_type_counts[ctype]}"
            )

    constraints = report.get("constraints", [])
    if constraints:
        console.print("\n  [bold]Constraints:[/bold]")
        for c in constraints:
            severity = c.get("severity", "")
            ctype = c.get("constraint_type", "")
            context_id = c.get("context_id", "")
            environment_id = c.get("environment_id", "")
            resource_id = c.get("resource_id", "")
            capability_id = c.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{severity}] [{ctype}] context={context_id} "
                    f"environment={environment_id} "
                    f"resource={resource_id} "
                    f"capability={capability_id}"
                )
            )
            for ref in c.get("references", []):
                rtype = ref.get("reference_type", "")
                rvalue = ref.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("execution-readiness-create")
@click.option(
    "--readiness-file",
    "readiness_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution readiness records.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_readiness_create(
    readiness_file: str | None, json_output: bool
) -> None:
    """Create an execution readiness report."""
    from axiom_core.execution_readiness import ExecutionReadinessEngine

    try:
        readinesses_data: list = []
        raw_metadata: dict = {}
        if readiness_file:
            with open(readiness_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            readinesses_data = payload.get("readinesses", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionReadinessEngine()
        report = engine.create(
            readinesses=readinesses_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_readiness_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-readinesses")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_readinesses(json_output: bool) -> None:
    """List all persisted execution readiness reports."""
    from axiom_core.execution_readiness import ExecutionReadinessEngine

    engine = ExecutionReadinessEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution readiness reports found.")
        return

    console.print("\n[bold]Execution Readiness Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('readiness_count', 0)} readinesses, "
            f"{r.get('not_ready_count', 0)} not-ready, "
            f"{r.get('degraded_count', 0)} degraded, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-readiness-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_readiness_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution readiness report."""
    from axiom_core.execution_readiness import ExecutionReadinessEngine

    try:
        engine = ExecutionReadinessEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_readiness_report_rich(report)


@cli.command("execution-readiness-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_readiness_export(report_id: str, fmt: str) -> None:
    """Export an execution readiness report (markdown/json/csv)."""
    from axiom_core.execution_readiness import ExecutionReadinessEngine

    try:
        engine = ExecutionReadinessEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_readiness_report_rich(report: dict) -> None:
    """Rich text rendering for an execution readiness report."""
    console.print("\n[bold]Execution Readiness Report[/bold]\n")
    console.print(f"  Report ID:              {report.get('report_id', '')}")
    console.print(
        f"  Readinesses:            {report.get('readiness_count', 0)}"
    )
    console.print(
        f"  Ready:                  {report.get('ready_count', 0)}"
    )
    console.print(
        f"  Degraded:               {report.get('degraded_count', 0)}"
    )
    console.print(
        f"  Not Ready:              {report.get('not_ready_count', 0)}"
    )
    console.print(
        f"  Checks:                 {report.get('check_count', 0)}"
    )
    console.print(
        "  Duplicate Readinesses:  "
        f"{report.get('duplicate_readiness_count', 0)}"
    )
    console.print(
        f"  Schema Version:         {report.get('schema_version', '')}"
    )

    status_counts = report.get("readiness_status_counts", {})
    if status_counts:
        console.print("\n  [bold]Readiness Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    check_type_counts = report.get("check_type_counts", {})
    if check_type_counts:
        console.print("\n  [bold]Check Type Counts:[/bold]")
        for ctype in sorted(check_type_counts):
            console.print(
                f"    {_rich_escape(ctype)}: "
                f"{check_type_counts[ctype]}"
            )

    readinesses = report.get("readinesses", [])
    if readinesses:
        console.print("\n  [bold]Readinesses:[/bold]")
        for r in readinesses:
            status = r.get("readiness_status", "")
            context_id = r.get("context_id", "")
            environment_id = r.get("environment_id", "")
            resource_id = r.get("resource_id", "")
            constraint_id = r.get("constraint_id", "")
            capability_id = r.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] context={context_id} "
                    f"environment={environment_id} "
                    f"resource={resource_id} "
                    f"constraint={constraint_id} "
                    f"capability={capability_id}"
                )
            )
            for check in r.get("checks", []):
                ctype = check.get("check_type", "")
                cstatus = check.get("status", "")
                console.print(_rich_escape(f"      [{ctype}] {cstatus}"))


@cli.command("execution-plan-create")
@click.option(
    "--plan-file",
    "plan_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution plan records.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_plan_create(plan_file: str | None, json_output: bool) -> None:
    """Create an execution plan report."""
    from axiom_core.execution_plan import ExecutionPlanEngine

    try:
        plans_data: list = []
        raw_metadata: dict = {}
        if plan_file:
            with open(plan_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            plans_data = payload.get("plans", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionPlanEngine()
        report = engine.create(
            plans=plans_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_plan_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-plans")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_plans(json_output: bool) -> None:
    """List all persisted execution plan reports."""
    from axiom_core.execution_plan import ExecutionPlanEngine

    engine = ExecutionPlanEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution plan reports found.")
        return

    console.print("\n[bold]Execution Plan Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('plan_count', 0)} plans, "
            f"{r.get('blocked_count', 0)} blocked, "
            f"{r.get('failed_count', 0)} failed, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-plan-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_plan_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution plan report."""
    from axiom_core.execution_plan import ExecutionPlanEngine

    try:
        engine = ExecutionPlanEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_plan_report_rich(report)


@cli.command("execution-plan-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_plan_export(report_id: str, fmt: str) -> None:
    """Export an execution plan report (markdown/json/csv)."""
    from axiom_core.execution_plan import ExecutionPlanEngine

    try:
        engine = ExecutionPlanEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_plan_report_rich(report: dict) -> None:
    """Rich text rendering for an execution plan report."""
    console.print("\n[bold]Execution Plan Report[/bold]\n")
    console.print(f"  Report ID:        {report.get('report_id', '')}")
    console.print(f"  Plans:            {report.get('plan_count', 0)}")
    console.print(f"  Blocked:          {report.get('blocked_count', 0)}")
    console.print(f"  Failed:           {report.get('failed_count', 0)}")
    console.print(f"  Steps:            {report.get('step_count', 0)}")
    console.print(
        f"  Duplicate Plans:  {report.get('duplicate_plan_count', 0)}"
    )
    console.print(
        f"  Schema Version:   {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    plan_type_counts = report.get("plan_type_counts", {})
    if plan_type_counts:
        console.print("\n  [bold]Plan Type Counts:[/bold]")
        for ptype in sorted(plan_type_counts):
            console.print(
                f"    {_rich_escape(ptype)}: {plan_type_counts[ptype]}"
            )

    plans = report.get("plans", [])
    if plans:
        console.print("\n  [bold]Plans:[/bold]")
        for p in plans:
            status = p.get("status", "")
            plan_type = p.get("plan_type", "")
            capability_id = p.get("capability_id", "")
            readiness_id = p.get("readiness_id", "")
            chain_id = p.get("chain_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] [{plan_type}] "
                    f"capability={capability_id} "
                    f"readiness={readiness_id} chain={chain_id}"
                )
            )
            for step in p.get("steps", []):
                order_index = step.get("order_index", 0)
                step_name = step.get("step_name", "")
                console.print(
                    _rich_escape(f"      [{order_index}] {step_name}")
                )


@cli.command("execution-step-create")
@click.option(
    "--step-file",
    "step_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution steps.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_step_create(step_file: str | None, json_output: bool) -> None:
    """Create an execution step report."""
    from axiom_core.execution_step import ExecutionStepEngine

    try:
        steps_data: list = []
        raw_metadata: dict = {}
        if step_file:
            with open(step_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            steps_data = payload.get("steps", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionStepEngine()
        report = engine.create(
            steps=steps_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_step_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-steps")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_steps(json_output: bool) -> None:
    """List all persisted execution step reports."""
    from axiom_core.execution_step import ExecutionStepEngine

    engine = ExecutionStepEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution step reports found.")
        return

    console.print("\n[bold]Execution Step Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('step_count', 0)} steps, "
            f"{r.get('blocked_count', 0)} blocked, "
            f"{r.get('failed_count', 0)} failed, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-step-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_step_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution step report."""
    from axiom_core.execution_step import ExecutionStepEngine

    try:
        engine = ExecutionStepEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_step_report_rich(report)


@cli.command("execution-step-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_step_export(report_id: str, fmt: str) -> None:
    """Export an execution step report (markdown/json/csv)."""
    from axiom_core.execution_step import ExecutionStepEngine

    try:
        engine = ExecutionStepEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_step_report_rich(report: dict) -> None:
    """Rich text rendering for an execution step report."""
    console.print("\n[bold]Execution Step Report[/bold]\n")
    console.print(f"  Report ID:       {report.get('report_id', '')}")
    console.print(f"  Steps:           {report.get('step_count', 0)}")
    console.print(f"  Blocked:         {report.get('blocked_count', 0)}")
    console.print(f"  Failed:          {report.get('failed_count', 0)}")
    console.print(f"  Skipped:         {report.get('skipped_count', 0)}")
    console.print(
        f"  Duplicate Steps: {report.get('duplicate_step_count', 0)}"
    )
    console.print(
        f"  Schema Version:  {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    step_type_counts = report.get("step_type_counts", {})
    if step_type_counts:
        console.print("\n  [bold]Step Type Counts:[/bold]")
        for stype in sorted(step_type_counts):
            console.print(
                f"    {_rich_escape(stype)}: {step_type_counts[stype]}"
            )

    steps = report.get("steps", [])
    if steps:
        console.print("\n  [bold]Steps:[/bold]")
        for s in steps:
            status = s.get("status", "")
            stype = s.get("step_type", "")
            order_index = s.get("order_index", 0)
            plan_id = s.get("plan_id", "")
            capability_id = s.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] [{stype}] [{order_index}] "
                    f"plan={plan_id} capability={capability_id}"
                )
            )
            for ref in s.get("references", []):
                rtype = ref.get("reference_type", "")
                rvalue = ref.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("execution-attempt-v2-create")
@click.option(
    "--attempt-file",
    "attempt_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution attempts.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_attempt_v2_create(
    attempt_file: str | None, json_output: bool
) -> None:
    """Create an execution attempt (v2) report."""
    from axiom_core.execution_attempt_v2 import ExecutionAttemptEngine

    try:
        attempts_data: list = []
        raw_metadata: dict = {}
        if attempt_file:
            with open(attempt_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            attempts_data = payload.get("attempts", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionAttemptEngine()
        report = engine.create(
            attempts=attempts_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_attempt_v2_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-attempts-v2")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_attempts_v2(json_output: bool) -> None:
    """List all persisted execution attempt (v2) reports."""
    from axiom_core.execution_attempt_v2 import ExecutionAttemptEngine

    engine = ExecutionAttemptEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution attempt reports found.")
        return

    console.print("\n[bold]Execution Attempt Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('attempt_count', 0)} attempts, "
            f"{r.get('failed_count', 0)} failed, "
            f"{r.get('timeout_count', 0)} timed out, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-attempt-v2-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_attempt_v2_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution attempt (v2) report."""
    from axiom_core.execution_attempt_v2 import ExecutionAttemptEngine

    try:
        engine = ExecutionAttemptEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_attempt_v2_report_rich(report)


@cli.command("execution-attempt-v2-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_attempt_v2_export(report_id: str, fmt: str) -> None:
    """Export an execution attempt (v2) report (markdown/json/csv)."""
    from axiom_core.execution_attempt_v2 import ExecutionAttemptEngine

    try:
        engine = ExecutionAttemptEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_attempt_v2_report_rich(report: dict) -> None:
    """Rich text rendering for an execution attempt (v2) report."""
    console.print("\n[bold]Execution Attempt Report[/bold]\n")
    console.print(f"  Report ID:          {report.get('report_id', '')}")
    console.print(f"  Attempts:           {report.get('attempt_count', 0)}")
    console.print(f"  Failed:             {report.get('failed_count', 0)}")
    console.print(f"  Timed Out:          {report.get('timeout_count', 0)}")
    console.print(f"  Succeeded:          {report.get('success_count', 0)}")
    console.print(
        f"  Total Duration (s): "
        f"{report.get('total_duration_seconds', 0.0)}"
    )
    console.print(
        f"  Duplicate Attempts: {report.get('duplicate_attempt_count', 0)}"
    )
    console.print(
        f"  Schema Version:     {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    result_counts = report.get("result_counts", {})
    if result_counts:
        console.print("\n  [bold]Result Counts:[/bold]")
        for result in sorted(result_counts):
            console.print(
                f"    {_rich_escape(result)}: {result_counts[result]}"
            )

    attempts = report.get("attempts", [])
    if attempts:
        console.print("\n  [bold]Attempts:[/bold]")
        for a in attempts:
            status = a.get("status", "")
            result = a.get("result", "")
            duration = a.get("duration_seconds", 0.0)
            step_id = a.get("step_id", "")
            plan_id = a.get("plan_id", "")
            capability_id = a.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] [{result}] [{duration}s] "
                    f"step={step_id} plan={plan_id} "
                    f"capability={capability_id}"
                )
            )
            for ref in a.get("references", []):
                rtype = ref.get("reference_type", "")
                rvalue = ref.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("execution-result-create")
@click.option(
    "--result-file",
    "result_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution results.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_result_create(
    result_file: str | None, json_output: bool
) -> None:
    """Create an execution result report."""
    from axiom_core.execution_result import ExecutionResultEngine

    try:
        results_data: list = []
        raw_metadata: dict = {}
        if result_file:
            with open(result_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            results_data = payload.get("results", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionResultEngine()
        report = engine.create(
            results=results_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_result_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-results")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_results(json_output: bool) -> None:
    """List all persisted execution result reports."""
    from axiom_core.execution_result import ExecutionResultEngine

    engine = ExecutionResultEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution result reports found.")
        return

    console.print("\n[bold]Execution Result Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('result_count', 0)} results, "
            f"{r.get('failed_count', 0)} failed, "
            f"{r.get('empty_count', 0)} empty, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-result-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_result_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution result report."""
    from axiom_core.execution_result import ExecutionResultEngine

    try:
        engine = ExecutionResultEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_result_report_rich(report)


@cli.command("execution-result-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_result_export(report_id: str, fmt: str) -> None:
    """Export an execution result report (markdown/json/csv)."""
    from axiom_core.execution_result import ExecutionResultEngine

    try:
        engine = ExecutionResultEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_result_report_rich(report: dict) -> None:
    """Rich text rendering for an execution result report."""
    console.print("\n[bold]Execution Result Report[/bold]\n")
    console.print(f"  Report ID:        {report.get('report_id', '')}")
    console.print(f"  Results:          {report.get('result_count', 0)}")
    console.print(f"  Failed:           {report.get('failed_count', 0)}")
    console.print(f"  Empty:            {report.get('empty_count', 0)}")
    console.print(f"  Produced:         {report.get('produced_count', 0)}")
    console.print(
        f"  Duplicate Results: {report.get('duplicate_result_count', 0)}"
    )
    console.print(
        f"  Schema Version:   {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    result_type_counts = report.get("result_type_counts", {})
    if result_type_counts:
        console.print("\n  [bold]Result Type Counts:[/bold]")
        for result_type in sorted(result_type_counts):
            console.print(
                f"    {_rich_escape(result_type)}: "
                f"{result_type_counts[result_type]}"
            )

    results = report.get("results", [])
    if results:
        console.print("\n  [bold]Results:[/bold]")
        for r in results:
            status = r.get("status", "")
            result_type = r.get("result_type", "")
            attempt_id = r.get("attempt_id", "")
            step_id = r.get("step_id", "")
            capability_id = r.get("capability_id", "")
            console.print(
                _rich_escape(
                    f"    [{status}] [{result_type}] "
                    f"attempt={attempt_id} step={step_id} "
                    f"capability={capability_id}"
                )
            )
            for ref in r.get("references", []):
                rtype = ref.get("reference_type", "")
                rvalue = ref.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("execution-artifact-create")
@click.option(
    "--artifact-file",
    "artifact_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with execution artifacts.",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_artifact_create(
    artifact_file: str | None, json_output: bool
) -> None:
    """Create an execution artifact report."""
    from axiom_core.execution_artifact import ExecutionArtifactEngine

    try:
        artifacts_data: list = []
        raw_metadata: dict = {}
        if artifact_file:
            with open(artifact_file, encoding="utf-8") as f:
                payload = json.loads(f.read())
            artifacts_data = payload.get("artifacts", [])
            raw_metadata = payload.get("raw_metadata", {})

        engine = ExecutionArtifactEngine()
        report = engine.create(
            artifacts=artifacts_data,
            raw_metadata=raw_metadata,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_execution_artifact_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("execution-artifacts")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_artifacts(json_output: bool) -> None:
    """List all persisted execution artifact reports."""
    from axiom_core.execution_artifact import ExecutionArtifactEngine

    engine = ExecutionArtifactEngine()
    reports = engine.list_reports()

    if json_output:
        click.echo(json.dumps(reports, indent=2, default=str))
        return

    if not reports:
        click.echo("No execution artifact reports found.")
        return

    console.print("\n[bold]Execution Artifact Reports[/bold]\n")
    for r in reports:
        console.print(
            f"  {r.get('report_id', '')}  "
            f"({r.get('artifact_count', 0)} artifacts, "
            f"{r.get('missing_count', 0)} missing, "
            f"{r.get('invalid_count', 0)} invalid, "
            f"created {r.get('created_at', '')})"
        )


@cli.command("execution-artifact-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def execution_artifact_show(report_id: str, json_output: bool) -> None:
    """Show a persisted execution artifact report."""
    from axiom_core.execution_artifact import ExecutionArtifactEngine

    try:
        engine = ExecutionArtifactEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(f"Error: Report not found: {report_id}", err=True)
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_execution_artifact_report_rich(report)


@cli.command("execution-artifact-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def execution_artifact_export(report_id: str, fmt: str) -> None:
    """Export an execution artifact report (markdown/json/csv)."""
    from axiom_core.execution_artifact import ExecutionArtifactEngine

    try:
        engine = ExecutionArtifactEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_execution_artifact_report_rich(report: dict) -> None:
    """Rich text rendering for an execution artifact report."""
    console.print("\n[bold]Execution Artifact Report[/bold]\n")
    console.print(f"  Report ID:          {report.get('report_id', '')}")
    console.print(f"  Artifacts:          {report.get('artifact_count', 0)}")
    console.print(f"  Missing:            {report.get('missing_count', 0)}")
    console.print(f"  Invalid:            {report.get('invalid_count', 0)}")
    console.print(f"  Created:            {report.get('created_count', 0)}")
    console.print(
        f"  Referenced:         {report.get('referenced_count', 0)}"
    )
    console.print(
        f"  Duplicate Artifacts: "
        f"{report.get('duplicate_artifact_count', 0)}"
    )
    console.print(
        f"  Schema Version:     {report.get('schema_version', '')}"
    )

    status_counts = report.get("status_counts", {})
    if status_counts:
        console.print("\n  [bold]Status Counts:[/bold]")
        for status in sorted(status_counts):
            console.print(
                f"    {_rich_escape(status)}: {status_counts[status]}"
            )

    artifact_type_counts = report.get("artifact_type_counts", {})
    if artifact_type_counts:
        console.print("\n  [bold]Artifact Type Counts:[/bold]")
        for artifact_type in sorted(artifact_type_counts):
            console.print(
                f"    {_rich_escape(artifact_type)}: "
                f"{artifact_type_counts[artifact_type]}"
            )

    artifacts = report.get("artifacts", [])
    if artifacts:
        console.print("\n  [bold]Artifacts:[/bold]")
        for a in artifacts:
            status = a.get("status", "")
            artifact_type = a.get("artifact_type", "")
            result_id = a.get("result_id", "")
            attempt_id = a.get("attempt_id", "")
            capability_id = a.get("capability_id", "")
            artifact_path = a.get("artifact_path", "")
            artifact_url = a.get("artifact_url", "")
            location = artifact_path or artifact_url or "-"
            console.print(
                _rich_escape(
                    f"    [{status}] [{artifact_type}] "
                    f"result={result_id} attempt={attempt_id} "
                    f"capability={capability_id} location={location}"
                )
            )
            for ref in a.get("references", []):
                rtype = ref.get("reference_type", "")
                rvalue = ref.get("reference_value", "")
                console.print(_rich_escape(f"      [{rtype}] {rvalue}"))


@cli.command("devin-session-import")
@click.option(
    "--session-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a JSON file with Devin session metadata.",
)
@click.option(
    "--session-id",
    "session_id",
    default=None,
    help="Devin session id (overrides metadata).",
)
@click.option(
    "--repo",
    default=None,
    help="Repository in 'owner/name' form (overrides metadata).",
)
@click.option(
    "--pr",
    "pr_number",
    type=int,
    default=None,
    help="Repository PR number (overrides metadata).",
)
@click.option(
    "--global-capability-number",
    "global_capability_number",
    type=int,
    default=None,
    help="Global capability number (overrides metadata).",
)
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def devin_session_import(
    session_file: str | None,
    session_id: str | None,
    repo: str | None,
    pr_number: int | None,
    global_capability_number: int | None,
    json_output: bool,
) -> None:
    """Import Devin session metadata into registry/timeline shapes."""
    from axiom_core.devin_session_import import (
        DevinSessionMetadataImportEngine,
    )

    try:
        metadata: dict = {}
        if session_file:
            with open(session_file, encoding="utf-8") as f:
                metadata = json.loads(f.read())

        engine = DevinSessionMetadataImportEngine()
        report = engine.import_session(
            metadata=metadata,
            session_id=session_id,
            repo=repo,
            pr_number=pr_number,
            global_capability_number=global_capability_number,
        )

        if json_output:
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            _render_devin_session_import_report_rich(report)
    except (ValueError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("devin-session-show")
@click.argument("report_id")
@click.option("--json-output", is_flag=True, default=False, help="Output JSON.")
def devin_session_show(report_id: str, json_output: bool) -> None:
    """Show a persisted Devin session metadata import."""
    from axiom_core.devin_session_import import (
        DevinSessionMetadataImportEngine,
    )

    try:
        engine = DevinSessionMetadataImportEngine()
        report = engine.get_report(report_id)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    if report is None:
        click.echo(
            f"Error: Devin session import not found: {report_id}", err=True
        )
        raise SystemExit(2)

    if json_output:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        _render_devin_session_import_report_rich(report)


@cli.command("devin-session-export")
@click.argument("report_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "csv"]),
    default="markdown",
    help="Export format.",
)
def devin_session_export(report_id: str, fmt: str) -> None:
    """Export a Devin session metadata import (markdown/json/csv)."""
    from axiom_core.devin_session_import import (
        DevinSessionMetadataImportEngine,
    )

    try:
        engine = DevinSessionMetadataImportEngine()
        output = engine.export_report(report_id, fmt=fmt)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        if "not found" in str(exc).lower():
            raise SystemExit(2) from exc
        raise SystemExit(1) from exc

    click.echo(output)


def _render_devin_session_import_report_rich(report: dict) -> None:
    """Rich text rendering for a Devin session metadata import."""
    console.print("\n[bold]Devin Session Metadata Import[/bold]\n")
    console.print(f"  Report ID:       {report.get('report_id', '')}")
    console.print(
        f"  Session ID:      {_rich_escape(report.get('session_id', ''))}"
    )
    console.print(
        f"  Repository:      {_rich_escape(report.get('repository', ''))}"
    )
    console.print(
        f"  Global Cap No.:  {report.get('global_capability_number', 0)}"
    )
    console.print(
        f"  Import Status:   {_rich_escape(report.get('status', ''))}"
    )
    console.print(
        f"  Registry Ref.:   "
        f"{_rich_escape(report.get('registry_reference_status', ''))}"
    )
    console.print(f"  Actions:         {report.get('action_count', 0)}")
    console.print(f"  Artifacts:       {report.get('artifact_count', 0)}")
    console.print(
        f"  Skill Proposals: {report.get('skill_proposal_count', 0)}"
    )
    console.print(f"  Schema Version:  {report.get('schema_version', '')}")

    action_counts = report.get("action_type_counts", {})
    if action_counts:
        console.print("\n  [bold]Action Type Counts:[/bold]")
        for action_type in sorted(action_counts):
            console.print(
                f"    {_rich_escape(action_type.upper())}: "
                f"{action_counts[action_type]}"
            )

    type_counts = report.get("timeline_event_type_counts", {})
    if type_counts:
        console.print("\n  [bold]Timeline Event Counts:[/bold]")
        for event_type in sorted(type_counts):
            console.print(
                f"    {_rich_escape(event_type.upper())}: "
                f"{type_counts[event_type]}"
            )

    events = report.get("timeline_events", [])
    if events:
        console.print("\n  [bold]Timeline Events:[/bold]")
        for e in events:
            seq = e.get("event_sequence", 0)
            etype = _rich_escape(e.get("event_type", "").upper())
            ts = _rich_escape(e.get("timestamp", ""))
            summary_text = _rich_escape(e.get("summary", ""))
            console.print(f"    [{seq}] {ts} [{etype}] {summary_text}")


if __name__ == "__main__":
    cli()
