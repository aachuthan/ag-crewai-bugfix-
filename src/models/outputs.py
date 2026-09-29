"""Structured output models for crew task results.

These are passed to Task(output_json=...) so CrewAI enforces
the LLM returns parseable JSON matching these schemas — instead
of free-text that requires fragile string parsing.
"""

from pydantic import BaseModel, Field


class TriageOutput(BaseModel):
    """Expected structured output from the Triage crew."""

    severity: str = Field(
        description="One of: critical, high, medium, low"
    )
    category: str = Field(
        description=(
            "Bug type: logic_error, null_reference, type_error, "
            "race_condition, config_error, etc."
        )
    )
    summary: str = Field(description="2-3 sentence triage analysis")
    initial_suspect_files: list[str] = Field(
        default_factory=list,
        description="File paths likely involved in the bug",
    )


class InvestigationOutput(BaseModel):
    """Expected structured output from the Investigation crew."""

    root_cause: str = Field(
        description="Precise description of what's wrong and why"
    )
    affected_files: list[str] = Field(
        description="List of files with line numbers"
    )
    code_snippets: list[str] = Field(
        default_factory=list,
        description="Relevant code sections",
    )
    suggested_approach: str = Field(description="How to fix it")


class FixOutput(BaseModel):
    """Expected structured output from the Fix crew."""

    fix_description: str = Field(description="What was changed and why")
    modified_files: list[str] = Field(
        description="List of changed file paths"
    )
    git_branch: str = Field(
        description="Branch name created for the fix"
    )
    diff: str = Field(description="The git diff output")


class TestOutput(BaseModel):
    """Expected structured output from the Test crew."""

    tests_written: list[str] = Field(
        description="List of new test file paths"
    )
    test_command: str = Field(
        description="Exact command used to run tests"
    )
    test_execution_output: str = Field(
        description="Raw output or stack trace from the test execution. If tests fail, do NOT summarize — provide the exact failure output."
    )
    total_tests: int = Field(default=0)
    passed: int = Field(default=0)
    failed: int = Field(default=0)
    all_passed: bool = Field(description="True if all tests passed")


class ReviewOutput(BaseModel):
    """Expected structured output from the Review crew."""

    verdict: str = Field(
        description="One of: approved, needs_changes, rejected"
    )
    comments: str = Field(description="Detailed review feedback")
    issues_found: list[str] = Field(
        default_factory=list,
        description="Specific issues found, if any",
    )
