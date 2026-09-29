"""Main Flow orchestrator for the bug-fix pipeline.

Flow: Triage → Investigate → Fix → Test → Route → Review → Route → Done/Retry

Key design decisions:
- Structured JSON output parsing (not string matching)
- Retry loop correctly re-enters the @listen chain via implement_fix_retry
- Both test failures AND review rejections trigger retries
- try/except with error_log around every crew kickoff
- State fields explicitly populated from parsed output at each phase
"""

import json
import logging

from crewai.flow.flow import Flow, listen, router, start

from src.crews.crew_factory import (
    create_fix_crew,
    create_investigation_crew,
    create_review_crew,
    create_test_crew,
    create_triage_crew,
)
from src.models.outputs import (
    FixOutput,
    InvestigationOutput,
    ReviewOutput,
    TestOutput,
    TriageOutput,
)
from src.models.state import BugFixState, BugSeverity, ReviewVerdict


logger = logging.getLogger(__name__)


def _safe_parse_json(result, model_class):
    """Safely parse crew output into a structured Pydantic model.

    CrewAI's output_json returns a dict when parsing succeeds,
    or raw text if the LLM didn't comply with the schema.
    This function handles both cases gracefully.

    Returns:
        Parsed model instance, or None if parsing fails.
    """
    try:
        # CrewAI may return a dict directly when output_json succeeds
        if isinstance(result, dict):
            return model_class(**result)

        # Try parsing the string as JSON
        result_text = str(result)

        # Sometimes the result is wrapped in markdown code fences
        if "```json" in result_text:
            start_idx = result_text.index("```json") + 7
            end_idx = result_text.index("```", start_idx)
            result_text = result_text[start_idx:end_idx].strip()
        elif "```" in result_text:
            start_idx = result_text.index("```") + 3
            end_idx = result_text.index("```", start_idx)
            result_text = result_text[start_idx:end_idx].strip()

        parsed = json.loads(result_text)
        return model_class(**parsed)
    except (json.JSONDecodeError, TypeError, ValueError, IndexError) as e:
        logger.warning(f"Could not parse structured output as {model_class.__name__}: {e}")
        return None


class BugFixFlow(Flow[BugFixState]):
    """Orchestrates the complete bug-fix pipeline.

    Phases:
        1. Triage   — classify severity, category, suspect files
        2. Investigate — root cause analysis with code tracing
        3. Fix      — implement minimal code fix on a feature branch
        4. Test     — write regression tests, run full suite
        5. Review   — quality gate with approve/reject/needs_changes

    Retry logic:
        - Test failures → retry fix (up to max_iterations)
        - Review needs_changes → retry fix (up to max_iterations)
        - Review rejected / max retries → report failure
    """

    # ─── Phase 1: Triage ──────────────────────────────────────────

    @start()
    def triage_bug(self):
        """Entry point: classify and triage the bug report."""
        logger.info("=" * 60)
        logger.info("🔍 PHASE 1: Bug Triage")
        logger.info("=" * 60)

        bug = self.state.bug_report
        bug_context = (
            f"Title: {bug.title}\n"
            f"Description: {bug.description}\n"
            f"Steps to Reproduce: {bug.steps_to_reproduce}\n"
            f"Error Logs:\n{bug.error_logs}\n"
            f"Known Affected Files: {', '.join(bug.affected_files) or 'Unknown'}"
        )

        try:
            crew = create_triage_crew(bug.repository_path, bug_context)
            result = crew.kickoff()
        except Exception as e:
            self.state.error_log.append(f"Triage failed: {e}")
            logger.error(f"Triage crew failed: {e}")
            # Default triage so pipeline can continue
            self.state.severity = BugSeverity.MEDIUM
            self.state.triage_summary = (
                f"Triage failed ({e}). Proceeding with provided context."
            )
            self.state.suspect_files = bug.affected_files
            return self.state.triage_summary

        # Parse structured output into state
        parsed = _safe_parse_json(result, TriageOutput)
        if parsed:
            try:
                self.state.severity = BugSeverity(parsed.severity.lower())
            except ValueError:
                self.state.severity = BugSeverity.MEDIUM
            self.state.category = parsed.category
            self.state.triage_summary = parsed.summary
            self.state.suspect_files = parsed.initial_suspect_files
        else:
            # Fallback: store raw text
            self.state.severity = BugSeverity.MEDIUM
            self.state.triage_summary = str(result)
            self.state.suspect_files = bug.affected_files

        logger.info(f"✅ Triage complete. Severity: {self.state.severity.value}")
        return self.state.triage_summary

    # ─── Phase 2: Investigation ───────────────────────────────────

    @listen(triage_bug)
    def investigate_bug(self, triage_result: str):
        """Deep investigation to find root cause."""
        logger.info("=" * 60)
        logger.info("🕵️ PHASE 2: Root Cause Investigation")
        logger.info("=" * 60)

        bug = self.state.bug_report
        suspect_files = self.state.suspect_files or bug.affected_files

        try:
            crew = create_investigation_crew(
                bug.repository_path, triage_result, suspect_files,
            )
            result = crew.kickoff()
        except Exception as e:
            self.state.error_log.append(f"Investigation failed: {e}")
            logger.error(f"Investigation crew failed: {e}")
            self.state.root_cause = (
                f"Investigation failed ({e}). Using triage info as context."
            )
            return self.state.root_cause

        parsed = _safe_parse_json(result, InvestigationOutput)
        if parsed:
            self.state.root_cause = parsed.root_cause
            self.state.affected_files_discovered = parsed.affected_files
            self.state.suggested_approach = parsed.suggested_approach
        else:
            self.state.root_cause = str(result)

        logger.info("✅ Investigation complete. Root cause identified.")
        return self.state.root_cause

    # ─── Phase 3: Fix Implementation ─────────────────────────────

    @listen(investigate_bug)
    def implement_fix(self, context: str):
        """Implement the actual code fix."""
        return self._do_implement_fix(context)

    def _do_implement_fix(self, context: str):
        """Shared fix implementation logic (used by both first attempt and retries)."""
        logger.info("=" * 60)
        logger.info(
            f"🛠️ PHASE 3: Implementing Fix "
            f"(attempt {self.state.current_iteration + 1}/{self.state.max_iterations + 1})"
        )
        logger.info("=" * 60)

        bug = self.state.bug_report
        affected_files = self.state.affected_files_discovered or bug.affected_files

        # Build context, incorporating retry feedback when applicable
        root_cause_context = self.state.root_cause or context
        if self.state.current_iteration > 0:
            root_cause_context = (
                f"⚠️ RETRY ATTEMPT {self.state.current_iteration}. "
                f"The previous fix was insufficient.\n\n"
                f"Feedback from previous attempt:\n"
                f"{self.state.review_comments or self.state.test_results or 'N/A'}\n\n"
                f"Original root cause:\n{self.state.root_cause}\n\n"
                f"Suggested approach:\n{self.state.suggested_approach or 'N/A'}"
            )

        try:
            crew = create_fix_crew(
                bug.repository_path,
                root_cause_context,
                affected_files,
                bug.title,
            )
            result = crew.kickoff()
        except Exception as e:
            self.state.error_log.append(f"Fix failed: {e}")
            logger.error(f"Fix crew failed: {e}")
            self.state.fix_description = f"Fix implementation failed: {e}"
            return self.state.fix_description

        parsed = _safe_parse_json(result, FixOutput)
        if parsed:
            self.state.fix_description = parsed.fix_description
            self.state.modified_files = parsed.modified_files
            self.state.git_branch = parsed.git_branch
            self.state.diff_output = parsed.diff
        else:
            self.state.fix_description = str(result)

        logger.info(
            f"✅ Fix implemented. "
            f"Branch: {self.state.git_branch}, "
            f"Files: {', '.join(self.state.modified_files)}"
        )
        return self.state.fix_description

    # ─── Phase 4: Testing ─────────────────────────────────────────

    @listen(implement_fix)
    def run_tests(self, fix_result: str):
        """Write regression tests and run the test suite."""
        return self._do_run_tests(fix_result)

    def _do_run_tests(self, fix_result: str):
        """Shared test execution logic."""
        logger.info("=" * 60)
        logger.info("🧪 PHASE 4: Testing")
        logger.info("=" * 60)

        bug = self.state.bug_report
        modified_files = self.state.modified_files

        try:
            crew = create_test_crew(
                bug.repository_path, fix_result, modified_files,
            )
            result = crew.kickoff()
        except Exception as e:
            self.state.error_log.append(f"Testing failed: {e}")
            logger.error(f"Test crew failed: {e}")
            self.state.tests_passed = False
            self.state.test_results = f"Test execution failed: {e}"
            return self.state.test_results

        parsed = _safe_parse_json(result, TestOutput)
        if parsed:
            self.state.tests_written = parsed.tests_written
            self.state.test_results = parsed.test_execution_output
            self.state.tests_passed = parsed.all_passed
        else:
            self.state.test_results = str(result)
            # Conservative: if we can't parse, assume failure
            self.state.tests_passed = False

        logger.info(f"✅ Tests complete. All passed: {self.state.tests_passed}")
        return self.state.test_results

    # ─── Router: Test Results ─────────────────────────────────────

    @router(run_tests)
    def test_gate(self, test_result: str) -> str:
        """Route based on test results: pass → review, fail → retry or fail."""
        if not self.state.tests_passed:
            if self.state.current_iteration < self.state.max_iterations:
                self.state.current_iteration += 1
                logger.warning(
                    f"❌ Tests failed. Retrying "
                    f"({self.state.current_iteration}/{self.state.max_iterations})"
                )
                return "retry"
            logger.error("❌ Tests failed. Max retries exceeded.")
            return "failed"
        return "tests_passed"

    # ─── Phase 5: Code Review ─────────────────────────────────────

    @listen("tests_passed")
    def review_fix(self):
        """Code review as quality gate."""
        logger.info("=" * 60)
        logger.info("📋 PHASE 5: Code Review")
        logger.info("=" * 60)

        bug = self.state.bug_report

        try:
            crew = create_review_crew(
                bug.repository_path,
                self.state.diff_output or "(diff not captured)",
                self.state.fix_description or "",
                self.state.test_results or "",
            )
            result = crew.kickoff()
        except Exception as e:
            self.state.error_log.append(f"Review failed: {e}")
            logger.error(f"Review crew failed: {e}")
            # If review crashes, don't auto-approve — require manual review
            self.state.review_verdict = ReviewVerdict.NEEDS_CHANGES
            self.state.review_comments = (
                f"Review failed ({e}). Manual review required."
            )
            return self.state.review_comments

        parsed = _safe_parse_json(result, ReviewOutput)
        if parsed:
            try:
                self.state.review_verdict = ReviewVerdict(parsed.verdict.lower())
            except ValueError:
                self.state.review_verdict = ReviewVerdict.NEEDS_CHANGES
            self.state.review_comments = parsed.comments
        else:
            self.state.review_comments = str(result)
            self.state.review_verdict = ReviewVerdict.NEEDS_CHANGES

        logger.info(f"✅ Review verdict: {self.state.review_verdict.value}")
        return self.state.review_comments

    # ─── Router: Review Verdict ───────────────────────────────────

    @router(review_fix)
    def review_gate(self, review_result: str) -> str:
        """Route based on review: approved → done, needs_changes → retry, rejected → fail."""
        if self.state.review_verdict == ReviewVerdict.APPROVED:
            return "approved"
        elif self.state.review_verdict == ReviewVerdict.NEEDS_CHANGES:
            if self.state.current_iteration < self.state.max_iterations:
                self.state.current_iteration += 1
                logger.warning(
                    f"🔄 Review: needs_changes. Retrying "
                    f"({self.state.current_iteration}/{self.state.max_iterations})"
                )
                return "retry"
        # REJECTED or max retries exceeded
        return "failed"

    # ─── Retry Path ───────────────────────────────────────────────
    # The retry flow re-enters the pipeline at implement_fix and
    # chains through run_tests → test_gate → review_fix → review_gate
    # via the @listen decorators on implement_fix_retry and run_tests_retry.

    @listen("retry")
    def retry_fix(self):
        """Re-enter the fix phase with feedback from the failed attempt."""
        logger.info(
            f"🔄 Retry attempt {self.state.current_iteration}/{self.state.max_iterations}"
        )
        feedback = self.state.review_comments or self.state.test_results or ""
        # Delegate to shared implementation
        return self._do_implement_fix(feedback)

    @listen(retry_fix)
    def run_tests_after_retry(self, fix_result: str):
        """Run tests after a retry fix — chains back to test_gate router."""
        return self._do_run_tests(fix_result)

    # Wire retry test results back through the same gate
    @router(run_tests_after_retry)
    def test_gate_after_retry(self, test_result: str) -> str:
        """Same routing logic as test_gate, reused after retry."""
        return self.test_gate(test_result)

    # ─── Terminal States ──────────────────────────────────────────

    @listen("approved")
    def report_success(self):
        """Pipeline completed successfully — fix is ready for PR."""
        logger.info("=" * 60)
        logger.info("✅ SUCCESS: Bug fix approved!")
        logger.info(f"   Branch: {self.state.git_branch}")
        logger.info(f"   Files changed: {', '.join(self.state.modified_files)}")
        logger.info(f"   Tests: {len(self.state.tests_written)} new test(s)")
        logger.info(f"   Iterations: {self.state.current_iteration + 1}")
        logger.info("=" * 60)

    @listen("failed")
    def report_failure(self):
        """Pipeline failed — manual intervention required."""
        logger.info("=" * 60)
        logger.error("❌ FAILED: Bug fix could not be completed.")
        logger.error(
            f"   Iterations used: {self.state.current_iteration}/{self.state.max_iterations}"
        )
        logger.error(f"   Last verdict: {self.state.review_verdict}")
        logger.error(f"   Last test result: {self.state.tests_passed}")
        if self.state.error_log:
            logger.error(f"   Errors encountered:")
            for err in self.state.error_log:
                logger.error(f"     - {err}")
        logger.info("=" * 60)
