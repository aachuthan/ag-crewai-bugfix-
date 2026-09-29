"""Tests for the custom tools: ClaudeCodeReadTool, ClaudeCodeEditTool, GitTool."""

import pytest

from src.tools.git_tool import GitTool, ALLOWED_GIT_COMMANDS


# ── GitTool Tests ─────────────────────────────────────────────────

class TestGitTool:
    """Tests for GitTool safety and functionality."""

    def test_allowed_commands_execute(self, sample_git_repo):
        """Allowed git subcommands should execute successfully."""
        tool = GitTool(repo_path=str(sample_git_repo))
        result = tool._run("status")
        assert "nothing to commit" in result.lower() or "clean" in result.lower()

    def test_blocked_commands_rejected(self, sample_git_repo):
        """Disallowed git subcommands should be rejected."""
        tool = GitTool(repo_path=str(sample_git_repo))

        for cmd in ["push", "pull", "fetch", "remote", "rebase", "rm", "clean"]:
            result = tool._run(cmd)
            assert "not allowed" in result.lower(), f"'{cmd}' should be blocked"

    def test_shell_injection_blocked(self, sample_git_repo):
        """Shell injection attempts via semicolons should be blocked."""
        tool = GitTool(repo_path=str(sample_git_repo))

        # The shlex.split + shell=False approach means semicolons
        # are just passed as arguments to git, not as shell operators
        result = tool._run("status; echo HACKED")
        # "status;" is not a valid git argument, but more importantly
        # "echo HACKED" should NOT execute as a separate command
        assert "HACKED" not in result

    def test_empty_command_rejected(self, sample_git_repo):
        """Empty commands should return an error."""
        tool = GitTool(repo_path=str(sample_git_repo))
        result = tool._run("")
        assert "error" in result.lower()

    def test_git_log(self, sample_git_repo):
        """git log should work and show the initial commit."""
        tool = GitTool(repo_path=str(sample_git_repo))
        result = tool._run("log --oneline -1")
        assert "initial commit" in result.lower()

    def test_branch_creation(self, sample_git_repo):
        """Creating a branch should succeed."""
        tool = GitTool(repo_path=str(sample_git_repo))
        result = tool._run("checkout -b test-branch")
        assert "test-branch" in result or "Switched" in result

    def test_diff_on_clean_repo(self, sample_git_repo):
        """git diff on a clean repo should produce no output."""
        tool = GitTool(repo_path=str(sample_git_repo))
        result = tool._run("diff")
        assert result == "(no output)"

    def test_allowed_commands_set(self):
        """Verify the allowlist contains expected safe commands."""
        assert "checkout" in ALLOWED_GIT_COMMANDS
        assert "commit" in ALLOWED_GIT_COMMANDS
        assert "diff" in ALLOWED_GIT_COMMANDS
        assert "push" not in ALLOWED_GIT_COMMANDS
        assert "remote" not in ALLOWED_GIT_COMMANDS


# ── ClaudeCodeTool Tests ──────────────────────────────────────────

class TestClaudeCodeReadTool:
    """Tests for ClaudeCodeReadTool with mocked SDK."""

    def test_read_tool_returns_response(self, sample_git_repo, mock_claude_code):
        """The read tool should return the mocked response."""
        from src.tools.claude_code_tool import ClaudeCodeReadTool

        mock_claude_code.response = "Found 3 functions in calculator.py"

        tool = ClaudeCodeReadTool(repo_path=str(sample_git_repo))
        result = tool._run("List all functions in calculator.py")

        assert "Found 3 functions" in result

    def test_read_tool_tracks_calls(self, sample_git_repo, mock_claude_code):
        """The read tool should pass the prompt to the SDK."""
        from src.tools.claude_code_tool import ClaudeCodeReadTool

        tool = ClaudeCodeReadTool(repo_path=str(sample_git_repo))
        tool._run("Analyze the code")

        assert len(mock_claude_code.calls) == 1
        assert "Analyze the code" in mock_claude_code.calls[0]["prompt"]


class TestClaudeCodeEditTool:
    """Tests for ClaudeCodeEditTool with mocked SDK."""

    def test_edit_tool_returns_response(self, sample_git_repo, mock_claude_code):
        """The edit tool should return the mocked response."""
        from src.tools.claude_code_tool import ClaudeCodeEditTool

        mock_claude_code.response = "File modified successfully"

        tool = ClaudeCodeEditTool(repo_path=str(sample_git_repo))
        result = tool._run("Add error handling to divide function")

        assert "File modified" in result
