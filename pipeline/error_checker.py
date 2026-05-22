"""
Error Checker — classifies Snowflake execution errors.

Pure string matching on error messages — no LLM needed.
Covers common Snowflake execution failure modes.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ErrorCheckResult:
    has_error: bool
    error_message: str
    error_type: str  # "syntax" | "runtime" | "timeout" | "permission" | "none"


# Error patterns: (substring to match, error_type)
# Order matters — first match wins
_ERROR_PATTERNS = [
    # Syntax errors
    ("SQL compilation error", "syntax"),
    ("Object does not exist", "syntax"),
    ("does not exist or not authorized", "syntax"),
    ("Ambiguous column name", "syntax"),
    ("Window function not allowed", "syntax"),
    ("Unsupported subquery type", "syntax"),
    ("Binding error", "syntax"),
    ("syntax error", "syntax"),
    ("invalid identifier", "syntax"),
    ("unexpected", "syntax"),
    # Runtime errors
    ("Expression type does not match column data type", "runtime"),
    ("Numeric value", "runtime"),
    ("division by zero", "runtime"),
    ("Division by zero", "runtime"),
    ("out of range", "runtime"),
    ("cannot convert", "runtime"),
    ("invalid value", "runtime"),
    # Timeout
    ("timed out", "timeout"),
    ("statement timeout", "timeout"),
    ("query timeout", "timeout"),
    ("execution timeout", "timeout"),
    # Permission
    ("Insufficient privileges", "permission"),
    ("not authorized", "permission"),
    ("Access denied", "permission"),
]


def check_error(exec_result) -> ErrorCheckResult:
    """
    Classify an execution result as success or categorized error.

    Args:
        exec_result: ExecutionResult from executor.py

    Returns:
        ErrorCheckResult with has_error, error_message, error_type.
    """
    if exec_result.success and exec_result.data is not None:
        return ErrorCheckResult(
            has_error=False, error_message="", error_type="none"
        )

    error_msg = exec_result.error_message or "Unknown error"
    error_type = _classify_error(error_msg)

    logger.warning(f"Error classified as '{error_type}': {error_msg[:200]}")

    return ErrorCheckResult(
        has_error=True, error_message=error_msg, error_type=error_type
    )


def _classify_error(error_message: str) -> str:
    """Classify error message by pattern matching."""
    msg_lower = error_message.lower()

    for pattern, error_type in _ERROR_PATTERNS:
        if pattern.lower() in msg_lower:
            return error_type

    # Default: treat as runtime if we can't classify
    return "runtime"
