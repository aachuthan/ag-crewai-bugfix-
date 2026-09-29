"""Tests for state models, output models, and flow parsing logic."""

import json

import pytest

from src.models.state import BugReport, BugFixState, BugSeverity, ReviewVerdict
from src.models.outputs import (
    TriageOutput,
    InvestigationOutput,
    FixOutput,
    TestOutput,
    ReviewOutput,
)
from src.flows.bug_fix_flow import _safe_parse_json


# ── State Model Tests ─────────────────────────────────────────────

class TestBugReport:
    """Tests for BugReport validation."""

    def test_valid_repo_path(self, sample_git_repo):
        """Should accept a valid git repo path."""
        report = BugReport(
            title="Test",
            description="Test bug",
            repository_path=str(sample_git_repo),
        )
        assert report.repository_path == str(sample_git_repo.resolve())

    def test_nonexistent_path_rejected(self):
        """Should reject paths that don't exist."""
        with pytest.raises(ValueError, match="does not exist"):
            BugReport(
                title="Test",
                description="Test",
                repository_path="/nonexistent/path/to/repo",
            )

    def test_non_git_path_rejected(self, tmp_path):
        """Should reject directories that aren't git repos."""
        with pytest.raises(ValueError, match="Not a git repository"):
            BugReport(
                title="Test",
                description="Test",
                repository_path=str(tmp_path),
            )

    def test_default_values(self, sample_git_repo):
        """Optional fields should have sensible defaults."""
        report = BugReport(
            title="Test",
            description="Test bug",
            repository_path=str(sample_git_repo),
        )
        assert report.steps_to_reproduce == ""
        assert report.error_logs == ""
        assert report.affected_files == []


class TestBugFixState:
    """Tests for BugFixState initialization."""

    def test_initial_state(self, sample_bug_report):
        """Fresh state should have null outputs and zero iterations."""
        state = BugFixState(bug_report=sample_bug_report)

        assert state.severity is None
        assert state.root_cause is None
        assert state.fix_description is None
        assert state.tests_passed is False
        assert state.review_verdict is None
        assert state.current_iteration == 0
        assert state.error_log == []


# ── Output Model Tests ────────────────────────────────────────────

class TestOutputModels:
    """Test that output models can be instantiated from JSON."""

    def test_triage_output(self):
        data = {
            "severity": "high",
            "category": "null_reference",
            "summary": "NPE when discount is zero",
            "initial_suspect_files": ["payment.py"],
        }
        output = TriageOutput(**data)
        assert output.severity == "high"
        assert output.initial_suspect_files == ["payment.py"]

    def test_investigation_output(self):
        data = {
            "root_cause": "Missing null check on line 42",
            "affected_files": ["payment.py:42"],
            "code_snippets": ["if discount: ..."],
            "suggested_approach": "Add null check before accessing discount",
        }
        output = InvestigationOutput(**data)
        assert "null check" in output.root_cause

    def test_fix_output(self):
        data = {
            "fix_description": "Added null check",
            "modified_files": ["payment.py"],
            "git_branch": "fix/null-check",
            "diff": "+ if discount is not None:",
        }
        output = FixOutput(**data)
        assert output.git_branch == "fix/null-check"

    def test_test_output(self):
        data = {
            "tests_written": ["test_payment.py"],
            "test_command": "pytest",
            "test_execution_output": "5 passed, 0 failed",
            "total_tests": 5,
            "passed": 5,
            "failed": 0,
            "all_passed": True,
        }
        output = TestOutput(**data)
        assert output.all_passed is True

    def test_review_output(self):
        data = {
            "verdict": "approved",
            "comments": "Clean fix, good tests",
            "issues_found": [],
        }
        output = ReviewOutput(**data)
        assert output.verdict == "approved"


# ── JSON Parsing Tests ────────────────────────────────────────────

class TestSafeParseJson:
    """Tests for the _safe_parse_json helper in the flow."""

    def test_parse_dict(self):
        """Should parse a dict directly."""
        data = {"severity": "high", "category": "logic_error",
                "summary": "test", "initial_suspect_files": []}
        result = _safe_parse_json(data, TriageOutput)
        assert result is not None
        assert result.severity == "high"

    def test_parse_json_string(self):
        """Should parse a JSON string."""
        data = json.dumps({
            "severity": "low", "category": "config_error",
            "summary": "Config issue", "initial_suspect_files": ["config.py"],
        })
        result = _safe_parse_json(data, TriageOutput)
        assert result is not None
        assert result.category == "config_error"

    def test_parse_markdown_fenced_json(self):
        """Should handle JSON wrapped in markdown code fences."""
        data = (
            "Here is my analysis:\n"
            "```json\n"
            '{"severity": "critical", "category": "null_reference", '
            '"summary": "NPE", "initial_suspect_files": []}\n'
            "```\n"
            "That's my report."
        )
        result = _safe_parse_json(data, TriageOutput)
        assert result is not None
        assert result.severity == "critical"

    def test_parse_invalid_returns_none(self):
        """Should return None for unparseable text."""
        result = _safe_parse_json("This is just plain text", TriageOutput)
        assert result is None

    def test_parse_partial_json_returns_none(self):
        """Should return None for partial/broken JSON."""
        result = _safe_parse_json('{"severity": "high"', TriageOutput)
        assert result is None
