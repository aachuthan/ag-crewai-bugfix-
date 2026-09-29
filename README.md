# AG CrewAI Bug Fix Pipeline

An AI-powered development team that autonomously diagnoses and fixes bugs in any codebase using **CrewAI** (orchestration) and **Claude Code** (execution).

Works with **any language** — Python, Java, JavaScript/TypeScript, Go, Rust, C#, Ruby, and more.

## How It Works

```
You describe the bug
        │
        ▼
🔍 Bug Analyst ──────── reads your description + error logs
        │                 classifies severity & type
        ▼
🕵️ Code Investigator ── reads the actual code in your repo
        │                 traces execution flow to root cause
        ▼
🛠️ Fix Developer ────── creates a git branch
        │                 edits the minimum code needed
        │                 commits the change
        ▼
🧪 Test Engineer ────── writes regression tests
        │                 runs your full test suite
        │                 ┌─ tests fail? → retries the fix
        ▼                 │
📋 Code Reviewer ───────┘  reviews the diff
        │                    ┌─ needs changes? → retries the fix
        ▼                    │
✅ Done ──────────────────────┘
        │
   Branch ready → you review & merge
```

### Agent Permissions (Least Privilege)

| Agent | Role | Can Read Code | Can Edit Code | Can Use Git |
|-------|------|:---:|:---:|:---:|
| Bug Analyst | Triage & classify | ✅ | ❌ | ❌ |
| Code Investigator | Root cause analysis | ✅ | ❌ | ❌ |
| Fix Developer | Implement fix | ✅ | ✅ | ✅ |
| Test Engineer | Write & run tests | ✅ | ✅ | ✅ |
| Code Reviewer | Quality gate | ✅ | ❌ | ❌ |

---

## Setup (One Time)

### Prerequisites

- **Python 3.11+**
- **Node.js & NPM** installed (required by Claude Code SDK)
- **Git** installed and on PATH
- **Claude Code CLI** installed ([docs](https://docs.anthropic.com/claude-code))
- **Anthropic API key**
- *(Optional)* Jira account with API token

### Step 1: Install

```bash
cd c:\projects\ag_crewai

# Without Jira integration
pip install -e .

# With Jira integration
pip install -e ".[jira]"
```

This installs the `bugfix` command on your system. You can run it from anywhere.

### Step 2: Configure API Keys

```bash
copy .env.example .env
```

Edit `.env` with your keys:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-paste-your-key-here

# Optional — only for Jira integration
JIRA_URL=https://your-company.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=paste-jira-token-here
```

> **Jira API token**: Get one at https://id.atlassian.com/manage-profile/security/api-tokens

### Step 3: Add `CLAUDE.md` to Your Target Repository

Create a `CLAUDE.md` file **at the root of the repository you want to fix**. This tells the agents how your project works:

```markdown
# Project

## Tech Stack
- Java 17, Spring Boot 3, Maven

## Commands
| Command | Purpose |
|---------|---------|
| `mvn test` | Run tests |
| `mvn compile` | Build |

## Rules
1. Run tests before finishing.
2. Minimal changes only.
3. Add tests for every fix.
```

Adapt for your language:

| Language | Test | Lint | Build |
|----------|------|------|-------|
| Python | `pytest` | `ruff check .` | `python -m build` |
| Java | `mvn test` | `mvn checkstyle:check` | `mvn compile` |
| JavaScript/TS | `npm test` | `npm run lint` | `npm run build` |
| Go | `go test ./...` | `golangci-lint run` | `go build ./...` |
| Rust | `cargo test` | `cargo clippy` | `cargo build` |
| C# | `dotnet test` | `dotnet format --verify-no-changes` | `dotnet build` |
| Ruby | `bundle exec rspec` | `rubocop` | — |

---

## Usage

### Fix from a Jira Ticket (Easiest)

```bash
bugfix fix-from-jira --repo C:\path\to\your-repo --issue BUG-123
```

The tool pulls the title, description, comments, and stack traces from Jira automatically. It also auto-detects file paths mentioned in the ticket (including Java class names like `com.myapp.OrderService`).

**Optional flags:**

| Flag | Effect |
|------|--------|
| `--no-comments` | Exclude Jira comments from context |

### Fix from a JSON File

Create a file describing the bug:

```json
{
    "title": "Login crashes when email has a plus sign",
    "description": "Users with user+tag@email.com get a 500 error on the login page",
    "steps_to_reproduce": "1. Go to /login\n2. Enter user+tag@test.com\n3. Click Sign In\n4. See 500 error",
    "error_logs": "NullPointerException at AuthService.java:42\n  at LoginController.java:18",
    "affected_files": [
        "src/main/java/com/app/AuthService.java",
        "src/main/java/com/app/LoginController.java"
    ]
}
```

Run:

```bash
bugfix fix-from-file --repo C:\path\to\your-repo --bug-file bug.json
```

### Fix with Inline Arguments

```bash
bugfix fix ^
  --repo C:\path\to\your-repo ^
  --title "Login crash with plus sign" ^
  --description "500 error when email contains +" ^
  --logs "NullPointerException at AuthService.java:42" ^
  --files "src/main/java/com/app/AuthService.java"
```

### Preview a Jira Ticket (Dry Run)

See what the agents will receive **without running the pipeline**:

```bash
bugfix preview-jira --issue BUG-123
```

### Verbose Mode

Add `--verbose` to see what each agent is doing in real time:

```bash
bugfix --verbose fix-from-jira --repo C:\path\to\your-repo --issue BUG-123
```

---

## After the Pipeline Finishes

### What You'll See

```
╭──── 🎉 Results ─────────────────────────╮
│ ✅ Bug Fix Complete!                     │
│                                          │
│ Branch: fix/login-crash-with-plus-sign   │
│ Files Changed: AuthService.java          │
│ Tests Written: AuthServiceTest.java      │
│ All Tests Pass: ✅ Yes                   │
│ Iterations: 1                            │
╰──────────────────────────────────────────╯
```

### Review and Merge

```bash
cd C:\path\to\your-repo

# See what the AI committed
git log --oneline -5

# Review the code changes
git diff main...HEAD

# If satisfied, push and create a PR
git push origin fix/login-crash-with-plus-sign
```

> **Always review AI-generated fixes before merging.** The pipeline gets you 90% there — you make the final call.

---

## Quick Reference

| What you want to do | Command |
|---------------------|---------|
| Fix from Jira | `bugfix fix-from-jira --repo REPO --issue KEY` |
| Fix from JSON file | `bugfix fix-from-file --repo REPO --bug-file FILE` |
| Fix inline | `bugfix fix --repo REPO --title "..." --description "..."` |
| Preview Jira ticket | `bugfix preview-jira --issue KEY` |
| Verbose output | `bugfix --verbose fix-from-jira ...` |
| See all commands | `bugfix --help` |
| Command help | `bugfix fix --help` |

---

## Tips for Best Results

| Tip | Why |
|-----|-----|
| **Paste the full stack trace** | Agents trace the call chain backwards from the error |
| **Name suspect files** | Skips broad searching, goes straight to the problem |
| **Write a good `CLAUDE.md`** | Tells agents how to build, test, and lint your project |
| **Start from a clean branch** | No uncommitted changes — the tool creates its own branch |
| **Use `preview-jira` first** | Verify the Jira data looks right before running |

### What You Don't Need to Worry About

- **Language** — Claude Code reads your source files and figures it out
- **Test framework** — the Test Engineer reads existing tests and follows the same patterns
- **Git** — the crew creates branches, commits, and diffs automatically
- **Finding files** — even without file hints, the Code Investigator searches the codebase

---

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `CLAUDE_MODEL` | `anthropic/claude-sonnet-4-6` | Model for all agents |
| `CLAUDE_CODE_MAX_TURNS` | `20` | Max turns per Claude Code query |
| `CLAUDE_CODE_PERMISSION_MODE` | `acceptEdits` | Permission mode for code edits |
| `MAX_RETRY_ITERATIONS` | `3` | Max fix→test→review retry cycles |
| `JIRA_URL` | *(optional)* | Your Jira instance URL |
| `JIRA_EMAIL` | *(optional)* | Your Jira email |
| `JIRA_API_TOKEN` | *(optional)* | Your Jira API token |

---

## Project Structure

```
src/
├── main.py                       # CLI entry point (bugfix command)
├── config/settings.py            # Centralized env-var config
├── models/
│   ├── state.py                  # BugReport + BugFixState
│   └── outputs.py                # Structured output schemas
├── tools/
│   ├── claude_code_tool.py       # Read-only + read-write tool variants
│   └── git_tool.py               # Safe git operations (allowlisted)
├── agents/factory.py             # 5 agents with least-privilege tools
├── crews/crew_factory.py         # Crew + Task creation
├── flows/bug_fix_flow.py         # Main Flow orchestrator
└── integrations/jira_client.py   # Jira ticket fetching & conversion
```

---

## Development

### Running Tests

```bash
# All tests (mocked — no API key needed)
pytest tests/ -v

# Specific modules
pytest tests/test_tools.py -v     # Tool safety tests
pytest tests/test_agents.py -v    # Agent permission tests
pytest tests/test_flow.py -v      # State & parsing tests
pytest tests/test_jira.py -v      # Jira integration tests
```

### Installing Dev Dependencies

```bash
pip install -e ".[dev]"
```

---

## License

MIT
