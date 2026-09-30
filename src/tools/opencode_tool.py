import asyncio
import logging
import shlex
import threading

from pydantic import BaseModel, ConfigDict, Field
from crewai.tools import BaseTool

from src.config.settings import get_settings
from src.observability.tracer import observe


logger = logging.getLogger(__name__)


def _run_async_safely(coro):
    """Safely execute an async coroutine inside a synchronous method."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
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
        thread.join(timeout=300)

        if exception:
            raise exception
        if thread.is_alive():
            raise TimeoutError("OpenCode query timed out after 300 seconds")
        return result
    else:
        return asyncio.run(coro)


@observe(as_type="generation", name="OpenCode CLI Query")
async def _query_opencode(prompt: str, repo_path: str, model: str) -> str:
    """Execute the OpenCode CLI via subprocess."""
    safe_prompt = shlex.quote(prompt)
    
    # We pass the prompt directly to OpenCode using the model flag
    cmd = f"opencode -m {model} {safe_prompt}"
    
    logger.debug(f"Executing OpenCode: {cmd}")
    
    process = await asyncio.create_subprocess_shell(
        cmd,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await process.communicate()
    output = stdout.decode('utf-8', errors='replace')
    err = stderr.decode('utf-8', errors='replace')
    
    if process.returncode != 0:
        return f"Error executing OpenCode:\n{err}\n{output}"
        
    return output


class OpenCodeInput(BaseModel):
    """Input schema for OpenCode tools."""
    prompt: str = Field(description="The natural language instruction for OpenCode.")


class OpenCodeReadTool(BaseTool):
    """Read-only tool using OpenCode."""
    name: str = "opencode_read"
    description: str = (
        "Use OpenCode to explore and read the codebase. "
        "Useful for searching, finding files, and reading code."
    )
    args_schema: type[BaseModel] = OpenCodeInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    repo_path: str = Field(description="The target repository path")

    def _run(self, prompt: str) -> str:
        settings = get_settings()
        # Enforce read-only constraint via prompt injection
        safe_prompt = (
            f"READ ONLY TASK: {prompt}\n\n"
            "You are operating in a read-only environment. Do NOT modify any files."
        )
        return _run_async_safely(_query_opencode(safe_prompt, self.repo_path, settings.opencode_model))


class OpenCodeEditTool(BaseTool):
    """Read-write tool using OpenCode."""
    name: str = "opencode_edit"
    description: str = (
        "Use OpenCode to write code and edit files. "
        "Useful for implementing bug fixes and writing tests."
    )
    args_schema: type[BaseModel] = OpenCodeInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    repo_path: str = Field(description="The target repository path")

    def _run(self, prompt: str) -> str:
        settings = get_settings()
        return _run_async_safely(_query_opencode(prompt, self.repo_path, settings.opencode_model))
