"""Shared test fixtures with mocked Claude Code SDK and sample repos."""

import os
import subprocess

import pytest


@pytest.fixture
def mock_claude_code(monkeypatch):
    """Mock the claude-agent-sdk query function.

    Returns a fake async generator that yields a message with
    configurable content. Use mock_claude_code.response to set
    the response text before each test.
    """
    class _MockController:
        def __init__(self):
            self.response = '{"result": "mocked response"}'
            self.calls = []

        async def fake_query(self, prompt, options=None):
            self.calls.append({"prompt": prompt, "options": options})

            class FakeMessage:
                pass

            msg = FakeMessage()
            msg.content = self.response
            yield msg

    controller = _MockController()

    # Patch at the module where it's imported
    monkeypatch.setattr(
        "src.tools.claude_code_tool.query",
        lambda prompt, options=None: controller.fake_query(prompt, options),
    )

    return controller


@pytest.fixture
def sample_git_repo(tmp_path):
    """Create a minimal git repository for testing.

    Returns the path to the repository.
    """
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Create a simple buggy file
    (repo / "calculator.py").write_text(
        'def divide(a, b):\n'
        '    """Divide a by b."""\n'
        '    return a / b\n'
    )

    # Create a simple test file
    (repo / "test_calculator.py").write_text(
        'from calculator import divide\n'
        '\n'
        'def test_divide():\n'
        '    assert divide(10, 2) == 5\n'
    )

    # Init git repo
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, env=env)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo, capture_output=True, env=env,
    )

    return repo


@pytest.fixture
def sample_bug_report(sample_git_repo):
    """Create a BugReport pointing at the sample git repo."""
    from src.models.state import BugReport

    return BugReport(
        title="Division by zero",
        description="divide(1, 0) raises ZeroDivisionError instead of returning None",
        error_logs="ZeroDivisionError: division by zero",
        affected_files=["calculator.py"],
        repository_path=str(sample_git_repo),
    )
