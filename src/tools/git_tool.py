"""Safe git operations tool for CrewAI agents.

Security measures:
- shell=False (no shell injection)
- shlex.split for proper argument parsing
- Allowlist of git subcommands (no arbitrary command execution)
- Timeout protection
"""

import logging
import shlex
import subprocess
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from src.observability.tracer import observe


logger = logging.getLogger(__name__)


# Only these git subcommands are permitted
ALLOWED_GIT_COMMANDS = frozenset({
    "checkout",
    "branch",
    "add",
    "commit",
    "diff",
    "log",
    "status",
    "show",
    "stash",
    "merge",
    "reset",
})


class GitInput(BaseModel):
    """Input schema for GitTool."""
    command: str = Field(
        description=(
            "Git command to execute (without 'git' prefix). "
            "Examples: 'checkout -b fix/bug-123', 'diff --staged', "
            "'add .', 'commit -m \"fix: resolve null check\"', "
            "'status', 'log --oneline -5'"
        )
    )


class GitTool(BaseTool):
    """Execute safe, allowlisted git operations in the target repository.

    Only permits a curated set of git subcommands to prevent
    destructive operations. Uses shlex.split + shell=False to
    avoid shell injection from LLM-generated arguments.
    """
    name: str = "git_tool"
    description: str = (
        "Execute git commands in the repository. Allowed operations: "
        "checkout, branch, add, commit, diff, log, status, show, stash, "
        "merge, reset. Provide the command WITHOUT the 'git' prefix."
    )
    args_schema: Type[BaseModel] = GitInput
    repo_path: str = Field(default="", description="Repository path")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @observe(as_type="generation", name="Git Command")
    def _run(self, command: str) -> str:
        # Parse the command string into safe argument list
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return f"Error: Could not parse command: {e}"

        if not parts:
            return "Error: Empty command"

        # Validate git subcommand against allowlist
        subcommand = parts[0]
        if subcommand not in ALLOWED_GIT_COMMANDS:
            return (
                f"Error: Git subcommand '{subcommand}' is not allowed. "
                f"Allowed: {', '.join(sorted(ALLOWED_GIT_COMMANDS))}"
            )

        full_cmd = ["git"] + parts
        logger.info(f"[git_tool] Running: {' '.join(full_cmd)}")

        try:
            result = subprocess.run(
                full_cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if stderr:
                    output += f"\nSTDERR: {stderr}"
                if not output:
                    output = f"Git command failed with exit code {result.returncode}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            logger.error(f"[git_tool] Timed out: {' '.join(full_cmd)}")
            return "Error: Git command timed out after 120 seconds."
        except FileNotFoundError:
            return "Error: 'git' executable not found. Is git installed and on PATH?"
        except Exception as e:
            logger.error(f"[git_tool] Failed: {e}")
            return f"Error: {str(e)}"
