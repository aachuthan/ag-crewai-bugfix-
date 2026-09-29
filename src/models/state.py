"""State models for the bug-fix pipeline.

BugReport: the user-provided input describing the bug.
BugFixState: the accumulator that carries data through every phase of the Flow.
"""

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class BugSeverity(str, Enum):
    """Bug severity levels for triage classification."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewVerdict(str, Enum):
    """Possible outcomes from the code review phase."""
    APPROVED = "approved"
    NEEDS_CHANGES = "needs_changes"
    REJECTED = "rejected"


class BugReport(BaseModel):
    """Input: The bug context provided by the user."""

    title: str = Field(description="Short bug title")
    description: str = Field(description="Detailed bug description")
    steps_to_reproduce: str = Field(default="", description="Steps to reproduce")
    error_logs: str = Field(
        default="", description="Relevant error logs / stack traces"
    )
    affected_files: list[str] = Field(
        default_factory=list, description="Known affected files"
    )
    repository_path: str = Field(description="Absolute path to the repository")

    @field_validator("repository_path")
    @classmethod
    def validate_repo_path(cls, v: str) -> str:
        """Ensure the repository path exists and is a git repo."""
        p = Path(v)
        if not p.exists():
            raise ValueError(f"Repository path does not exist: {v}")
        if not p.is_dir():
            raise ValueError(f"Repository path is not a directory: {v}")
        if not (p / ".git").exists():
            raise ValueError(f"Not a git repository (no .git found): {v}")
        return str(p.resolve())


class BugFixState(BaseModel):
    """Flow state that accumulates results from each crew.

    Fields are populated progressively as each phase completes.
    The Flow orchestrator reads/writes these fields to pass context
    between crews.
    """

    # ── Input ──────────────────────────────────────────────────────
    bug_report: BugReport

    # ── Triage output ──────────────────────────────────────────────
    severity: Optional[BugSeverity] = None
    category: Optional[str] = None
    triage_summary: Optional[str] = None
    suspect_files: list[str] = Field(default_factory=list)

    # ── Investigation output ───────────────────────────────────────
    root_cause: Optional[str] = None
    affected_files_discovered: list[str] = Field(default_factory=list)
    suggested_approach: Optional[str] = None

    # ── Fix output ─────────────────────────────────────────────────
    fix_description: Optional[str] = None
    modified_files: list[str] = Field(default_factory=list)
    git_branch: Optional[str] = None
    diff_output: Optional[str] = None

    # ── Test output ────────────────────────────────────────────────
    tests_written: list[str] = Field(default_factory=list)
    test_results: Optional[str] = None
    tests_passed: bool = False

    # ── Review output ──────────────────────────────────────────────
    review_verdict: Optional[ReviewVerdict] = None
    review_comments: Optional[str] = None

    # ── Flow control ───────────────────────────────────────────────
    current_iteration: int = 0
    max_iterations: int = 3
    error_log: list[str] = Field(default_factory=list)
