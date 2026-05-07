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


if __name__ == "__main__":
    cli()
