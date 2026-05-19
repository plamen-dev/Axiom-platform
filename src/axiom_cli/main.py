"""Axiom CLI - Command-line interface for the Axiom platform."""

from typing import Optional
from uuid import UUID

import click
from axiom_core.input_normalization import InputNormalizer, NormalizationReport
from axiom_core.mcp_layer import MCPLayer
from axiom_core.orchestrator import Orchestrator
from axiom_core.persistence import storage
from axiom_core.schemas import JobStatus, PlanStatus
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Axiom Platform CLI - AI-powered autonomous Revit workflows."""
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
def test_grids(run_mode, case_file, limit, run_id, output_dir, fail_fast):
    """Run the CreateGrids deterministic test harness."""
    from datetime import datetime, timezone
    from pathlib import Path

    from axiom_core.testing.loader import load_test_cases
    from axiom_core.testing.report import find_latest_previous_run, generate_summary
    from axiom_core.testing.runner import run_test_suite
    from axiom_core.testing.storage import persist_results

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
def test_levels(run_mode, case_file, limit, run_id, output_dir, fail_fast):
    """Run the CreateLevels deterministic test harness."""
    from datetime import datetime, timezone
    from pathlib import Path

    from axiom_core.testing.loader import load_test_cases
    from axiom_core.testing.report import find_latest_previous_run, generate_summary
    from axiom_core.testing.runner import run_test_suite
    from axiom_core.testing.storage import persist_results

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

    if not s.total_elements and not s.total_parameters:
        console.print("[yellow]No data found in this run.[/yellow]")
        return

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

    # Run metadata
    meta_table = Table(title="Run Metadata", show_header=True)
    meta_table.add_column("Field", style="cyan")
    meta_table.add_column("Value", style="white")
    meta_table.add_row("Run ID", s.run_id or "(unknown)")
    meta_table.add_row("Source Model", s.source_model or "(unknown)")
    console.print(meta_table)

    # Totals
    totals_table = Table(title="Totals", show_header=True)
    totals_table.add_column("Metric", style="cyan")
    totals_table.add_column("Count", style="white")
    totals_table.add_row("Element instances", str(s.total_instances))
    totals_table.add_row("Element types", str(s.total_types))
    totals_table.add_row("Total parameters", str(s.total_parameters))
    totals_table.add_row("Read-only params", str(s.read_only_params))
    totals_table.add_row("Writable params", str(s.writable_params))
    totals_table.add_row("Instance params", str(s.instance_params))
    totals_table.add_row("Type params", str(s.type_params))
    totals_table.add_row("Missing level", str(s.missing_level_count))
    console.print(totals_table)

    # Category counts
    if s.category_counts:
        cat_table = Table(title="Categories", show_header=True)
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", style="white")
        for cat, count in sorted(s.category_counts.items(), key=lambda x: -x[1]):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    # Top parameter names
    if s.top_param_names:
        param_table = Table(title="Top Parameter Names", show_header=True)
        param_table.add_column("Parameter", style="cyan")
        param_table.add_column("Occurrences", style="white")
        for name, count in s.top_param_names[:15]:
            param_table.add_row(name, str(count))
        console.print(param_table)


if __name__ == "__main__":
    cli()
