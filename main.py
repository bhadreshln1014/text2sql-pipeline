"""
Text-to-SQL Pipeline — Main Orchestrator

Entry point for the pipeline. Runs decompose → generate → verify → execute
with retry loops and persistent memory.

Usage:
    python main.py --limit 30
    python main.py --instance sf_bq011
    python main.py --model ollama/qwen2.5:32b --limit 5
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml
from dotenv import load_dotenv

# Add text2sql to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.llm import init_llm, get_token_usage
from utils.context_loader import ContextLoader
from utils.logger import QuestionLogger, setup_logging
from pipeline.decomposer import decompose, format_subtask_tree
from pipeline.generator import generate
from pipeline.requirements import check_requirements
from pipeline.executor import Executor
from pipeline.explorer import Explorer
from pipeline.error_checker import check_error, ErrorCheckResult
from memory.learnings import read_learnings, append_learning, error_to_learning
from eval.evaluator import Evaluator

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    """Load pipeline configuration from YAML."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_dataset(path: str) -> dict:
    """Load Spider2-Snow dataset as {instance_id: metadata}."""
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line.strip())
            data[item["instance_id"]] = item
    return data


def log_hard_failure(
    failure_type: str, instance_id: str, details: dict, config: dict
):
    """Log a hard failure (question that exhausted all retries)."""
    failures_dir = config.get("hard_failures_path", "data/hard_failures")
    os.makedirs(failures_dir, exist_ok=True)

    failure = {
        "instance_id": instance_id,
        "failure_type": failure_type,
        "timestamp": datetime.now().isoformat(),
        "details": _serialize(details),
    }

    path = os.path.join(failures_dir, f"{instance_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(failure, f, indent=2, default=str)

    logger.warning(f"Hard failure [{failure_type}] for {instance_id}")


def _serialize(obj) -> dict:
    """Convert dataclass or object to serializable dict."""
    if hasattr(obj, "__dict__"):
        return {k: str(v)[:500] for k, v in obj.__dict__.items()}
    return {"value": str(obj)[:500]}


async def run_pipeline(instance_ids: list[str], config: dict, dataset: dict):
    """
    Run the full pipeline for a list of instances.

    Flow per question:
    1. Load context (DDL + docs)
    2. Decompose NLQ into subtasks
    3. Requirements loop: generate → verify → retry
    4. Execution loop: execute → classify error → retry
    5. Store results (SQL + CSV)

    Post-run:
    6. Offline evaluation
    7. Taxonomy extraction → append learnings
    """
    # Initialize components
    context_loader = ContextLoader(config)
    executor = Executor(config)
    explorer = Explorer(config, executor)
    evaluator = Evaluator(config)

    learnings_path = config.get("learnings_path", "data/learnings.md")
    max_retries_req = config.get("max_retries_requirements", 3)
    max_retries_exec = config.get("max_retries_execution", 3)
    max_learnings = config.get("max_learnings_entries", 40)

    processed = 0
    succeeded = 0
    failed_req = 0
    failed_exec = 0

    total = len(instance_ids)
    start_time = time.time()

    for i, instance_id in enumerate(instance_ids, 1):
        instance = dataset.get(instance_id)
        if instance is None:
            logger.error(f"Instance {instance_id} not found in dataset")
            continue

        nlq = instance.get("instruction", instance.get("question", ""))
        db_id = instance.get("db_id", "")
        external_knowledge = instance.get("external_knowledge", "")

        qlog = QuestionLogger(instance_id, config.get("outputs_path", "data/outputs"))

        print(f"\n{'=' * 70}")
        print(f"[{i}/{total}] {instance_id} | db={db_id}")
        print(f"Q: {nlq[:100]}{'...' if len(nlq) > 100 else ''}")
        print(f"{'=' * 70}")

        try:
            # ----------------------------------------------------------
            # Step 1: Load context
            # ----------------------------------------------------------
            ctx = context_loader.load_context(db_id, external_knowledge or None)
            qlog.log_step("context_loaded", {
                "db_id": db_id,
                "ddl_chars": len(ctx["ddl"]),
                "docs_chars": len(ctx["docs"]),
            })

            # ----------------------------------------------------------
            # Step 2: Decompose (NLQ only — no DDL, semantic-first)
            # ----------------------------------------------------------
            subtask_tree = await decompose(nlq)
            qlog.log_step("decomposed", {
                "subtask_count": len(subtask_tree),
                "subtasks": [{"id": s.id, "desc": s.description} for s in subtask_tree],
            })
            print(f"📋 Decomposed into {len(subtask_tree)} subtasks")

            # ----------------------------------------------------------
            # Step 2.5: Explore Database
            # ----------------------------------------------------------
            print(f"🔍 Exploring database schema dynamically...")
            exploration_transcript, exploration_errors, column_roster = await explorer.explore(nlq, db_id, ctx, [{"id": s.id, "desc": s.description} for s in subtask_tree])
            qlog.log_step("explored", {
                "transcript_length": len(exploration_transcript),
                "errors_caught": len(exploration_errors),
            })
            # Debug: save transcript to disk
            transcript_path = os.path.join(config.get("outputs_path", "data/outputs"), f"{instance_id}_transcript.md")
            with open(transcript_path, "w", encoding="utf-8") as tf:
                tf.write(exploration_transcript)
            
            # Fix 4: Process Explorer Failures into Learnings
            for exp_err in exploration_errors:
                # Mock ErrorCheckResult for exploration
                err_result = ErrorCheckResult(
                    has_error=True,
                    error_type="exploration_syntax",
                    error_message=exp_err["error"],
                    error_query=exp_err["sql"]
                )
                
                learning = await error_to_learning(err_result, exp_err["sql"], column_roster)
                learning.error_type = f"EXPLORER_{learning.error_type}"
                appended = append_learning(learning, learnings_path)
                if appended:
                    print(f"📝 Appended [EXPLORER] learning: {learning.pattern[:50]}...")

            # ----------------------------------------------------------
            # Step 3: Requirements loop
            # ----------------------------------------------------------
            # Re-read each instance so learnings from prior instances are included
            learnings = read_learnings(learnings_path, max_entries=max_learnings)
            prev_feedback = None
            requirements_passed = False
            sql = ""

            for attempt in range(max_retries_req):
                # Generate SQL
                sql = await generate(
                    nlq=nlq,
                    ddl=ctx["ddl"],
                    docs=ctx["docs"],
                    learnings=learnings,
                    subtask_tree=subtask_tree,
                    exploration_transcript=exploration_transcript,
                    prev_feedback=prev_feedback,
                )
                qlog.log_step("sql_generated", {
                    "attempt": attempt + 1,
                    "loop": "requirements",
                    "sql": sql,
                })

                # Check requirements
                result = await check_requirements(sql, subtask_tree)
                qlog.log_step("requirements_checked", {
                    "attempt": attempt + 1,
                    "score": result.score,
                    "passed": result.passed,
                    "failed_count": len(result.failed_subtasks),
                })

                if result.passed:
                    requirements_passed = True
                    print(f"✅ Requirements passed ({result.score}) on attempt {attempt + 1}")
                    break

                print(
                    f"⚠️  Requirements failed: {result.score} "
                    f"({len(result.failed_subtasks)} subtasks failed, "
                    f"attempt {attempt + 1}/{max_retries_req})"
                )

                prev_feedback = {
                    "failed_subtasks": result.failed_subtasks,
                    "previous_sql": sql,
                    "score": result.score,
                    "attempt": attempt + 1,
                }

            if not requirements_passed:
                print(f"❌ Requirements exhausted after {max_retries_req} attempts")
                log_hard_failure("requirements", instance_id, result, config)
                qlog.log_step("hard_failure", {"type": "requirements"})
                qlog.save()
                failed_req += 1
                processed += 1
                continue

            # ----------------------------------------------------------
            # Step 4: Execution loop
            # ----------------------------------------------------------
            execution_passed = False

            for attempt in range(max_retries_exec):
                print(f"⚙️  Executing SQL on Snowflake (attempt {attempt + 1})...")
                exec_result = executor.execute(sql, db_id)
                qlog.log_step("executed", {
                    "attempt": attempt + 1,
                    "success": exec_result.success,
                    "time_ms": exec_result.execution_time_ms,
                    "error": exec_result.error_message,
                })

                error = check_error(exec_result)

                if not error.has_error:
                    execution_passed = True
                    print(
                        f"✅ Execution succeeded in "
                        f"{exec_result.execution_time_ms}ms"
                    )
                    break

                print(
                    f"⚠️  Execution error [{error.error_type}]: "
                    f"{error.error_message[:100]}... "
                    f"(attempt {attempt + 1}/{max_retries_exec})"
                )

                # On the final attempt there is no next iteration to use a new SQL
                if attempt == max_retries_exec - 1:
                    break

                # Generalize the error into a learning
                learning = await error_to_learning(error, sql, column_roster)
                append_learning(learning, learnings_path)
                qlog.log_step("learning_appended", {
                    "pattern": learning.pattern,
                    "fix": learning.fix,
                })

                # Re-read learnings (now includes the new one)
                learnings = read_learnings(learnings_path, max_entries=max_learnings)

                # Regenerate SQL with error feedback
                sql = await generate(
                    nlq=nlq,
                    ddl=ctx["ddl"],
                    docs=ctx["docs"],
                    learnings=learnings,
                    subtask_tree=subtask_tree,
                    exploration_transcript=exploration_transcript,
                    prev_feedback={
                        "error": error,
                        "previous_sql": sql,
                        "attempt": attempt + 1,
                    },
                )
                qlog.log_step("sql_regenerated", {
                    "attempt": attempt + 1,
                    "loop": "execution",
                    "sql": sql,
                })

            if not execution_passed:
                print(f"❌ Execution exhausted after {max_retries_exec} attempts")
                log_hard_failure("execution", instance_id, error, config)
                qlog.log_step("hard_failure", {"type": "execution"})
                qlog.save()
                failed_exec += 1
                processed += 1
                continue

            # ----------------------------------------------------------
            # Step 5: Store results
            # ----------------------------------------------------------
            executor.store_results(instance_id, sql, exec_result.data)
            qlog.log_step("results_stored", {
                "rows": len(exec_result.data) if exec_result.data is not None else 0,
            })
            qlog.save()

            succeeded += 1
            processed += 1

        except Exception as e:
            logger.error(f"Unexpected error for {instance_id}: {e}", exc_info=True)
            qlog.log_step("unexpected_error", {"error": str(e)})
            qlog.save()
            processed += 1

    # ----------------------------------------------------------
    # Post-run summary
    # ----------------------------------------------------------
    elapsed = time.time() - start_time
    token_usage = get_token_usage()

    print(f"\n{'=' * 70}")
    print(f"  PIPELINE SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Processed:           {processed}/{total}")
    print(f"  Succeeded:           {succeeded}")
    print(f"  Failed (req):        {failed_req}")
    print(f"  Failed (exec):       {failed_exec}")
    print(f"  Elapsed:             {elapsed:.1f}s")
    print(f"  Input tokens:        {token_usage['total_input_tokens']:,}")
    print(f"  Output tokens:       {token_usage['total_output_tokens']:,}")
    print(f"{'=' * 70}\n")

    # ----------------------------------------------------------
    # Step 6: Offline evaluation
    # ----------------------------------------------------------
    print("📊 Running offline evaluation...")
    eval_report = evaluator.run_offline_eval(dataset)
    evaluator.print_report(eval_report)

    # ----------------------------------------------------------
    # Step 7: Taxonomy extraction
    # ----------------------------------------------------------
    if eval_report.failures:
        print("🔬 Extracting error taxonomy...")
        new_learnings = await evaluator.extract_taxonomy(eval_report.failures)
        for entry in new_learnings:
            append_learning(entry, learnings_path)
        print(f"📝 Appended {len(new_learnings)} new learnings to {learnings_path}")

    return eval_report


async def main(args):
    """Entry point."""
    # Load env vars
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        # Try parent bhadresh .env
        alt_env = os.path.join(os.path.dirname(__file__), "..", "bhadresh", ".env")
        if os.path.exists(alt_env):
            load_dotenv(alt_env)

    # Load config
    config = load_config(args.config)

    # CLI model override (keep original fallback_model unless explicitly same)
    if args.model:
        config["model"] = args.model
        print(f"Model override: {args.model}")

    # Initialize LLM
    init_llm(config)

    # Setup logging
    setup_logging(verbose=args.verbose)

    # Load dataset
    dataset = load_dataset(config["spider_data_path"])
    print(f"Loaded {len(dataset)} instances from dataset")

    # Determine which instances to run
    if args.instance:
        instance_ids = [args.instance]
    else:
        instance_ids = list(dataset.keys())
        if args.limit:
            instance_ids = instance_ids[: args.limit]

    print(f"Running pipeline on {len(instance_ids)} instances")
    print(f"Model: {config['model']}")
    print(f"Max retries: requirements={config['max_retries_requirements']}, "
          f"execution={config['max_retries_execution']}")

    # Run
    report = await run_pipeline(instance_ids, config, dataset)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Text-to-SQL Pipeline")
    parser.add_argument("--limit", type=int, default=30, help="Max questions to run")
    parser.add_argument("--model", type=str, default=None, help="Override config model")
    parser.add_argument("--instance", type=str, default=None, help="Run single instance")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config file path")
    parser.add_argument("--verbose", action="store_true", default=False, help="Verbose logging")
    args = parser.parse_args()

    asyncio.run(main(args))
