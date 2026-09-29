"""Custom CrewAI tools that wrap the claude-agent-sdk.

Split into read-only and read-write variants to enforce
least-privilege per agent role.

Key design decisions:
- ClaudeCodeReadTool: only allows Read, Grep, Glob (for analysts, investigators, reviewers)
- ClaudeCodeEditTool: allows Read, Write, Edit, Bash, Grep, Glob (for fix developers, test engineers)
- allowed_tools is NOT exposed in the LLM-visible schema (prevents permission escalation)
- Uses thread-pool executor to avoid asyncio.run() crash inside CrewAI's event loop
"""

import asyncio
import logging
import threading
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field
from claude_agent_sdk import query, ClaudeAgentOptions

from src.config.settings import get_settings


logger = logging.getLogger(__name__)


# ── Input Schema ──────────────────────────────────────────────────
# Only the prompt is LLM-controlled. Tool permissions are fixed
# at the class level to prevent agents from escalating access.

class ClaudeCodePromptInput(BaseModel):
    """Input schema for Claude Code tools — only the prompt is user-controlled."""
    prompt: str = Field(
        description="Clear, specific instruction for code analysis or modification"
    )


# ── Async Safety Layer ────────────────────────────────────────────

def _run_async_safely(coro):
    """Run an async coroutine safely, handling existing event loops.

    CrewAI may already have a running event loop. Calling asyncio.run()
    inside an existing loop raises RuntimeError. This function detects
    that situation and runs the coroutine in a separate thread instead.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop (likely CrewAI's).
        # Spin up a new thread with its own event loop.
        result = None
        exception = None

        def _thread_target():
            nonlocal result, exception
            try:
                result = asyncio.run(coro)
            except Exception as e:
                exception = e

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()
        thread.join(timeout=300)  # 5-minute hard timeout

        if exception:
            raise exception
        if thread.is_alive():
            raise TimeoutError("Claude Code query timed out after 300 seconds")
        return result
    else:
        # No existing loop — safe to use asyncio.run()
        return asyncio.run(coro)


# ── Core Query Function ──────────────────────────────────────────

async def _query_claude_code(
    prompt: str,
    repo_path: str,
    allowed_tools: list[str],
    system_prompt: str,
) -> str:
    """Execute a Claude Code query and collect results from the stream."""
    settings = get_settings()

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        cwd=repo_path,
        max_turns=settings.claude_code_max_turns,
        permission_mode=settings.claude_code_permission_mode,
    )

    results = []
    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            results.append(str(message.content))
        elif hasattr(message, "text"):
            results.append(message.text)

    return "\n".join(results) if results else "No output received from Claude Code."


# ── Read-Only Tool ────────────────────────────────────────────────

class ClaudeCodeReadTool(BaseTool):
    """Read-only codebase operations: file reading, grep, glob.

    Use this for agents that should NOT modify the repository
    (Bug Analyst, Code Investigator, Code Reviewer).
    """
    name: str = "code_reader"
    description: str = (
        "Read and search code in the repository. Can read file contents, "
        "search for patterns with grep, and find files with glob. "
        "CANNOT modify any files. Provide a clear, specific instruction."
    )
    args_schema: Type[BaseModel] = ClaudeCodePromptInput
    repo_path: str = Field(default="", description="Repository path")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, prompt: str) -> str:
        logger.info(f"[code_reader] Executing: {prompt[:100]}...")
        coro = _query_claude_code(
            prompt=prompt,
            repo_path=self.repo_path,
            allowed_tools=["Read", "Grep", "Glob"],
            system_prompt=(
                "You are a senior software engineer analyzing code. "
                "Be precise and thorough. Return structured findings. "
                "You can only READ files — do not attempt to modify anything."
            ),
        )
        try:
            return _run_async_safely(coro)
        except Exception as e:
            logger.error(f"[code_reader] Failed: {e}")
            return f"Error executing code read: {str(e)}"


# ── Read-Write Tool ───────────────────────────────────────────────

class ClaudeCodeEditTool(BaseTool):
    """Read-write codebase operations: read, write, edit, run commands.

    Use this ONLY for agents that need to modify the repository
    (Fix Developer, Test Engineer).
    """
    name: str = "code_editor"
    description: str = (
        "Read, write, and edit code in the repository. Can also run shell "
        "commands (e.g., test runners, build tools). Use for implementing "
        "fixes, writing tests, and running the test suite. "
        "Provide a clear, specific instruction."
    )
    args_schema: Type[BaseModel] = ClaudeCodePromptInput
    repo_path: str = Field(default="", description="Repository path")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, prompt: str) -> str:
        logger.info(f"[code_editor] Executing: {prompt[:100]}...")
        coro = _query_claude_code(
            prompt=prompt,
            repo_path=self.repo_path,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            system_prompt=(
                "You are a senior software engineer implementing code changes. "
                "Be precise and minimal. Only change what is strictly necessary. "
                "Always verify your changes make sense before completing."
            ),
        )
        try:
            return _run_async_safely(coro)
        except Exception as e:
            logger.error(f"[code_editor] Failed: {e}")
            return f"Error executing code edit: {str(e)}"
