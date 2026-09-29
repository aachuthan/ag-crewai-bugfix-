"""Tests for agent factory — verifies agent creation and tool assignments."""

import pytest

from src.agents.factory import (
    create_bug_analyst,
    create_code_investigator,
    create_code_reviewer,
    create_fix_developer,
    create_test_engineer,
)
from src.tools.claude_code_tool import ClaudeCodeEditTool, ClaudeCodeReadTool
from src.tools.git_tool import GitTool


class TestAgentFactory:
    """Verify that agents are created with correct tools (least-privilege)."""

    def test_bug_analyst_is_read_only(self, sample_git_repo):
        """Bug analyst should only have read tools."""
        agent = create_bug_analyst(str(sample_git_repo))
        tool_types = [type(t) for t in agent.tools]

        assert ClaudeCodeReadTool in tool_types
        assert ClaudeCodeEditTool not in tool_types
        assert GitTool not in tool_types

    def test_code_investigator_is_read_only(self, sample_git_repo):
        """Code investigator should only have read tools."""
        agent = create_code_investigator(str(sample_git_repo))
        tool_types = [type(t) for t in agent.tools]

        assert ClaudeCodeReadTool in tool_types
        assert ClaudeCodeEditTool not in tool_types
        assert GitTool not in tool_types

    def test_fix_developer_has_write_and_git(self, sample_git_repo):
        """Fix developer needs edit tools and git."""
        agent = create_fix_developer(str(sample_git_repo))
        tool_types = [type(t) for t in agent.tools]

        assert ClaudeCodeEditTool in tool_types
        assert GitTool in tool_types
        assert ClaudeCodeReadTool not in tool_types

    def test_test_engineer_has_write_and_git(self, sample_git_repo):
        """Test engineer needs edit tools (to write tests) and git."""
        agent = create_test_engineer(str(sample_git_repo))
        tool_types = [type(t) for t in agent.tools]

        assert ClaudeCodeEditTool in tool_types
        assert GitTool in tool_types
        assert ClaudeCodeReadTool not in tool_types

    def test_code_reviewer_is_read_only(self, sample_git_repo):
        """Code reviewer should only have read tools."""
        agent = create_code_reviewer(str(sample_git_repo))
        tool_types = [type(t) for t in agent.tools]

        assert ClaudeCodeReadTool in tool_types
        assert ClaudeCodeEditTool not in tool_types
        assert GitTool not in tool_types

    def test_agents_have_delegation_disabled(self, sample_git_repo):
        """All specialist agents should not delegate."""
        agents = [
            create_bug_analyst(str(sample_git_repo)),
            create_code_investigator(str(sample_git_repo)),
            create_fix_developer(str(sample_git_repo)),
            create_test_engineer(str(sample_git_repo)),
            create_code_reviewer(str(sample_git_repo)),
        ]
        for agent in agents:
            assert agent.allow_delegation is False, (
                f"Agent '{agent.role}' should have delegation disabled"
            )
