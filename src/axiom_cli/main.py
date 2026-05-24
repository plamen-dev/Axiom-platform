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
    covered_categories = {r["ObjectCategory"] for r in final_rows if r["ObjectCategory"]}
    unique_names = {r["ParameterName"] for r in final_rows}
    ro_count = sum(1 for r in final_rows if r["IsReadOnly"])
    instance_count = sum(1 for r in final_rows if r["IsInstanceParam"])
    type_count = sum(1 for r in final_rows if r["IsTypeParam"])
    cat_counter = Counter(r["ObjectCategory"] for r in final_rows)
    dt_counter = Counter(r["DataTypeLabel"] for r in final_rows if r["DataTypeLabel"])
    grp_counter = Counter(r["GroupTypeLabel"] for r in final_rows if r["GroupTypeLabel"])

    # Check coverage against object registry if provided
    all_categories: set[str] = set()
    if object_registry_dir:
        obj_reg_path = Path(object_registry_dir)
        obj_parquet_files = list(obj_reg_path.rglob("revit_object_registry.parquet"))
        for opf in obj_parquet_files:
            ot = pq.read_table(str(opf))
            if "category" in ot.schema.names:
                all_categories.update(
                    c for c in ot.column("category").to_pylist() if c
                )
        # Also check elements.parquet
        elem_parquet_files = list(obj_reg_path.rglob("elements.parquet"))
        for epf in elem_parquet_files:
            et = pq.read_table(str(epf))
            if "category" in et.schema.names:
                all_categories.update(
                    c for c in et.column("category").to_pylist() if c
                )

    missing_categories = sorted(all_categories - covered_categories) if all_categories else []

    # Priority coverage analysis
    from axiom_core.inventory.extraction_planner import PRIORITY_CATEGORIES
    priority_lower = {p.lower(): p for p in PRIORITY_CATEGORIES}
    covered_priority = sorted(
        c for c in covered_categories if c.lower() in priority_lower
    )
    missing_priority = sorted(
        p for p in PRIORITY_CATEGORIES if p.lower() not in {c.lower() for c in covered_categories}
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
        f"- **Categories with coverage:** {len(covered_categories)}\n",
        f"- **Read-only:** {ro_count}\n",
        f"- **Writable:** {len(final_rows) - ro_count}\n",
        f"- **Instance params:** {instance_count}\n",
        f"- **Type params:** {type_count}\n",
    ]
    if all_categories:
        summary_lines.extend([
            f"- **Total discovered categories:** {len(all_categories)}\n",
            f"- **Categories missing coverage:** {len(missing_categories)}\n",
        ])
    summary_lines.extend([
        f"- **Priority categories covered:** {len(covered_priority)} / {len(PRIORITY_CATEGORIES)}\n",
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
    if missing_categories:
        summary_lines.append("\n## All Missing Coverage\n")
        for mc in missing_categories:
            summary_lines.append(f"- {mc}\n")
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
        "categories_with_coverage": sorted(covered_categories),
        "categories_missing_coverage": missing_categories,
        "covered_priority_categories": covered_priority,
        "missing_priority_categories": missing_priority,
        "category_count": len(covered_categories),
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
                  f"from {len(source_runs)} runs across {len(covered_categories)} categories"
                  f"[/bold green]")
    console.print(f"  Priority coverage: {len(covered_priority)}/{len(PRIORITY_CATEGORIES)}")
    if missing_priority:
        console.print(f"[yellow]Missing priority categories: "
                      f"{', '.join(missing_priority)}[/yellow]")
    if missing_categories:
        console.print(f"[yellow]Missing coverage for {len(missing_categories)} categories total. "
                      f"Run parameter schema for these categories to complete coverage.[/yellow]")


if __name__ == "__main__":
    cli()
