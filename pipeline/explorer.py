import logging
import json
import re
from typing import List, Tuple
from utils.llm import llm_call
from pipeline.executor import Executor

logger = logging.getLogger(__name__)

_ALLOWED_RECON_PREFIXES = ("select", "show", "describe", "desc")


def _is_safe_recon_sql(sql: str) -> bool:
    """Allow only read-only reconnaissance statements."""
    first_word = sql.strip().split()[0].lower() if sql.strip() else ""
    return first_word in _ALLOWED_RECON_PREFIXES


class Explorer:
    """
    Agentic Database Explorer.
    Allows the LLM to run reconnaissance SQL queries (e.g. SHOW TABLES, SELECT * LIMIT 3)
    to understand complex JSON schemas before writing the final SQL.
    """

    def __init__(self, config: dict, executor: Executor):
        self.config = config
        self.executor = executor
        self.max_steps = config.get("max_exploration_steps", 3)
        self.model = config.get("model", "llama-3.3-70b-versatile")
        self.temperature = config.get("temperature", 0.0)

    async def explore(self, instruction: str, db_id: str, context: dict, subtasks: List[dict]) -> Tuple[str, List[dict]]:
        """
        Runs the dynamic database exploration loop.

        Args:
            instruction: The original user query.
            db_id: Database ID.
            context: The static context (table names).
            subtasks: The semantic subtasks.

        Returns:
            Tuple containing:
            - A markdown-formatted transcript of the exploration.
            - A list of exploration errors (dicts with 'sql' and 'error').
        """
        logger.info(f"Starting Database Exploration (max {self.max_steps} steps)")

        system_prompt = (
            "You are an AI Data Engineer building a SQL query for Snowflake.\n"
            "You do not have the exact JSON schema of the tables. You must explore the database to find it.\n"
            "You can execute reconnaissance queries to explore the schema.\n"
            "If you want to execute a query, write ONLY the SQL query wrapped in ```sql ... ``` block and NOTHING ELSE.\n"
            "DO NOT write the final query here. Write simple queries like:\n"
            "- SHOW TABLES IN SCHEMA IDC.IDC_V17;\n"
            "- SELECT * FROM IDC.IDC_V17.TABLE_NAME LIMIT 1;\n"
            "We will execute your query and return the results to you.\n"
            "Once you perfectly understand the schema (especially nested JSON keys) needed to answer the user's question, "
            "output the exact word 'READY' (without quotes, no SQL block)."
        )

        subtask_list = "\n".join([f"- {s['desc']}" for s in subtasks])

        # Fix 1: Schema Grounding Step
        table_names = set()
        for match in re.finditer(r"(?:--|Table:)\s+[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.([A-Za-z0-9_]+)", context.get('ddl', '')):
            table_names.add(match.group(1))
        
        grounding_block = ""
        if table_names:
            tables_csv = ", ".join(f"'{t}'" for t in table_names)
            grounding_sql = f"""
                SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM {db_id}.INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME IN ({tables_csv})
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """
            try:
                res = self.executor.execute(grounding_sql, db_id, timeout=30)
                if res.success and not res.data.empty:
                    grounding_block = "=== VERIFIED COLUMN ROSTER (SOURCE OF TRUTH) ===\n"
                    current_table = None
                    for _, row in res.data.iterrows():
                        tbl = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
                        if tbl != current_table:
                            if current_table is not None:
                                grounding_block += "\n"
                            current_table = tbl
                            grounding_block += f"{tbl}: "
                            grounding_block += f"{row['COLUMN_NAME']} ({row['DATA_TYPE']})"
                        else:
                            grounding_block += f", {row['COLUMN_NAME']} ({row['DATA_TYPE']})"
                    grounding_block += "\n=== END ROSTER — DO NOT USE COLUMNS NOT LISTED ABOVE ===\n\n"
            except Exception as e:
                logger.warning(f"Schema grounding query failed: {e}")

        transcript = "### Database Exploration Transcript\n\n"
        # Prepend COLUMN ROSTER to transcript so the Generator sees it
        if grounding_block:
            transcript += grounding_block
        history = ""
        reached_ready = False
        exploration_errors = []

        for step in range(self.max_steps):
            logger.info(f"Exploration Step {step + 1}/{self.max_steps}")

            prompt = (
                f"Question: {instruction}\n\n"
                f"Database: {db_id}\n\n"
                f"Subtasks:\n{subtask_list}\n\n"
                f"Initial Table Context:\n{context['ddl']}\n\n"
                f"{grounding_block}"
                f"History of your Exploration:\n{history}\n"
                "What is your exploratory SQL query? (Or output READY if you already know the exact schema)."
            )

            response = await llm_call(
                prompt=prompt,
                system=system_prompt,
                model=self.model,
                temperature=self.temperature
            )

            response_clean = response.strip()

            if response_clean.upper() == "READY":
                logger.info("Explorer Agent reported READY.")
                transcript += "**Agent:** READY (Exploration Complete)\n"
                reached_ready = True
                break

            # Extract SQL from markdown block
            sql_match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?\s*```", response_clean, re.DOTALL)
            if sql_match:
                sql_to_run = sql_match.group(1).strip()
            else:
                # LLM returned neither READY nor a SQL block — log and skip this step
                logger.warning(
                    f"Explorer step {step + 1}: LLM returned neither READY nor a SQL block. "
                    f"Response: {response_clean[:200]}"
                )
                history += f"Step {step + 1}: No valid SQL or READY signal received.\n\n"
                continue

            # Guard against DML/DDL — only allow read-only statements
            if not _is_safe_recon_sql(sql_to_run):
                first_word = sql_to_run.split()[0] if sql_to_run.split() else "?"
                logger.warning(
                    f"Explorer blocked unsafe recon statement: {first_word.upper()}. Skipping."
                )
                history += (
                    f"Step {step + 1}: Query blocked (only SELECT/SHOW/DESCRIBE allowed).\n\n"
                )
                continue

            # Fix 2: Explorer Guard Layer (auto LIMIT 5)
            if sql_to_run.lower().startswith("select") and not re.search(r"\blimit\s+\d+", sql_to_run, re.IGNORECASE):
                sql_to_run += "\nLIMIT 5"
                transcript += "**System:** Automatically appended `LIMIT 5` to prevent context blowout.\n\n"

            transcript += f"**Agent Recon Query:**\n```sql\n{sql_to_run}\n```\n\n"

            logger.info(f"Executing Recon Query: {sql_to_run[:50]}...")
            result = self.executor.execute(sql_to_run, db_id, timeout=30)

            if result.success and result.data is not None:
                if result.data.empty:
                    query_result = "Success. (0 rows returned)"
                else:
                    row_dict = result.data.head(5).to_dict(orient="records")
                    query_result = json.dumps(row_dict, default=str)
            else:
                query_result = f"Error executing query: {result.error_message}"
                exploration_errors.append({"sql": sql_to_run, "error": result.error_message})

            # Fix 3: Hard Context Budget Enforcement with Actionable Warning
            budget_per_query = 2000
            if len(query_result) > budget_per_query:
                query_result = query_result[:budget_per_query] + "\n... [SYSTEM WARNING: Result truncated to 2000 chars. Query INFORMATION_SCHEMA.COLUMNS for exact column names or rewrite with specific column names and LIMIT 5.]"

            transcript += f"**Database Result:**\n{query_result}\n\n"
            history += f"You ran:\n```sql\n{sql_to_run}\n```\nResult:\n{query_result}\n\n"

        if not reached_ready:
            logger.warning("Explorer reached max steps without outputting READY.")

        # Cap transcript size so it doesn't dominate the generator prompt
        budget = self.config.get("exploration_transcript_budget", 6000)
        if len(transcript) > budget:
            transcript = transcript[:budget] + "\n... (exploration transcript truncated)\n"
            logger.info(f"Exploration transcript truncated to {budget} chars")

        return transcript, exploration_errors, grounding_block
