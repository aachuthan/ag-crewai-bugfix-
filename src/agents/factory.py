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
        tools=[ClaudeCodeReadTool(repo_path=repo_path)],
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
        tools=[ClaudeCodeReadTool(repo_path=repo_path)],
        verbose=True,
        allow_delegation=False,
    )


# ── Fix Developer ────────────────────────────────────────────────

def create_fix_developer(repo_path: str) -> Agent:
    """Create the Fix Developer agent that implements code fixes.

    Tools: code_editor (READ-WRITE) + git_tool
    Uses extended thinking for precise implementation.
    """
    return Agent(
        role="Senior Fix Developer",
        goal=(
            "Implement a minimal, correct fix for the identified bug. "
            "Create a feature branch, apply the fix, and produce a clean diff."
        ),
        backstory=(
            "You are a senior software engineer known for clean, minimal fixes. "
            "You create dedicated branches, write descriptive commit messages, "
            "and ensure changes are surgical. You have access to code editing "
            "tools and git operations."
        ),
        llm=_make_llm(
            temperature=0.0,
            thinking={"type": "enabled", "budget_tokens": 10000},
            max_tokens=16000,
        ),
        tools=[
            ClaudeCodeEditTool(repo_path=repo_path),
            GitTool(repo_path=repo_path),
        ],
        verbose=True,
        allow_delegation=False,
    )


# ── Test Engineer ─────────────────────────────────────────────────

def create_test_engineer(repo_path: str) -> Agent:
    """Create the Test Engineer agent for writing and running tests.

    Tools: code_editor (READ-WRITE, needs to write test files + run tests) + git_tool
    """
    return Agent(
        role="Test Engineer",
        goal=(
            "Write regression tests that cover the bug scenario, run the full "
            "test suite, and report whether all tests pass."
        ),
        backstory=(
            "You are a test automation expert. You write tests that verify "
            "the fix works and prevent regression. You understand the project's "
            "testing framework and always run the complete test suite after "
            "adding new tests."
        ),
        llm=_make_llm(temperature=0.1),
        tools=[
            ClaudeCodeEditTool(repo_path=repo_path),
            GitTool(repo_path=repo_path),
        ],
        verbose=True,
        allow_delegation=False,
    )


# ── Code Reviewer ─────────────────────────────────────────────────

def create_code_reviewer(repo_path: str) -> Agent:
    """Create the Code Reviewer agent that acts as a quality gate.

    Tools: code_reader (READ-ONLY)
    Uses extended thinking for thorough review.
    """
    return Agent(
        role="Senior Code Reviewer",
        goal=(
            "Review the proposed fix for correctness, code quality, potential "
            "regressions, and adherence to project conventions. Provide a "
            "verdict: approved, needs_changes, or rejected."
        ),
        backstory=(
            "You are a principal engineer who reviews code with extreme "
            "thoroughness. You check for edge cases, thread safety, error "
            "handling, naming conventions, and performance issues. You are "
            "constructive but uncompromising on quality."
        ),
        llm=_make_llm(
            temperature=0.0,
            thinking={"type": "enabled", "budget_tokens": 8000},
            max_tokens=12000,
        ),
        tools=[ClaudeCodeReadTool(repo_path=repo_path)],
        verbose=True,
        allow_delegation=False,
    )
