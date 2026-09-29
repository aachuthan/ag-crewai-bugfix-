"""Crew factory — creates specialized crews with structured output parsing.

Each crew wraps a single agent + task for one phase of the pipeline.
Tasks use output_json to enforce structured responses from the LLM,
eliminating fragile string-matching for result parsing.
"""

import re

from crewai import Crew, Process, Task

from src.agents.factory import (
    create_bug_analyst,
    create_code_investigator,
    create_code_reviewer,
    create_fix_developer,
    create_test_engineer,
)
from src.models.outputs import (
    FixOutput,
    InvestigationOutput,
    ReviewOutput,
    TestOutput,
    TriageOutput,
)


# ── Triage Crew ───────────────────────────────────────────────────

def create_triage_crew(repo_path: str, bug_context: str) -> Crew:
    """Create the Triage crew that classifies the bug.

    Agent: Bug Analyst (read-only)
    Output: TriageOutput (severity, category, summary, suspect files)
    """
    analyst = create_bug_analyst(repo_path)

    task = Task(
        description=(
            f"Analyze the following bug report and classify it.\n\n"
            f"## Bug Context\n{bug_context}\n\n"
            f"## Instructions\n"
            f"1. Read the bug description, error logs, and steps to reproduce.\n"
            f"2. Use the code_reader tool to read relevant files if mentioned.\n"
            f"3. Classify the bug severity: critical, high, medium, or low.\n"
            f"4. Categorize the bug type (e.g., logic_error, null_reference, "
            f"type_error, race_condition, config_error).\n"
            f"5. Write a clear triage summary.\n"
            f"6. List files that are likely involved.\n\n"
            f"Return your response as JSON matching the expected schema."
        ),
        expected_output=(
            "JSON with fields: severity, category, summary, initial_suspect_files"
        ),
        output_json=TriageOutput,
        agent=analyst,
    )

    return Crew(
        agents=[analyst],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


# ── Investigation Crew ────────────────────────────────────────────

def create_investigation_crew(
    repo_path: str,
    triage_summary: str,
    suspect_files: list[str],
) -> Crew:
    """Create the Investigation crew for root cause analysis.

    Agent: Code Investigator (read-only, extended thinking)
    Output: InvestigationOutput (root cause, affected files, snippets, approach)
    """
    investigator = create_code_investigator(repo_path)

    files_list = (
        "\n".join(f"- {f}" for f in suspect_files)
        if suspect_files
        else "- (none specified — search broadly)"
    )

    task = Task(
        description=(
            f"Investigate the root cause of the following triaged bug.\n\n"
            f"## Triage Summary\n{triage_summary}\n\n"
            f"## Suspect Files\n{files_list}\n\n"
            f"## Instructions\n"
            f"1. Use the code_reader tool to read the suspect files.\n"
            f"2. Search the codebase for related patterns using grep.\n"
            f"3. Trace the execution flow that leads to the bug.\n"
            f"4. Identify the EXACT root cause with file paths and line numbers.\n"
            f"5. Suggest how to fix it.\n\n"
            f"Return your response as JSON matching the expected schema."
        ),
        expected_output=(
            "JSON with fields: root_cause, affected_files, code_snippets, "
            "suggested_approach"
        ),
        output_json=InvestigationOutput,
        agent=investigator,
    )

    return Crew(
        agents=[investigator],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


# ── Fix Crew ──────────────────────────────────────────────────────

def create_fix_crew(
    repo_path: str,
    root_cause: str,
    affected_files: list[str],
    bug_title: str,
) -> Crew:
    """Create the Fix crew that implements the code fix.

    Agent: Fix Developer (read-write + git)
    Output: FixOutput (description, modified files, branch, diff)
    """
    developer = create_fix_developer(repo_path)

    # Sanitize bug title for branch name
    branch_name = "fix/" + re.sub(r"[^a-z0-9-]", "-", bug_title.lower())[:40]
    branch_name = re.sub(r"-+", "-", branch_name).strip("-")

    files_list = "\n".join(f"- {f}" for f in affected_files)

    task = Task(
        description=(
            f"Implement a fix for the identified bug.\n\n"
            f"## Root Cause\n{root_cause}\n\n"
            f"## Affected Files\n{files_list}\n\n"
            f"## Instructions\n"
            f"1. Use git_tool to create a new branch: '{branch_name}'\n"
            f"2. Use code_editor tool to implement the minimal fix.\n"
            f"3. Ensure the fix is surgical — only change what's necessary.\n"
            f"4. Use git_tool to stage changes: 'add .'\n"
            f"5. Use git_tool to commit: 'commit -m \"fix: {bug_title[:50]}\"'\n"
            f"6. Use git_tool to get the diff: 'diff main...HEAD'\n\n"
            f"Return your response as JSON matching the expected schema."
        ),
        expected_output=(
            "JSON with fields: fix_description, modified_files, git_branch, diff"
        ),
        output_json=FixOutput,
        agent=developer,
    )

    return Crew(
        agents=[developer],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


# ── Test Crew ─────────────────────────────────────────────────────

def create_test_crew(
    repo_path: str,
    fix_description: str,
    modified_files: list[str],
) -> Crew:
    """Create the Test crew that writes and runs tests.

    Agent: Test Engineer (read-write + git, needs to write test files and run them)
    Output: TestOutput (tests written, command, results, pass/fail)
    """
    tester = create_test_engineer(repo_path)

    files_list = (
        "\n".join(f"- {f}" for f in modified_files)
        if modified_files
        else "- (see fix description for context)"
    )

    task = Task(
        description=(
            f"Write regression tests and verify the bug fix.\n\n"
            f"## Fix Description\n{fix_description}\n\n"
            f"## Modified Files\n{files_list}\n\n"
            f"## Instructions\n"
            f"1. Use code_editor to read existing test files and understand "
            f"the testing patterns used in this project.\n"
            f"2. Write regression test(s) that:\n"
            f"   a. Would FAIL against the original buggy code.\n"
            f"   b. PASS with the fix applied.\n"
            f"3. Use code_editor to run the FULL test suite using the "
            f"project's test command.\n"
            f"4. Use git_tool to stage and commit: "
            f"'add .' then 'commit -m \"test: add regression tests\"'\n"
            f"5. Report: total tests, passed, failed, test file names.\n"
            f"6. IMPORTANT: If tests fail, you MUST provide the exact raw failure stack trace in 'test_execution_output'. Do not summarize it.\n\n"
            f"Return your response as JSON matching the expected schema."
        ),
        expected_output=(
            "JSON with fields: tests_written, test_command, "
            "test_execution_output, total_tests, passed, failed, all_passed"
        ),
        output_json=TestOutput,
        agent=tester,
    )

    return Crew(
        agents=[tester],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )


# ── Review Crew ───────────────────────────────────────────────────

def create_review_crew(
    repo_path: str,
    diff_output: str,
    fix_description: str,
    test_results: str,
) -> Crew:
    """Create the Review crew that acts as a quality gate.

    Agent: Code Reviewer (read-only, extended thinking)
    Output: ReviewOutput (verdict, comments, issues)
    """
    reviewer = create_code_reviewer(repo_path)

    # Truncate diff to avoid blowing context window
    truncated_diff = diff_output[:5000]
    if len(diff_output) > 5000:
        truncated_diff += "\n... (diff truncated, use code_reader to view full files)"

    task = Task(
        description=(
            f"Review the proposed bug fix for quality and correctness.\n\n"
            f"## Fix Description\n{fix_description}\n\n"
            f"## Code Diff\n```\n{truncated_diff}\n```\n\n"
            f"## Test Results\n{test_results}\n\n"
            f"## Review Checklist\n"
            f"1. Is the fix correct and complete?\n"
            f"2. Are there edge cases not handled?\n"
            f"3. Does the fix follow project coding conventions?\n"
            f"4. Could the fix introduce regressions?\n"
            f"5. Are the tests adequate?\n"
            f"6. Is the fix minimal (no unnecessary changes)?\n\n"
            f"Provide verdict: 'approved', 'needs_changes', or 'rejected'.\n\n"
            f"Return your response as JSON matching the expected schema."
        ),
        expected_output=(
            "JSON with fields: verdict, comments, issues_found"
        ),
        output_json=ReviewOutput,
        agent=reviewer,
    )

    return Crew(
        agents=[reviewer],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
