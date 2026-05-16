"""
Decomposer — breaks NLQ into semantic subtask tree.

Takes ONLY the natural language question. No DDL, no schema.
Reasons about WHAT the question asks, not HOW to query it.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from utils.llm import llm_call
from utils.prompt_templates import DECOMPOSER_SYSTEM, DECOMPOSER_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class Subtask:
    id: int
    description: str
    parent_id: Optional[int]  # None for root
    level: int  # 0 = business, 1 = data, 2 = SQL-specific


async def decompose(nlq: str) -> list[Subtask]:
    """
    Decompose a natural language question into semantic subtasks.

    Args:
        nlq: Natural language question.

    Returns:
        List of Subtask objects forming a hierarchy.
    """
    prompt = DECOMPOSER_PROMPT.format(nlq=nlq)

    response = await llm_call(
        prompt=prompt,
        system=DECOMPOSER_SYSTEM,
        response_format="json",
    )

    try:
        subtasks_raw = json.loads(response)
        subtasks = [
            Subtask(
                id=s["id"],
                description=s["description"],
                parent_id=s.get("parent_id"),
                level=s.get("level", 0),
            )
            for s in subtasks_raw
        ]
        logger.info(f"Decomposed into {len(subtasks)} subtasks")
        return subtasks

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse decomposer output: {e}")
        # Fallback: single subtask = the original question
        return [
            Subtask(id=1, description=nlq, parent_id=None, level=0)
        ]


def format_subtask_tree(subtasks: list[Subtask]) -> str:
    """Format subtask tree as a readable string for prompt injection."""
    lines = []
    for s in subtasks:
        indent = "  " * s.level
        parent_info = f" (child of #{s.parent_id})" if s.parent_id else ""
        lines.append(f"{indent}#{s.id}: {s.description}{parent_info}")
    return "\n".join(lines)
