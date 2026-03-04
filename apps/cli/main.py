"""CLI entry point for NexusDev.

Provides commands for:
- Creating and managing sessions
- Running workflow stages
- Approving/rejecting stages
- Viewing status and artifacts
"""

import asyncio
from uuid import UUID

import typer
from core.domain.session import SessionStatus
from core.services.approval_service import ApprovalService
from core.services.session_service import SessionService
from core.storage.database import create_database
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

app = typer.Typer(
    name="nexusdev",
    help="NexusDev - Multi-Agent Automated Development System",
    no_args_is_help=True,
)
console = Console()

# Global database instance
_db = None


async def get_db():
    """Get or create database instance."""
    global _db
    if _db is None:
        _db = create_database()
        await _db.create_tables()
    return _db


@app.command()
def version():
    """Show version information."""
    console.print(
        Panel.fit(
            "[bold blue]NexusDev[/bold blue] v0.1.0\n"
            "Multi-Agent Automated Development System\n"
            "Powered by LangGraph + MetaSOP",
            title="Version",
        )
    )


@app.command()
def create(
    name: str = typer.Argument(..., help="Session name"),
    requirement: str = typer.Argument(..., help="Development requirement"),
    description: str = typer.Option("", "--desc", "-d", help="Session description"),
    user: str = typer.Option("cli-user", "--user", "-u", help="Creating user"),
):
    """Create a new development session."""

    async def _create():
        db = await get_db()
        service = SessionService(db)

        session = await service.create_session(
            name=name,
            requirement=requirement,
            description=description,
            created_by=user,
        )

        console.print(
            Panel.fit(
                f"[green]Session created successfully![/green]\n\n"
                f"ID: [cyan]{session.id}[/cyan]\n"
                f"Name: [bold]{session.name}[/bold]\n"
                f"Status: [yellow]{session.status.value}[/yellow]",
                title="Session Created",
            )
        )

    asyncio.run(_create())


@app.command()
def status(
    session_id: str = typer.Argument(..., help="Session ID"),
):
    """Get session status."""

    async def _status():
        db = await get_db()
        service = SessionService(db)

        try:
            uuid = UUID(session_id)
        except ValueError:
            console.print("[red]Invalid session ID format[/red]")
            raise typer.Exit(1) from None

        result = await service.get_status(uuid)

        if "error" in result:
            console.print(f"[red]Error: {result['error']}[/red]")
            raise typer.Exit(1)

        # Create status table
        table = Table(title=f"Session Status: {result['name']}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("ID", result["session_id"])
        table.add_row("Status", result["status"])
        table.add_row("Current Stage", result["current_stage_id"] or "None")
        table.add_row("Completed Stages", str(len(result["completed_stages"])))
        table.add_row("Created", result["created_at"])
        table.add_row("Updated", result["updated_at"])

        console.print(table)

        # Show stages
        if result["stages"]:
            stage_table = Table(title="Stages")
            stage_table.add_column("Name", style="cyan")
            stage_table.add_column("Type", style="blue")
            stage_table.add_column("Status", style="yellow")
            stage_table.add_column("Agent", style="green")

            for stage in result["stages"]:
                stage_table.add_row(
                    stage["name"],
                    stage["type"],
                    stage["status"],
                    stage["agent"],
                )

            console.print(stage_table)

    asyncio.run(_status())


@app.command()
def list(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum results"),
):
    """List sessions."""

    async def _list():
        db = await get_db()
        service = SessionService(db)

        session_status = None
        if status:
            try:
                session_status = SessionStatus(status)
            except ValueError:
                console.print(f"[red]Invalid status: {status}[/red]")
                raise typer.Exit(1) from None

        sessions = await service.list_sessions(
            status=session_status,
            limit=limit,
        )

        if not sessions:
            console.print("[yellow]No sessions found[/yellow]")
            return

        table = Table(title="Sessions")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Created", style="blue")

        for session in sessions:
            table.add_row(
                str(session.id)[:8] + "...",
                session.name,
                session.status.value,
                session.created_at.strftime("%Y-%m-%d %H:%M"),
            )

        console.print(table)

    asyncio.run(_list())


@app.command()
def run(
    session_id: str = typer.Argument(..., help="Session ID"),
    stage: str | None = typer.Option(None, "--stage", help="Specific stage to run"),
    mode: str | None = typer.Option(
        None,
        "--mode",
        help="Workflow mode: single_stage or full_graph",
    ),
):
    """Run a workflow stage."""

    async def _run():
        db = await get_db()
        service = SessionService(db)

        try:
            uuid = UUID(session_id)
        except ValueError:
            console.print("[red]Invalid session ID format[/red]")
            raise typer.Exit(1) from None

        result = await service.run_stage(uuid, stage, mode)

        if "error" in result:
            console.print(f"[red]Error: {result['error']}[/red]")
            raise typer.Exit(1)

        if result.get("mode") == "full_graph":
            console.print(
                Panel.fit(
                    f"[green]Workflow executed (full graph)![/green]\n\n"
                    f"Session ID: [cyan]{result['session_id']}[/cyan]\n"
                    f"Status: [bold]{result['status']}[/bold]\n"
                    f"Current Stage: [blue]{result.get('current_stage') or 'N/A'}[/blue]\n"
                    f"Stage Status: [yellow]{result.get('stage_status', 'N/A')}[/yellow]",
                    title="Workflow Executed",
                )
            )
            return

        console.print(
            Panel.fit(
                f"[green]Stage started successfully![/green]\n\n"
                f"Stage ID: [cyan]{result['stage_id']}[/cyan]\n"
                f"Stage Name: [bold]{result['stage_name']}[/bold]\n"
                f"Stage Type: [blue]{result['stage_type']}[/blue]\n"
                f"Requires Approval: [yellow]{'Yes' if result['requires_approval'] else 'No'}[/yellow]",
                title="Stage Started",
            )
        )

    asyncio.run(_run())


@app.command()
def approve(
    session_id: str = typer.Argument(..., help="Session ID"),
    stage_id: str = typer.Argument(..., help="Stage ID"),
    message: str = typer.Option("", "--message", "-m", help="Approval message"),
    user: str = typer.Option("cli-user", "--user", "-u", help="Approving user"),
):
    """Approve a pending stage."""

    async def _approve():
        db = await get_db()
        service = SessionService(db)

        try:
            session_uuid = UUID(session_id)
            stage_uuid = UUID(stage_id)
        except ValueError:
            console.print("[red]Invalid ID format[/red]")
            raise typer.Exit(1) from None

        result = await service.approve_stage(
            session_uuid,
            stage_uuid,
            user,
            message,
        )

        if "error" in result:
            console.print(f"[red]Error: {result['error']}[/red]")
            raise typer.Exit(1)

        console.print(
            Panel.fit(
                f"[green]Stage approved successfully![/green]\n\n"
                f"Approved by: [cyan]{result['approved_by']}[/cyan]\n"
                f"Message: [italic]{result['message'] or 'N/A'}[/italic]",
                title="Approved",
            )
        )

    asyncio.run(_approve())


@app.command()
def reject(
    session_id: str = typer.Argument(..., help="Session ID"),
    stage_id: str = typer.Argument(..., help="Stage ID"),
    reason: str = typer.Option(..., "--reason", "-r", help="Rejection reason"),
    user: str = typer.Option("cli-user", "--user", "-u", help="Rejecting user"),
):
    """Reject a pending stage."""

    async def _reject():
        db = await get_db()
        service = SessionService(db)

        try:
            session_uuid = UUID(session_id)
            stage_uuid = UUID(stage_id)
        except ValueError:
            console.print("[red]Invalid ID format[/red]")
            raise typer.Exit(1) from None

        result = await service.reject_stage(
            session_uuid,
            stage_uuid,
            user,
            reason,
        )

        if "error" in result:
            console.print(f"[red]Error: {result['error']}[/red]")
            raise typer.Exit(1)

        console.print(
            Panel.fit(
                f"[red]Stage rejected[/red]\n\n"
                f"Rejected by: [cyan]{result['rejected_by']}[/cyan]\n"
                f"Reason: [italic]{result['reason'] or 'N/A'}[/italic]",
                title="Rejected",
            )
        )

    asyncio.run(_reject())


@app.command()
def approvals(
    session_id: str | None = typer.Option(None, "--session", "-s", help="Filter by session"),
):
    """List pending approvals."""

    async def _approvals():
        db = await get_db()
        service = ApprovalService(db)

        session_uuid = None
        if session_id:
            try:
                session_uuid = UUID(session_id)
            except ValueError:
                console.print("[red]Invalid session ID format[/red]")
                raise typer.Exit(1) from None

        approvals = await service.get_pending_approvals(session_uuid)

        if not approvals:
            console.print("[yellow]No pending approvals[/yellow]")
            return

        table = Table(title="Pending Approvals")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Session", style="blue")
        table.add_column("Stage", style="green")
        table.add_column("Requested By", style="yellow")
        table.add_column("Time Remaining", style="magenta")

        for approval in approvals:
            remaining = approval.time_remaining()
            remaining_str = str(remaining).split(".")[0] if remaining else "N/A"

            table.add_row(
                str(approval.id)[:8] + "...",
                str(approval.session_id)[:8] + "...",
                approval.stage_name,
                approval.requested_by,
                remaining_str,
            )

        console.print(table)

    asyncio.run(_approvals())


@app.command()
def workflow():
    """Show the default workflow diagram."""
    tree = Tree("[bold blue]Development Workflow[/bold blue]")

    req = tree.add("[cyan]1. Requirement Analysis[/cyan] (PM Agent)")
    req.add("[dim]Output: PRD, User Stories[/dim]")

    design = tree.add("[cyan]2. System Design[/cyan] (Architect Agent)")
    design.add("[dim]Output: Architecture, API Spec, DB Schema[/dim]")
    design.add("[yellow]↳ HITL Checkpoint: Human Approval Required[/yellow]")

    code = tree.add("[cyan]3. Coding[/cyan] (Coder Agent)")
    code.add("[dim]Output: Source Code, Configuration[/dim]")

    review = tree.add("[cyan]4. Code Review[/cyan] (Reviewer Agent)")
    review.add("[dim]Output: Review Report[/dim]")
    review.add("[dim]↳ Loop back if changes needed[/dim]")

    test = tree.add("[cyan]5. Testing[/cyan] (Tester Agent)")
    test.add("[dim]Output: Test Cases, Coverage Report[/dim]")
    test.add("[dim]↳ Loop back if tests fail[/dim]")

    tree.add("[green]6. Complete[/green]")

    console.print(Panel(tree, title="MVP Workflow"))


def main():
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
