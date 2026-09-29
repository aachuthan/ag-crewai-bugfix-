"""Jira integration — fetch bug/feature tickets and convert them to BugReports.

Connects to Jira Cloud or Server via the atlassian-python-api library,
pulls issue details (summary, description, comments, attachments, labels),
and maps them into the BugReport model used by the pipeline.

Setup:
    pip install ag-crewai-bugfix[jira]

    # .env
    JIRA_URL=https://your-org.atlassian.net
    JIRA_EMAIL=your-email@company.com
    JIRA_API_TOKEN=your-api-token
"""

import logging
import re
from typing import Optional

from src.config.settings import get_settings
from src.models.state import BugReport


logger = logging.getLogger(__name__)


def _ensure_jira_installed():
    """Check that atlassian-python-api is installed."""
    try:
        from atlassian import Jira  # noqa: F401
        return True
    except ImportError:
        raise ImportError(
            "Jira integration requires 'atlassian-python-api'. "
            "Install it with: pip install ag-crewai-bugfix[jira]"
        )


def _get_jira_client():
    """Create and return an authenticated Jira client."""
    _ensure_jira_installed()
    from atlassian import Jira

    settings = get_settings()

    if not settings.jira_url:
        raise ValueError(
            "JIRA_URL is not configured. "
            "Set it in your .env file or environment variables."
        )
    if not settings.jira_email or not settings.jira_api_token:
        raise ValueError(
            "JIRA_EMAIL and JIRA_API_TOKEN must be configured. "
            "Set them in your .env file or environment variables.\n"
            "Get an API token at: https://id.atlassian.com/manage-profile/security/api-tokens"
        )

    return Jira(
        url=settings.jira_url,
        username=settings.jira_email,
        password=settings.jira_api_token,
        cloud=True,
    )


def _extract_text_from_adf(adf_content: dict | str | None) -> str:
    """Extract plain text from Atlassian Document Format (ADF) content.

    Jira Cloud returns descriptions in ADF (a nested JSON structure).
    Jira Server returns plain text or wiki markup.
    This function handles both cases.
    """
    if adf_content is None:
        return ""

    # If it's already a string (Jira Server / simple text), return as-is
    if isinstance(adf_content, str):
        return adf_content

    # ADF is a dict with a 'content' array
    if not isinstance(adf_content, dict):
        return str(adf_content)

    def _walk_adf(node: dict) -> str:
        """Recursively walk ADF nodes and extract text."""
        parts = []

        if node.get("type") == "text":
            parts.append(node.get("text", ""))
        elif node.get("type") == "hardBreak":
            parts.append("\n")
        elif node.get("type") == "codeBlock":
            # Extract code block content
            code_parts = []
            for child in node.get("content", []):
                code_parts.append(_walk_adf(child))
            code_text = "".join(code_parts)
            lang = node.get("attrs", {}).get("language", "")
            parts.append(f"\n```{lang}\n{code_text}\n```\n")
        elif node.get("type") in ("listItem", "bulletList", "orderedList"):
            for child in node.get("content", []):
                child_text = _walk_adf(child)
                if node.get("type") == "listItem":
                    parts.append(f"- {child_text}\n")
                else:
                    parts.append(child_text)
        else:
            # Generic: recurse into children
            for child in node.get("content", []):
                parts.append(_walk_adf(child))

            # Add line break after block-level elements
            if node.get("type") in ("paragraph", "heading"):
                parts.append("\n")

        return "".join(parts)

    return _walk_adf(adf_content).strip()


def _extract_comments(comment_data: dict | None) -> str:
    """Extract comment text from a Jira issue's comment field."""
    if not comment_data:
        return ""

    comments = comment_data.get("comments", [])
    if not comments:
        return ""

    # CONTEXT WINDOW PROTECTION: Only take the last 5 comments
    comments = comments[-5:]

    parts = []
    for comment in comments:
        author = comment.get("author", {}).get("displayName", "Unknown")
        body = _extract_text_from_adf(comment.get("body", ""))
        created = comment.get("created", "")[:10]  # Just the date
        parts.append(f"[{created}] {author}:\n{body}")

    result = "\n\n---\n\n".join(parts)
    
    # CONTEXT WINDOW PROTECTION: Hard limit to 10k chars
    if len(result) > 10000:
        result = "...(earlier parts truncated due to length)...\n" + result[-10000:]
        
    return result


# File extensions recognized across all supported languages
_CODE_EXTENSIONS = frozenset({
    # JVM
    '.java', '.kt', '.kts', '.scala', '.groovy', '.clj',
    # Python
    '.py', '.pyx', '.pyi',
    # JavaScript / TypeScript
    '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.vue', '.svelte',
    # Go
    '.go',
    # Rust
    '.rs',
    # C / C++
    '.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.hxx',
    # C# / .NET
    '.cs', '.fs', '.vb', '.cshtml', '.razor',
    # Ruby
    '.rb', '.erb',
    # PHP
    '.php',
    # Swift / Objective-C
    '.swift', '.m', '.mm',
    # Dart
    '.dart',
    # Elixir / Erlang
    '.ex', '.exs', '.erl',
    # Config / Data
    '.xml', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg',
    '.properties', '.env', '.gradle',
    # Web
    '.html', '.css', '.scss', '.sass', '.less',
    # Shell
    '.sh', '.bash', '.zsh', '.ps1',
    # SQL
    '.sql',
})


def _guess_affected_files(text: str) -> list[str]:
    """Best-effort extraction of file paths mentioned in issue text.

    Language-agnostic: handles explicit file paths, stack trace patterns,
    and language-specific qualified names for multiple ecosystems.

    Recognized patterns:
        Explicit paths:   src/main/java/com/app/Order.java
                          app/models/user.rb
                          pkg/handler/auth.go

        Java/Kotlin FQCN: com.myapp.service.OrderService
                          → src/main/java/com/myapp/service/OrderService.java

        Python modules:   myapp.services.auth (in "File" or "import" context)
                          → myapp/services/auth.py

        Go packages:      github.com/user/repo/pkg/auth
                          → pkg/auth

        C# namespaces:    MyApp.Services.OrderService (in stack trace context)
                          → MyApp/Services/OrderService.cs

        Stack traces:     at OrderService.java:42
                          File "/app/auth.py", line 10
                          at Object.<anonymous> (src/index.js:15:3)
                          goroutine 1 [running]: main.go:42
    """
    files = []

    # ── 1. Explicit file paths with recognized extensions ─────────
    # Matches: src/main/java/Order.java, ./app/models/user.rb, C:\src\file.go
    path_pattern = r'[\w./\\:-]+\.\w{1,10}'
    for match in re.findall(path_pattern, text):
        ext = '.' + match.rsplit('.', 1)[-1].lower() if '.' in match else ''
        if ext in _CODE_EXTENSIONS:
            # Clean up leading/trailing punctuation
            cleaned = match.strip('.,;:()[]{}"\' ')
            if cleaned and len(cleaned) > 3:
                files.append(cleaned)

    # ── 2. Java / Kotlin fully-qualified class names ──────────────
    # Matches: com.myapp.service.OrderService
    # → src/main/java/com/myapp/service/OrderService.java
    fqcn_pattern = r'\b([a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*){2,}\.[A-Z]\w+)\b'
    for match in re.findall(fqcn_pattern, text):
        java_path = "src/main/java/" + match.replace(".", "/") + ".java"
        files.append(java_path)

    # ── 3. Python module paths (in import/traceback context) ──────
    # Matches: "File \"/app/mymodule/auth.py\"" or "from myapp.auth import ..."
    # Also: "in myapp.services.auth" from tracebacks
    py_import_pattern = r'(?:from|import)\s+([\w.]+)'
    for match in re.findall(py_import_pattern, text):
        if '.' in match and not match.startswith('__'):
            py_path = match.replace('.', '/') + '.py'
            files.append(py_path)

    # Python traceback file paths: File "/app/something.py", line 42
    py_traceback_pattern = r'File\s+"([^"]+\.py)"'
    for match in re.findall(py_traceback_pattern, text):
        files.append(match)

    # ── 4. Go package paths ───────────────────────────────────────
    # Matches: github.com/user/repo/pkg/handler
    # Extracts the local part after the repo root
    go_pkg_pattern = r'(?:github\.com|gitlab\.com|bitbucket\.org)/[\w.-]+/[\w.-]+/([\w/.-]+)'
    for match in re.findall(go_pkg_pattern, text):
        files.append(match)

    # Go stack traces: main.go:42, handler.go:15
    go_trace_pattern = r'\b(\w+\.go):\d+'
    for match in re.findall(go_trace_pattern, text):
        files.append(match)

    # ── 5. C# / .NET namespace patterns (in stack traces) ────────
    # Matches: "at MyApp.Services.OrderService.Process()" in stack traces
    cs_pattern = r'at\s+([A-Z][\w]+(?:\.[A-Z][\w]+){2,})\.\w+\('
    for match in re.findall(cs_pattern, text):
        cs_path = match.replace('.', '/') + '.cs'
        files.append(cs_path)

    # ── 6. JavaScript/TypeScript stack traces ─────────────────────
    # Matches: at Object.<anonymous> (src/index.js:15:3)
    #          at /app/src/utils/helper.ts:42:10
    js_trace_pattern = r'(?:at\s+.*?\(|at\s+)([\w./\\-]+\.(?:js|ts|jsx|tsx|mjs))[\s:)]'
    for match in re.findall(js_trace_pattern, text):
        files.append(match)

    # ── 7. Ruby stack traces ──────────────────────────────────────
    # Matches: from /app/models/user.rb:42:in `validate'
    rb_trace_pattern = r'([\w./\\-]+\.rb):\d+'
    for match in re.findall(rb_trace_pattern, text):
        files.append(match)

    # ── 8. Rust stack traces ──────────────────────────────────────
    # Matches: src/main.rs:42  or  at src/lib.rs:15
    rs_trace_pattern = r'([\w./\\-]+\.rs):\d+'
    for match in re.findall(rs_trace_pattern, text):
        files.append(match)

    # ── Deduplicate while preserving order ────────────────────────
    seen = set()
    unique = []
    for f in files:
        # Normalize separators
        normalized = f.replace('\\', '/')
        if normalized not in seen and len(normalized) > 2:
            seen.add(normalized)
            unique.append(normalized)

    return unique


def fetch_jira_issue(issue_key: str) -> dict:
    """Fetch a Jira issue and return its raw fields.

    Args:
        issue_key: The Jira issue key (e.g., "PROJ-123", "BUG-456")

    Returns:
        Dict with keys: summary, description, comments, labels,
        priority, status, issue_type, assignee, reporter, components
    """
    jira = _get_jira_client()

    logger.info(f"Fetching Jira issue: {issue_key}")

    issue = jira.issue(
        issue_key,
        fields="summary,description,comment,labels,priority,status,"
               "issuetype,assignee,reporter,components,attachment",
    )

    fields = issue.get("fields", {})

    return {
        "key": issue_key,
        "summary": fields.get("summary", ""),
        "description": _extract_text_from_adf(fields.get("description")),
        "comments": _extract_comments(fields.get("comment")),
        "labels": fields.get("labels", []),
        "priority": (fields.get("priority") or {}).get("name", "Unknown"),
        "status": (fields.get("status") or {}).get("name", "Unknown"),
        "issue_type": (fields.get("issuetype") or {}).get("name", "Unknown"),
        "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
        "reporter": (fields.get("reporter") or {}).get("displayName", "Unknown"),
        "components": [
            c.get("name", "") for c in (fields.get("components") or [])
        ],
    }


def jira_issue_to_bug_report(
    issue_key: str,
    repository_path: str,
    include_comments: bool = True,
) -> BugReport:
    """Fetch a Jira issue and convert it to a BugReport for the pipeline.

    The function:
    1. Fetches the issue from Jira (summary, description, comments)
    2. Extracts file paths mentioned in the text
    3. Uses comments as additional error logs / context
    4. Maps Jira fields to BugReport fields

    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")
        repository_path: Local path to the git repository
        include_comments: Whether to include Jira comments as context

    Returns:
        A BugReport ready to feed into BugFixFlow
    """
    issue = fetch_jira_issue(issue_key)

    logger.info(
        f"Converting {issue_key} to BugReport: "
        f"type={issue['issue_type']}, priority={issue['priority']}"
    )

    # Build the title from the Jira summary
    title = f"[{issue_key}] {issue['summary']}"

    # Build the description, including metadata
    description_parts = [
        issue["description"],
        "",
        f"Jira Issue: {issue_key}",
        f"Type: {issue['issue_type']}",
        f"Priority: {issue['priority']}",
        f"Status: {issue['status']}",
        f"Reporter: {issue['reporter']}",
    ]
    if issue["components"]:
        description_parts.append(f"Components: {', '.join(issue['components'])}")
    if issue["labels"]:
        description_parts.append(f"Labels: {', '.join(issue['labels'])}")

    description = "\n".join(description_parts)
    
    # CONTEXT WINDOW PROTECTION: Hard limit to 10k chars
    if len(description) > 10000:
        description = description[:10000] + "\n\n... (description truncated due to length)"

    # Use comments as additional context (often contains stack traces,
    # reproduction steps, and debugging notes)
    error_logs = ""
    steps_to_reproduce = ""
    if include_comments and issue["comments"]:
        # Comments often contain the most useful debugging info
        error_logs = f"=== Jira Comments ===\n\n{issue['comments']}"

    # Extract file paths from description + comments
    full_text = f"{issue['description']}\n{issue['comments']}"
    affected_files = _guess_affected_files(full_text)

    return BugReport(
        title=title,
        description=description,
        steps_to_reproduce=steps_to_reproduce,
        error_logs=error_logs,
        affected_files=affected_files,
        repository_path=repository_path,
    )
