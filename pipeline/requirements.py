"""
Requirements Checker — verifies SQL against subtask tree.

LLM evaluates each subtask independently (not holistically).
Returns per-subtask verdicts with algorithmic scoring on top.
"""

import json
import logging
from dataclasses import dataclass, field

from pipeline.decomposer import Subtask, format_subtask_tree
from utils.llm import llm_call
from utils.prompt_templates import REQUIREMENTS_SYSTEM, REQUIREMENTS_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class RequirementsResult:
    score: float  # n_satisfied / total
    passed: bool  # score == 1.0
    subtask_results: list  # [{subtask_id, satisfied, reason}]
    failed_subtasks: list  # Filtered list of failures with reasons


async def check_requirements(sql: str, subtask_tree: list[Subtask], checker_model: str = None) -> RequirementsResult:
    """
    Check whether SQL satisfies all subtasks.

    Args:
        sql: Generated SQL string.
        subtask_tree: List of Subtask objects to verify against.

    Returns:
        RequirementsResult with score, pass/fail, and per-subtask details.
    """
    subtask_text = format_subtask_tree(subtask_tree)

    prompt = REQUIREMENTS_PROMPT.format(
        sql=sql,
        subtask_tree=subtask_text,
    )

    response = await llm_call(
        prompt=prompt,
        system=REQUIREMENTS_SYSTEM,
        response_format="json",
        model=checker_model,
    )

    try:
        results_raw = json.loads(response)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to parse requirements checker output: {e}")
        # Fail-safe: assume all subtasks failed
        return RequirementsResult(
            score=0.0,
            passed=False,
            subtask_results=[],
            failed_subtasks=[
                {"subtask_id": s.id, "reason": "Requirements checker parse failure"}
                for s in subtask_tree
            ],
        )

    # Calculate score — always divide by the actual number of subtasks, not
    # the number the LLM happened to return (it may return fewer than asked)
    total = len(subtask_tree)
    satisfied = sum(1 for r in results_raw if r.get("satisfied", False))
    score = satisfied / total if total > 0 else 0.0

    # Extract failures
    failed = [r for r in results_raw if not r.get("satisfied", False)]

    result = RequirementsResult(
        score=round(score, 3),
        passed=(score == 1.0),
        subtask_results=results_raw,
        failed_subtasks=failed,
    )

    logger.info(
        f"Requirements check: {satisfied}/{total} passed "
        f"(score={result.score}, passed={result.passed})"
    )

    return result
