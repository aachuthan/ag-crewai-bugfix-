"""Tests for the Jira integration module."""

import pytest

from src.integrations.jira_client import (
    _extract_text_from_adf,
    _extract_comments,
    _guess_affected_files,
)


# ── ADF Parsing Tests ─────────────────────────────────────────────

class TestExtractTextFromADF:
    """Tests for Atlassian Document Format content extraction."""

    def test_none_returns_empty(self):
        assert _extract_text_from_adf(None) == ""

    def test_plain_string_passthrough(self):
        text = "This is a plain text description"
        assert _extract_text_from_adf(text) == text

    def test_simple_adf_paragraph(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello world"}
                    ]
                }
            ]
        }
        result = _extract_text_from_adf(adf)
        assert "Hello world" in result

    def test_adf_code_block(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "java"},
                    "content": [
                        {"type": "text", "text": "public void test() {}"}
                    ]
                }
            ]
        }
        result = _extract_text_from_adf(adf)
        assert "public void test()" in result
        assert "```java" in result

    def test_adf_multiple_paragraphs(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "First"}]
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Second"}]
                },
            ]
        }
        result = _extract_text_from_adf(adf)
        assert "First" in result
        assert "Second" in result

    def test_adf_with_hard_break(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Line 1"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "Line 2"},
                    ]
                }
            ]
        }
        result = _extract_text_from_adf(adf)
        assert "Line 1" in result
        assert "Line 2" in result


# ── Comment Extraction Tests ──────────────────────────────────────

class TestExtractComments:
    """Tests for Jira comment extraction."""

    def test_none_returns_empty(self):
        assert _extract_comments(None) == ""

    def test_empty_comments(self):
        assert _extract_comments({"comments": []}) == ""

    def test_single_comment(self):
        data = {
            "comments": [
                {
                    "author": {"displayName": "John Doe"},
                    "body": "I found the root cause",
                    "created": "2026-01-15T10:30:00.000+0000",
                }
            ]
        }
        result = _extract_comments(data)
        assert "John Doe" in result
        assert "I found the root cause" in result
        assert "2026-01-15" in result

    def test_multiple_comments(self):
        data = {
            "comments": [
                {
                    "author": {"displayName": "Alice"},
                    "body": "First comment",
                    "created": "2026-01-15T10:00:00.000+0000",
                },
                {
                    "author": {"displayName": "Bob"},
                    "body": "Second comment",
                    "created": "2026-01-15T11:00:00.000+0000",
                },
            ]
        }
        result = _extract_comments(data)
        assert "Alice" in result
        assert "Bob" in result
        assert "---" in result  # Separator between comments


# ── File Path Detection Tests ─────────────────────────────────────

class TestGuessAffectedFiles:
    """Tests for smart file path extraction from issue text."""

    def test_java_file_path(self):
        text = "The error is in src/main/java/com/app/OrderService.java line 42"
        files = _guess_affected_files(text)
        assert any("OrderService.java" in f for f in files)

    def test_java_fqcn_to_path(self):
        text = "NullPointerException in com.myapp.service.OrderService.calculateTotal"
        files = _guess_affected_files(text)
        assert any("src/main/java/com/myapp/service/OrderService.java" in f for f in files)

    def test_python_file_path(self):
        text = "Error in auth/validators.py at line 87"
        files = _guess_affected_files(text)
        assert any("auth/validators.py" in f for f in files)

    def test_multiple_files(self):
        text = (
            "The bug affects OrderService.java and PaymentService.java. "
            "Stack trace points to com.myapp.util.Calculator"
        )
        files = _guess_affected_files(text)
        assert len(files) >= 2

    def test_no_files(self):
        text = "The login button doesn't work when clicked"
        files = _guess_affected_files(text)
        # May or may not find files — should not crash
        assert isinstance(files, list)

    def test_deduplication(self):
        text = "Error in OrderService.java and also in OrderService.java again"
        files = _guess_affected_files(text)
        java_files = [f for f in files if "OrderService.java" in f]
        assert len(java_files) == 1  # Should be deduplicated

    def test_config_files(self):
        text = "Check the application.properties and pom.xml configuration"
        files = _guess_affected_files(text)
        assert any("application.properties" in f for f in files)
        assert any("pom.xml" in f for f in files)
