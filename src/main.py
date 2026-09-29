"""CLI entry point for the AI Development Team bug-fix pipeline.

Usage:
    bugfix fix --repo /path/to/repo --title "Bug title" --description "Details"
    bugfix fix-from-file --repo /path/to/repo --bug-file bug.json
    bugfix --verbose fix ...
"""

import json
import logging
import sys

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from src.flows.bug_fix_flow import BugFixFlow
from src.models.state import BugFixState, BugReport, ReviewVerdict
from src.observability.tracer import init_observability, flush_traces, get_trace_url


load_dotenv()
console = Console()


# ── Helpers ───────────────────────────────────────────────────────

def _setup_logging(verbose: bool):
    """Configure logging — DEBUG if verbose, INFO otherwise."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _report_results(state: BugFixState, trace_url: str = None):
    """Print the final results of a bug-fix pipeline run."""
    console.print()

    if state.review_verdict == ReviewVerdict.APPROVED:
        panel_content = (
            f"[bold green]✅ Bug Fix Complete![/bold green]\n\n"
            f"[bold]Branch:[/bold] {state.git_branch or 'N/A'}\n"
            f"[bold]Files Changed:[/bold] {', '.join(state.modified_files) or 'N/A'}\n"
            f"[bold]Tests Written:[/bold] {', '.join(state.tests_written) or 'N/A'}\n"
            f"[bold]All Tests Pass:[/bold] {'✅ Yes' if state.tests_passed else '❌ No'}\n"
            f"[bold]Iterations:[/bold] {state.current_iteration + 1}"
        )
        if trace_url:
            panel_content += f"\n\n[bold]📊 View Trace:[/bold] [link={trace_url}]{trace_url}[/link]"
        console.print(Panel.fit(panel_content, title="🎉 Results"))
    else:
        verdict = state.review_verdict.value if state.review_verdict else "N/A"
        panel_content = (
            f"[bold yellow]⚠️ Bug Fix Incomplete[/bold yellow]\n\n"
            f"[bold]Verdict:[/bold] {verdict}\n"
            f"[bold]Iterations Used:[/bold] "
            f"{state.current_iteration}/{state.max_iterations}\n"
            f"[bold]Last Comments:[/bold] "
            f"{(state.review_comments or 'N/A')[:500]}\n"
            f"[bold]Errors:[/bold] {'; '.join(state.error_log) or 'None'}"
        )
        if trace_url:
            panel_content += f"\n\n[bold]📊 View Trace:[/bold] [link={trace_url}]{trace_url}[/link]"
        console.print(Panel.fit(panel_content, title="⚠️ Results"))

    # Print error log if any
    if state.error_log:
        console.print("\n[dim]Error log:[/dim]")
        for err in state.error_log:
            console.print(f"  [red]• {err}[/red]")


def _run_pipeline(bug_report: BugReport):
    """Create and run the bug-fix flow, then report results."""
    if init_observability():
        console.print("[dim ℹ️] Observability enabled. Tracing to Langfuse...[/dim]")

    console.print(Panel.fit(
        f"[bold blue]🐛 Bug Fix Pipeline[/bold blue]\n\n"
        f"[bold]Title:[/bold] {bug_report.title}\n"
        f"[bold]Repository:[/bold] {bug_report.repository_path}\n"
        f"[bold]Affected Files:[/bold] "
        f"{', '.join(bug_report.affected_files) or 'Unknown'}",
        title="Starting AI Development Team",
    ))

    initial_state = BugFixState(bug_report=bug_report)
    flow = BugFixFlow(state=initial_state)
    trace_url = ""

    try:
        flow.kickoff()
        trace_url = get_trace_url()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Pipeline interrupted by user.[/bold yellow]")
        trace_url = get_trace_url()
        _report_results(flow.state, trace_url)
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Pipeline crashed: {e}[/bold red]")
        trace_url = get_trace_url()
        _report_results(flow.state, trace_url)
        sys.exit(1)
    finally:
        flush_traces()

    _report_results(flow.state, trace_url)


# ── CLI Commands ──────────────────────────────────────────────────

@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool):
    """AI Development Team — Bug Fix Pipeline.

    Orchestrates a multi-agent team (Bug Analyst, Code Investigator,
    Fix Developer, Test Engineer, Code Reviewer) to autonomously
    diagnose and fix bugs in a repository.
    """
    _setup_logging(verbose)


@cli.command()
@click.option("--repo", required=True, help="Path to the target repository")
@click.option("--title", required=True, help="Bug title")
@click.option("--description", required=True, help="Bug description")
@click.option("--steps", default="", help="Steps to reproduce")
@click.option("--logs", default="", help="Error logs or stack traces")
@click.option(
    "--files", default="",
    help="Comma-separated list of affected files",
)
def fix(
    repo: str,
    title: str,
    description: str,
    steps: str,
    logs: str,
    files: str,
):
    """Run the full bug-fix pipeline with inline arguments."""
    affected_files = [f.strip() for f in files.split(",") if f.strip()]

    try:
        bug_report = BugReport(
            title=title,
            description=description,
            steps_to_reproduce=steps,
            error_logs=logs,
            affected_files=affected_files,
            repository_path=repo,
        )
    except ValueError as e:
        console.print(f"[bold red]Invalid input: {e}[/bold red]")
        sys.exit(1)

    _run_pipeline(bug_report)


@cli.command()
@click.option("--repo", required=True, help="Path to the target repository")
@click.option(
    "--bug-file", required=True,
    help="Path to a JSON file with bug context",
)
def fix_from_file(repo: str, bug_file: str):
    """Run the bug-fix pipeline from a JSON bug report file.

    The JSON file should have fields: title, description,
    and optionally: steps_to_reproduce, error_logs, affected_files.
    """
    try:
        with open(bug_file) as f:
            data = json.load(f)
    except FileNotFoundError:
        console.print(f"[bold red]Bug file not found: {bug_file}[/bold red]")
        sys.exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[bold red]Invalid JSON in bug file: {e}[/bold red]")
        sys.exit(1)

    data["repository_path"] = repo

    try:
        bug_report = BugReport(**data)
    except ValueError as e:
        console.print(f"[bold red]Invalid bug report: {e}[/bold red]")
        sys.exit(1)

    _run_pipeline(bug_report)


@cli.command()
@click.option("--repo", required=True, help="Path to the target repository")
@click.option(
    "--issue", required=True,
    help="Jira issue key (e.g., PROJ-123, BUG-456)",
)
@click.option(
    "--no-comments", is_flag=True,
    help="Exclude Jira comments from the bug context",
)
def fix_from_jira(repo: str, issue: str, no_comments: bool):
    """Run the bug-fix pipeline from a Jira issue.

    Fetches the issue from Jira (summary, description, comments),
    extracts file paths and error logs, and feeds them into the pipeline.

    Requires: pip install ag-crewai-bugfix[jira]

    Configure in .env:
        JIRA_URL=https://your-org.atlassian.net
        JIRA_EMAIL=your-email@company.com
        JIRA_API_TOKEN=your-api-token
    """
    try:
        from src.integrations.jira_client import jira_issue_to_bug_report
    except ImportError as e:
        console.print(
            f"[bold red]Jira integration not available: {e}[/bold red]\n"
            f"Install with: pip install ag-crewai-bugfix[jira]"
        )
        sys.exit(1)

    console.print(f"[bold blue]🔗 Fetching Jira issue: {issue}[/bold blue]")

    try:
        bug_report = jira_issue_to_bug_report(
            issue_key=issue,
            repository_path=repo,
            include_comments=not no_comments,
        )
    except ValueError as e:
        console.print(f"[bold red]Configuration error: {e}[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Failed to fetch Jira issue: {e}[/bold red]")
        sys.exit(1)

    # Show what was fetched before running the pipeline
    console.print(Panel.fit(
        f"[bold green]✅ Jira Issue Fetched[/bold green]\n\n"
        f"[bold]Title:[/bold] {bug_report.title}\n"
        f"[bold]Description:[/bold] {bug_report.description[:300]}...\n"
        f"[bold]Affected Files:[/bold] "
        f"{', '.join(bug_report.affected_files) or 'None detected'}\n"
        f"[bold]Has Error Logs:[/bold] "
        f"{'Yes' if bug_report.error_logs else 'No'}",
        title=f"📋 {issue}",
    ))

    _run_pipeline(bug_report)


@cli.command()
@click.option(
    "--issue", required=True,
    help="Jira issue key (e.g., PROJ-123)",
)
def preview_jira(issue: str):
    """Preview what the pipeline would see from a Jira issue (dry run).

    Fetches and displays the issue details without running the pipeline.
    Useful for verifying Jira connectivity and inspecting how the issue
    maps to a BugReport.
    """
    try:
        from src.integrations.jira_client import fetch_jira_issue, _guess_affected_files
    except ImportError as e:
        console.print(
            f"[bold red]Jira integration not available: {e}[/bold red]\n"
            f"Install with: pip install ag-crewai-bugfix[jira]"
        )
        sys.exit(1)

    console.print(f"[bold blue]🔗 Fetching Jira issue: {issue}[/bold blue]")

    try:
        data = fetch_jira_issue(issue)
    except Exception as e:
        console.print(f"[bold red]Failed: {e}[/bold red]")
        sys.exit(1)

    # Extract files
    full_text = f"{data['description']}\n{data['comments']}"
    files = _guess_affected_files(full_text)

    console.print(Panel.fit(
        f"[bold]{data['key']}[/bold]: {data['summary']}\n\n"
        f"[bold]Type:[/bold] {data['issue_type']}\n"
        f"[bold]Priority:[/bold] {data['priority']}\n"
        f"[bold]Status:[/bold] {data['status']}\n"
        f"[bold]Reporter:[/bold] {data['reporter']}\n"
        f"[bold]Assignee:[/bold] {data['assignee']}\n"
        f"[bold]Labels:[/bold] {', '.join(data['labels']) or 'None'}\n"
        f"[bold]Components:[/bold] {', '.join(data['components']) or 'None'}",
        title="📋 Issue Details",
    ))

    if data['description']:
        console.print(Panel(
            data['description'][:2000],
            title="📝 Description",
        ))

    if files:
        console.print(Panel(
            "\n".join(f"  • {f}" for f in files),
            title="📁 Detected Files",
        ))
    else:
        console.print("[dim]No file paths detected in issue text.[/dim]")

    if data['comments']:
        console.print(Panel(
            data['comments'][:2000],
            title="💬 Comments",
        ))

    console.print(
        f"\n[bold green]Ready to run:[/bold green] "
        f"bugfix fix-from-jira --repo /path/to/repo --issue {issue}"
    )


if __name__ == "__main__":
    cli()
