"""Central Langfuse observability wrapper.

Provides a safe fallback if Langfuse is not installed or configured,
ensuring the pipeline never crashes due to missing telemetry tools.
"""

import functools
import logging

from src.config.settings import get_settings


logger = logging.getLogger(__name__)

_LANGFUSE_ENABLED = False
_langfuse_client = None

try:
    from langfuse.decorators import observe as lf_observe
    from langfuse.decorators import langfuse_context
    import litellm
    _HAS_LANGFUSE = True
except ImportError:
    _HAS_LANGFUSE = False


def init_observability() -> bool:
    """Initialize Langfuse and configure LiteLLM callbacks if keys are present."""
    global _LANGFUSE_ENABLED, _langfuse_client
    settings = get_settings()

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return False

    if not _HAS_LANGFUSE:
        logger.warning(
            "Langfuse keys found in environment, but the 'langfuse' package is "
            "not installed. To enable tracing, run: pip install -e '.[observe]'"
        )
        return False

    try:
        from langfuse import Langfuse
        
        # Initialize client
        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host
        )
        
        # Configure CrewAI's underlying LLM engine (LiteLLM) to send traces
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
        
        _LANGFUSE_ENABLED = True
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Langfuse observability: {e}")
        return False


def observe(*args, **kwargs):
    """Safe decorator wrapper for @observe().
    
    If Langfuse is installed, it wraps the function for tracing.
    If not, it acts as a transparent pass-through decorator.
    """
    if _HAS_LANGFUSE:
        return lf_observe(*args, **kwargs)
    else:
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*f_args, **f_kwargs):
                return func(*f_args, **f_kwargs)
            return wrapper
        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])
        return decorator


def update_trace_context(name: str = None, session_id: str = None):
    """Safely update the current trace metadata (e.g., bug title)."""
    if _LANGFUSE_ENABLED:
        langfuse_context.update_current_trace(name=name, session_id=session_id)


def get_trace_url() -> str:
    """Retrieve the URL to the active trace in the Langfuse UI."""
    if _LANGFUSE_ENABLED and _langfuse_client:
        trace_id = langfuse_context.get_current_trace_id()
        if trace_id:
            host = get_settings().langfuse_host.rstrip('/')
            # E.g. https://cloud.langfuse.com/trace/1234-abcd
            return f"{host}/trace/{trace_id}"
    return ""


def flush_traces():
    """Ensure all telemetry is sent before shutdown."""
    if _LANGFUSE_ENABLED and _langfuse_client:
        _langfuse_client.flush()
