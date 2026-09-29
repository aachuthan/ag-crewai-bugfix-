"""Centralized configuration loaded from environment variables."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings


load_dotenv()


class Settings(BaseSettings):
    """Global settings for the bug-fix pipeline."""

    # API keys
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # Model config
    claude_model: str = Field(
        default="anthropic/claude-sonnet-4-6",
        alias="CLAUDE_MODEL",
    )

    # Claude Code SDK config
    claude_code_max_turns: int = Field(default=20, alias="CLAUDE_CODE_MAX_TURNS")
    claude_code_permission_mode: str = Field(
        default="acceptEdits",
        alias="CLAUDE_CODE_PERMISSION_MODE",
    )

    # Flow config
    max_retry_iterations: int = Field(default=3, alias="MAX_RETRY_ITERATIONS")

    # Jira config (optional — only needed for `fix-from-jira` command)
    jira_url: str = Field(default="", alias="JIRA_URL")
    jira_email: str = Field(default="", alias="JIRA_EMAIL")
    jira_api_token: str = Field(default="", alias="JIRA_API_TOKEN")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Return cached global settings instance."""
    return Settings()
