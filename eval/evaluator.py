"""
Evaluator — offline evaluation + error taxonomy extraction.

Compares output CSVs against gold standards using Spider2-Snow evaluation logic.
Extracts generalizable learnings from failures via LLM taxonomy analysis.
"""

import json
import logging
import os
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from memory.learnings import LearningEntry
from utils.llm import llm_call
from utils.prompt_templates import TAXONOMY_SYSTEM, TAXONOMY_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class FailureRecord:
    instance_id: str
    error_type: str  # "execution_error" | "wrong_result"
    sql: str
    error_message: str = ""
    details: str = ""
    nlq: str = ""


@dataclass
class EvalReport:
    total: int = 0
    correct: int = 0
    wrong_result: int = 0
    execution_error: int = 0
    missing: int = 0
    accuracy: float = 0.0
    failures: list = field(default_factory=list)
    per_instance: dict = field(default_factory=dict)


class Evaluator:
    """Offline evaluator for Spider2-Snow benchmark."""

    def __init__(self, config: dict):
        self.gold_dir = config.get(
            "gold_dir", "../spider2-snow/evaluation_suite/gold/exec_result"
        )
        self.eval_standard_path = config.get(
            "eval_standard_path",
            "../spider2-snow/evaluation_suite/gold/spider2snow_eval.jsonl",
        )
        self.outputs_path = config.get("outputs_path", "data/outputs")

        # Load evaluation standards
        self.eval_standards = self._load_eval_standards()

    def _load_eval_standards(self) -> dict:
        """Load evaluation standards from spider2snow_eval.jsonl."""
        standards = {}
        if not os.path.exists(self.eval_standard_path):
            logger.warning(f"Eval standards not found: {self.eval_standard_path}")
            return standards

        with open(self.eval_standard_path, "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line.strip())
                standards[item["instance_id"]] = item

        logger.info(f"Loaded {len(standards)} evaluation standards")
        return standards

    def run_offline_eval(self, dataset: dict = None) -> EvalReport:
        """
        Compare all output CSVs against gold CSVs.

        Returns:
            EvalReport with accuracy, failure details, and per-instance breakdown.
        """
        report = EvalReport()
        failures = []

        for instance_id, standard in self.eval_standards.items():
            pred_path = os.path.join(self.outputs_path, f"{instance_id}.csv")
            sql_path = os.path.join(self.outputs_path, f"{instance_id}.sql")

            report.total += 1

            nlq = ""
            if dataset and instance_id in dataset:
                nlq = dataset[instance_id].get("instruction", dataset[instance_id].get("question", ""))

            # Load predicted SQL (for failure records)
            pred_sql = ""
            if os.path.exists(sql_path):
                with open(sql_path, "r", encoding="utf-8") as f:
                    pred_sql = f.read()

            # Check if prediction exists
            if not os.path.exists(pred_path):
                report.missing += 1
                report.per_instance[instance_id] = "missing"
                failures.append(FailureRecord(
                    instance_id=instance_id,
                    error_type="execution_error",
                    sql=pred_sql,
                    error_message="No prediction CSV found",
                    nlq=nlq,
                ))
                continue

            # Load predicted result
            try:
                pred_df = pd.read_csv(pred_path)
            except Exception as e:
                report.execution_error += 1
                report.per_instance[instance_id] = "execution_error"
                failures.append(FailureRecord(
                    instance_id=instance_id,
                    error_type="execution_error",
                    sql=pred_sql,
                    error_message=f"Could not read prediction CSV: {e}",
                    nlq=nlq,
                ))
                continue

            # Load gold result(s)
            gold_dfs = self._load_gold_results(instance_id, standard)
            if not gold_dfs:
                report.missing += 1
                report.per_instance[instance_id] = "missing_gold"
                continue

            # Compare
            condition_cols = standard.get("condition_cols", [])
            ignore_order = standard.get("ignore_order", False)

            is_correct = compare_multi_pandas_table(
                pred_df, gold_dfs, condition_cols, ignore_order
            )

            if is_correct:
                report.correct += 1
                report.per_instance[instance_id] = "correct"
            else:
                report.wrong_result += 1
                report.per_instance[instance_id] = "wrong_result"
                failures.append(FailureRecord(
                    instance_id=instance_id,
                    error_type="wrong_result",
                    sql=pred_sql,
                    details=f"Result mismatch: pred shape={pred_df.shape}, gold shape={gold_dfs[0].shape}",
                    nlq=nlq,
                ))

        report.accuracy = report.correct / report.total if report.total > 0 else 0.0
        report.failures = failures

        logger.info(
            f"Eval: {report.correct}/{report.total} correct "
            f"({report.accuracy:.1%}), {report.wrong_result} wrong, "
            f"{report.execution_error} exec errors, {report.missing} missing"
        )

        return report

    def _load_gold_results(self, instance_id: str, standard: dict) -> list:
        """Load gold result CSV(s) for an instance."""
        gold_dfs = []

        # Try single gold file
        gold_path = os.path.join(self.gold_dir, f"{instance_id}.csv")
        if os.path.exists(gold_path):
            try:
                gold_dfs.append(pd.read_csv(gold_path))
            except Exception as e:
                logger.warning(f"Could not read gold CSV {gold_path}: {e}")

        # Try numbered gold files (instance_id_0.csv, instance_id_1.csv, ...)
        for i in range(10):
            numbered_path = os.path.join(self.gold_dir, f"{instance_id}_{i}.csv")
            if os.path.exists(numbered_path):
                try:
                    gold_dfs.append(pd.read_csv(numbered_path))
                except Exception as e:
                    logger.warning(f"Could not read gold CSV {numbered_path}: {e}")

        # Try letter-suffixed gold files (instance_id_a.csv, instance_id_b.csv, ...)
        for ch in "abcdefghijklmnopqrstuvwxyz":
            letter_path = os.path.join(self.gold_dir, f"{instance_id}_{ch}.csv")
            if os.path.exists(letter_path):
                try:
                    gold_dfs.append(pd.read_csv(letter_path))
                except Exception as e:
                    logger.warning(f"Could not read gold CSV {letter_path}: {e}")

        return gold_dfs

    async def extract_taxonomy(self, failures: list[FailureRecord]) -> list[LearningEntry]:
        """
        LLM-driven error taxonomy extraction from batch failures.

        Args:
            failures: List of FailureRecord objects from evaluation.

        Returns:
            List of LearningEntry objects for appending to learnings.md.
        """
        if not failures:
            return []

        # Format failures for the LLM
        failure_texts = []
        for f in failures[:20]:  # Limit to 20 failures to stay within token budget
            failure_texts.append(
                f"Instance: {f.instance_id}\n"
                f"Question: {f.nlq}\n"
                f"Error Type: {f.error_type}\n"
                f"SQL:\n{f.sql}\n"
                f"Error/Details: {f.error_message or f.details}"
            )

        failures_str = "\n---\n".join(failure_texts)

        try:
            response = await llm_call(
                prompt=TAXONOMY_PROMPT.format(failures=failures_str),
                system=TAXONOMY_SYSTEM,
                response_format="json",
            )

            learnings_raw = json.loads(response)
            # Guard against double-encoded JSON (LLM wraps array in quotes)
            if isinstance(learnings_raw, str):
                learnings_raw = json.loads(learnings_raw)
            entries = []

            for item in learnings_raw:
                entries.append(LearningEntry(
                    error_type=item.get("error_type", "other"),
                    pattern=item.get("pattern", "Unknown pattern"),
                    fix=item.get("fix", "Review and adjust"),
                    example_sql=item.get("example", ""),
                ))

            logger.info(f"Extracted {len(entries)} learnings from {len(failures)} failures")
            return entries

        except Exception as e:
            logger.error(f"Taxonomy extraction failed: {e}")
            return []

    def print_report(self, report: EvalReport):
        """Print a formatted evaluation report."""
        print(f"\n{'=' * 70}")
        print(f"  EVALUATION REPORT")
        print(f"{'=' * 70}")
        print(f"  Total instances:     {report.total}")
        print(f"  Correct:             {report.correct}")
        print(f"  Wrong result:        {report.wrong_result}")
        print(f"  Execution errors:    {report.execution_error}")
        print(f"  Missing:             {report.missing}")
        print(f"  Accuracy:            {report.accuracy:.2%}")
        print(f"{'=' * 70}")

        print("\nPer-instance breakdown:")
        for iid, status in sorted(report.per_instance.items()):
            emoji = {"correct": "✅", "wrong_result": "❌", "execution_error": "⚠️", "missing": "⬜"}.get(status, "?")
            print(f"  {emoji} {iid}: {status}")
        print()


# ============================================================================
# Comparison functions (from evaluate_utils.py)
# ============================================================================

def compare_pandas_table(pred, gold, condition_cols=[], ignore_order=False):
    """Compare two pandas dataframes for equality."""
    tolerance = 1e-2

    def vectors_match(v1, v2, tol=tolerance, ignore_order_=False):
        if ignore_order_:
            v1, v2 = (
                sorted(v1, key=lambda x: (x is None, str(x), isinstance(x, (int, float)))),
                sorted(v2, key=lambda x: (x is None, str(x), isinstance(x, (int, float)))),
            )
        if len(v1) != len(v2):
            return False
        for a, b in zip(v1, v2):
            if pd.isna(a) and pd.isna(b):
                continue
            elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if not math.isclose(float(a), float(b), abs_tol=tol):
                    return False
            elif a != b:
                return False
        return True

    if condition_cols:
        # Ensure condition_cols is a list so iloc returns a DataFrame, not a Series
        if isinstance(condition_cols, int):
            condition_cols = [condition_cols]
        gold_cols = gold.iloc[:, condition_cols]
    else:
        gold_cols = gold
    pred_cols = pred

    t_gold_list = gold_cols.transpose().values.tolist()
    t_pred_list = pred_cols.transpose().values.tolist()

    score = 1
    for _, gold_vec in enumerate(t_gold_list):
        if not any(vectors_match(gold_vec, pred_vec, ignore_order_=ignore_order) for pred_vec in t_pred_list):
            score = 0
    return score


def compare_multi_pandas_table(pred, multi_gold, multi_condition_cols=[], multi_ignore_order=False):
    """Compare predicted result with multiple gold standards."""
    if not multi_condition_cols or multi_condition_cols == [[]] or multi_condition_cols == [None]:
        multi_condition_cols = [[] for _ in range(len(multi_gold))]
    elif len(multi_gold) > 1 and not all(isinstance(sublist, list) for sublist in multi_condition_cols):
        multi_condition_cols = [multi_condition_cols for _ in range(len(multi_gold))]

    multi_ignore_order_list = [multi_ignore_order for _ in range(len(multi_gold))]

    for i, gold in enumerate(multi_gold):
        if compare_pandas_table(pred, gold, multi_condition_cols[i], multi_ignore_order_list[i]):
            return 1
    return 0
