"""
Generator — produces Snowflake SQL from context, subtasks, and feedback.

Handles three modes:
1. First attempt: subtask tree + context + learnings
2. Requirements retry: + failed subtasks + previous SQL + score
3. Execution retry: + error message + previous SQL + attempt
"""

import logging
import re

from pipeline.decomposer import Subtask, format_subtask_tree
from utils.llm import llm_call
from utils.prompt_templates import (
    GENERATOR_SYSTEM,
    GENERATOR_PROMPT,
    GENERATOR_RETRY_PROMPT,
    GENERATOR_ERROR_RETRY_PROMPT,
)

logger = logging.getLogger(__name__)


async def generate(
    nlq: str,
    ddl: str,
    docs: str,
    learnings: str,
    subtask_tree: list[Subtask],
    exploration_transcript: str = "",
    prev_feedback: dict = None,
) -> str:
    """
    Generate Snowflake SQL.

    Args:
        nlq: Natural language question.
        ddl: DDL schema text.
        docs: External documentation text.
        learnings: Content from learnings.md.
        subtask_tree: List of Subtask objects.
        prev_feedback: Optional feedback dict with one of:
            - Requirements failure: {failed_subtasks, previous_sql, score, attempt}
            - Execution error: {error, previous_sql, attempt}

    Returns:
        Raw SQL string.
    """
    subtask_text = format_subtask_tree(subtask_tree)
    docs_section = f"ADDITIONAL DOCUMENTATION:\n{docs}" if docs else ""
    learnings_text = learnings if learnings else "No learnings yet."

    if prev_feedback is None:
        # First attempt
        prompt = GENERATOR_PROMPT.format(
            ddl=ddl,
            docs_section=docs_section,
            learnings=learnings_text,
            subtask_tree=subtask_text,
            exploration_transcript=exploration_transcript,
            nlq=nlq,
        )
        logger.info("Generating SQL (first attempt)")

    elif "failed_subtasks" in prev_feedback:
        # Requirements retry
        failed_text = _format_failed_subtasks(prev_feedback["failed_subtasks"])
        prompt = GENERATOR_RETRY_PROMPT.format(
            ddl=ddl,
            docs_section=docs_section,
            learnings=learnings_text,
            subtask_tree=subtask_text,
            exploration_transcript=exploration_transcript,
            nlq=nlq,
            previous_sql=prev_feedback["previous_sql"],
            score=prev_feedback["score"],
            attempt=prev_feedback["attempt"],
            failed_subtasks=failed_text,
        )
        logger.info(
            f"Generating SQL (requirements retry #{prev_feedback['attempt']}, "
            f"score={prev_feedback['score']})"
        )

    elif "error" in prev_feedback:
        # Execution error retry
        error = prev_feedback["error"]
        prompt = GENERATOR_ERROR_RETRY_PROMPT.format(
            ddl=ddl,
            docs_section=docs_section,
            learnings=learnings_text,
            subtask_tree=subtask_text,
            exploration_transcript=exploration_transcript,
            nlq=nlq,
            previous_sql=prev_feedback["previous_sql"],
            attempt=prev_feedback["attempt"],
            error_type=error.error_type,
            error_message=error.error_message,
        )
        logger.info(
            f"Generating SQL (execution retry #{prev_feedback['attempt']}, "
            f"error_type={error.error_type})"
        )
    else:
        raise ValueError(f"Unknown feedback format: {prev_feedback.keys()}")

    sql = await llm_call(
        prompt=prompt,
        system=GENERATOR_SYSTEM,
        response_format="text",
    )

    # Strip any markdown code block wrappers
    sql = _clean_sql_output(sql)

    logger.debug(f"Generated SQL ({len(sql)} chars)")
    return sql


def _format_failed_subtasks(failed_subtasks: list) -> str:
    """Format failed subtasks for the retry prompt."""
    lines = []
    for fs in failed_subtasks:
        if isinstance(fs, dict):
            lines.append(f"- Subtask #{fs.get('subtask_id', '?')}: {fs.get('reason', 'no reason')}")
        else:
            lines.append(f"- {fs}")
    return "\n".join(lines)


def _clean_sql_output(sql: str) -> str:
    """Remove markdown wrappers and thinking blocks from LLM SQL output."""
    sql = sql.strip()
    match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?\s*```", sql, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # No sql block — strip any <thinking>...</thinking> block and return remainder
    sql = re.sub(r"<thinking>.*?</thinking>", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
    return sql
