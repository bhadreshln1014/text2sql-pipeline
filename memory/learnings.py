"""
Learnings Memory — read/write/append learnings.md + error generalization.

The learnings file is append-only and contains generalizable Snowflake dialect rules.
error_to_learning() uses an LLM call to convert raw errors into reusable rules.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from utils.llm import llm_call
from utils.prompt_templates import ERROR_TO_LEARNING_SYSTEM, ERROR_TO_LEARNING_PROMPT

logger = logging.getLogger(__name__)

# Separator between entries in learnings.md
_ENTRY_SEPARATOR = "\n---\n"


@dataclass
class LearningEntry:
    error_type: str
    pattern: str  # What went wrong (generalized)
    fix: str  # How to fix it (generalized)
    example_sql: str  # Abbreviated example
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_markdown(self) -> str:
        """Format as a markdown entry for learnings.md."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M")
        return (
            f"## [{ts}] [{self.error_type}]\n"
            f"**Pattern:** {self.pattern}\n"
            f"**Fix:** {self.fix}\n"
            f"**Example:** `{self.example_sql}`"
        )


def read_learnings(
    path: str = "data/learnings.md", max_entries: Optional[int] = None
) -> str:
    """
    Read learnings.md content for prompt injection.

    Args:
        path: Path to learnings.md.
        max_entries: If set, returns only the most recent N entries.

    Returns:
        String content of learnings (possibly truncated).
    """
    if not os.path.exists(path):
        return ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return ""

        if max_entries is not None and max_entries > 0:
            entries = content.split(_ENTRY_SEPARATOR)
            entries = [e.strip() for e in entries if e.strip()]
            if len(entries) > max_entries:
                entries = entries[-max_entries:]
                logger.debug(f"Truncated learnings to most recent {max_entries} entries")
            content = _ENTRY_SEPARATOR.join(entries)

        return content

    except Exception as e:
        logger.warning(f"Could not read learnings file: {e}")
        return ""


def append_learning(entry: LearningEntry, path: str = "data/learnings.md") -> bool:
    """
    Append a learning entry to learnings.md.
    Skips if an identical pattern or fix is already present.

    Args:
        entry: LearningEntry to append.
        path: Path to learnings.md.
        
    Returns:
        bool: True if appended, False if skipped (duplicate).
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # Deduplication: compare normalized **Pattern:** lines from existing entries
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        existing_patterns = {
            line.replace("**Pattern:**", "").strip().lower()
            for line in content.splitlines()
            if line.startswith("**Pattern:**")
        }
        if entry.pattern.strip().lower() in existing_patterns:
            logger.info(f"Skipped duplicate learning [{entry.error_type}]: {entry.pattern[:60]}...")
            return False

    markdown = entry.to_markdown()

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{markdown}\n{_ENTRY_SEPARATOR}")

    logger.info(f"Appended learning [{entry.error_type}]: {entry.pattern[:60]}...")
    return True


async def error_to_learning(error, failed_sql: str, column_roster: str = "") -> LearningEntry:
    """
    LLM call that converts a raw Snowflake error into a generalizable learning.

    Generalizability is enforced at the prompt level — the LLM rewrites
    the raw error as a general Snowflake dialect rule, NOT a fix for
    this specific query.

    Args:
        error: ErrorCheckResult from error_checker.py.
        failed_sql: The SQL that caused the error.
        column_roster: Optional column roster for table-scoped diagnosis.

    Returns:
        LearningEntry with generalized pattern and fix.
    """
    roster_section = ""
    if column_roster:
        roster_section = f"COLUMN ROSTER (use to diagnose which table owns which column):\n{column_roster}"

    prompt = ERROR_TO_LEARNING_PROMPT.format(
        error_type=error.error_type,
        error_message=error.error_message[:500],  # Truncate long errors
        failed_sql=failed_sql[:500],  # Truncate long SQL
        column_roster=roster_section,
    )

    try:
        response = await llm_call(
            prompt=prompt,
            system=ERROR_TO_LEARNING_SYSTEM,
            response_format="json",
        )

        data = json.loads(response)
        return LearningEntry(
            error_type=data.get("error_type", error.error_type),
            pattern=data.get("pattern", error.error_message[:100]),
            fix=data.get("fix", "Review error and adjust SQL"),
            example_sql=data.get("example", ""),
        )

    except Exception as e:
        logger.warning(f"Failed to generalize error via LLM, using raw error: {e}")
        # Fallback: use the raw error (less generalizable but still useful)
        return LearningEntry(
            error_type=error.error_type,
            pattern=f"Raw error: {error.error_message[:100]}",
            fix="Review the Snowflake error and adjust SQL accordingly",
            example_sql="",
        )
