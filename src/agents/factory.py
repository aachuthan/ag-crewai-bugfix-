"""Agent factory — creates all specialized agents for the bug-fix pipeline.

Each agent gets ONLY the tools it needs (least-privilege):
- Bug Analyst:       code_reader only
- Code Investigator: code_reader only
- Fix Developer:     code_editor + git_tool
- Test Engineer:     code_editor + git_tool
- Code Reviewer:     code_reader only
"""

from crewai import Agent, LLM

from src.config.settings import get_settings
from src.tools.claude_code_tool import ClaudeCodeReadTool, ClaudeCodeEditTool
from src.tools.opencode_tool import OpenCodeReadTool, OpenCodeEditTool
from src.tools.git_tool import GitTool


def _make_llm(
    temperature: float = 0.1,
    thinking: dict | None = None,
    max_tokens: int | None = None,
) -> LLM:
    """Create an LLM instance from centralized settings."""
    settings = get_settings()
    kwargs: dict = {"model": settings.claude_model, "temperature": temperature}
    if thinking:
        kwargs["thinking"] = thinking
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return LLM(**kwargs)


def _get_tools(readonly: bool, repo_path: str):
    """Dynamically get the correct toolset based on the active execution engine."""
    engine = get_settings().execution_engine.lower()
    
    if engine == "opencode":
        return [OpenCodeReadTool(repo_path=repo_path)] if readonly else [OpenCodeEditTool(repo_path=repo_path), GitTool(repo_path=repo_path)]
    else:
        # Default to claude-code
        return [ClaudeCodeReadTool(repo_path=repo_path)] if readonly else [ClaudeCodeEditTool(repo_path=repo_path), GitTool(repo_path=repo_path)]


# ── Bug Analyst ───────────────────────────────────────────────────

def create_bug_analyst(repo_path: str) -> Agent:
    """Create the Bug Analyst agent responsible for triage and classification.

    Tools: code_reader (READ-ONLY)
    """
    return Agent(
        role="Senior Bug Analyst",
        goal=(
            "Analyze the bug report, classify its severity and category, "
            "and produce a clear triage summary that guides the investigation."
        ),
        backstory=(
            "You are a veteran QA engineer with 15 years of experience. "
            "You excel at reading bug reports, error logs, and stack traces "
            "to quickly classify and prioritize issues. You understand the "
            "difference between a symptom and a root cause."
        ),
        llm=_make_llm(temperature=0.1),
        tools=_get_tools(readonly=True, repo_path=repo_path),
        verbose=True,
        allow_delegation=False,
    )


# ── Code Investigator ────────────────────────────────────────────

def create_code_investigator(repo_path: str) -> Agent:
    """Create the Code Investigator agent for root cause analysis.

    Tools: code_reader (READ-ONLY)
    Uses extended thinking for deep analysis.
    """
    return Agent(
        role="Code Investigator",
        goal=(
            "Trace the bug to its root cause by analyzing the codebase, "
            "identifying affected files, and documenting relevant code paths."
        ),
        backstory=(
            "You are a debugging specialist who thinks like a detective. "
            "You methodically trace execution flows, read stack traces, "
            "and search for patterns to pinpoint exactly where and why "
            "a bug occurs. You document findings with file paths and line numbers."
        ),
        llm=_make_llm(
            temperature=0.0,
            thinking={"type": "enabled", "budget_tokens": 8000},
            max_tokens=12000,
        ),
        tools=_get_tools(readonly=True, repo_path=repo_path),
        verbose=True,
        allow_delegation=False,
    )


# ── Fix Developer ────────────────────────────────────────────────

def create_fix_developer(repo_path: str) -> Agent:
    """Create the Fix Developer agent to implement the code fix.

    Tools: code_editor, git_tool (READ-WRITE)
    """
    return Agent(
        role="Senior Fix Developer",
        goal="Write the exact code changes needed to fix the bug and commit them.",
        backstory=(
            "You are a senior software engineer who writes extremely clean, "
            "surgical code. You never refactor unrelated code. You make "
            "minimal, safe, and precise code modifications to resolve issues."
        ),
        llm=_make_llm(temperature=0.1),
        tools=_get_tools(readonly=False, repo_path=repo_path),
        verbose=True,
        allow_delegation=False,
    )


# ── Test Engineer ────────────────────────────────────────────────

def create_test_engineer(repo_path: str) -> Agent:
    """Create the Test Engineer agent to write tests and verify the fix.

    Tools: code_editor, git_tool (READ-WRITE)
    """
    return Agent(
        role="Test Automation Engineer",
        goal="Write regression tests for the bug and verify they pass.",
        backstory=(
            "You are a rigorous QA automation engineer. You excel at finding "
            "edge cases, understanding existing test frameworks in any language, "
            "and writing automated tests that ensure bugs never return."
        ),
        llm=_make_llm(temperature=0.1),
        tools=_get_tools(readonly=False, repo_path=repo_path),
        verbose=True,
        allow_delegation=False,
    )


# ── Code Reviewer ────────────────────────────────────────────────

def create_code_reviewer(repo_path: str) -> Agent:
    """Create the Code Reviewer agent as the final quality gate.

    Tools: code_reader (READ-ONLY)
    """
    return Agent(
        role="Lead Code Reviewer",
        goal="Review the proposed fix and tests to ensure quality and correctness.",
        backstory=(
            "You are a strict but fair Principal Engineer. You review pull "
            "requests with a fine-toothed comb. Your goal is to "
            "ensure that code meets quality standards, is fully tested, "
            "and solves the root problem without regressions."
        ),
        llm=_make_llm(temperature=0.0),
        tools=_get_tools(readonly=True, repo_path=repo_path),
        verbose=True,
        allow_delegation=False,
    )
