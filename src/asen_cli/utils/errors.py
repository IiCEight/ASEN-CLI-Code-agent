class AsenError(Exception):
    """Base exception for asen cli."""


class ConfigError(AsenError):
    """Raised when configuration is invalid."""


class SafetyError(AsenError):
    """Raised when an operation violates the workspace safety boundary."""


class ToolError(AsenError):
    """Raised when a tool cannot complete its operation."""


class LlmError(AsenError):
    """Raised when the LLM request or response is invalid."""
