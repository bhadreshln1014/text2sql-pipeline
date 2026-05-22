"""
Executor — Snowflake SQL execution wrapper.

Wraps the existing get_snowflake_sql_result() from bhadresh/evaluate_utils.py.
Adds timeout estimation, structured results, and CSV/SQL storage.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import snowflake.connector
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    data: Optional[pd.DataFrame] = None
    error_message: Optional[str] = None
    execution_time_ms: int = 0


class Executor:
    """Executes SQL on Snowflake and stores results."""

    def __init__(self, config: dict):
        self.credential_path = config.get(
            "snowflake_credential_path", "../bhadresh/snowflake_credential.json"
        )
        self.outputs_path = config.get("outputs_path", "data/outputs")
        self.timeout_base = config.get("query_timeout_base", 60)
        self.timeout_max = config.get("query_timeout_max", 300)

        # Load Snowflake credentials
        with open(self.credential_path, "r") as f:
            self.credentials = json.load(f)

        # One cached connection per db_id — avoids reconnecting on every query
        self._connections: dict = {}

        os.makedirs(self.outputs_path, exist_ok=True)

    def _get_connection(self, db_id: str):
        """Return a live Snowflake connection for db_id, creating one if needed."""
        conn = self._connections.get(db_id)
        if conn is None or conn.is_closed():
            conn = snowflake.connector.connect(database=db_id, **self.credentials)
            self._connections[db_id] = conn
            logger.info(f"Opened new Snowflake connection for db={db_id}")
        return conn

    def close(self):
        """Close all cached connections. Call when the pipeline is done."""
        for db_id, conn in list(self._connections.items()):
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    def __del__(self):
        self.close()

    def execute(self, sql: str, db_id: str, timeout: Optional[int] = None) -> ExecutionResult:
        """
        Execute SQL on Snowflake.

        Args:
            sql: SQL query string.
            db_id: Database identifier (e.g., "MY_DATABASE").
            timeout: Query timeout in seconds. Auto-estimated if None.

        Returns:
            ExecutionResult with success/data/error.
        """
        if timeout is None:
            timeout = self._estimate_timeout(sql)

        # Clean SQL (remove markdown wrappers if present)
        sql = self._clean_sql(sql)

        start = time.time()

        def _run_query():
            conn = self._get_connection(db_id)
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(results, columns=columns)
                if df.empty:
                    logger.warning("Query returned empty result set")
                return True, df
            except Exception as e:
                logger.error(f"Snowflake error: {e}")
                # If the connection was broken by this error, evict it so
                # the next call gets a fresh one.
                if conn.is_closed():
                    self._connections.pop(db_id, None)
                return False, str(e)
            finally:
                cursor.close()
                # Connection is kept alive — do NOT close it here

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_query)
                try:
                    success, result = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    elapsed_ms = int((time.time() - start) * 1000)
                    return ExecutionResult(
                        success=False,
                        error_message=f"Query execution timed out after {timeout} seconds",
                        execution_time_ms=elapsed_ms,
                    )

            elapsed_ms = int((time.time() - start) * 1000)

            if success:
                return ExecutionResult(
                    success=True, data=result, execution_time_ms=elapsed_ms
                )
            else:
                return ExecutionResult(
                    success=False, error_message=result, execution_time_ms=elapsed_ms
                )

        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            return ExecutionResult(
                success=False, error_message=str(e), execution_time_ms=elapsed_ms
            )

    def store_results(
        self, instance_id: str, sql: str, data: Optional[pd.DataFrame]
    ):
        """Save SQL and CSV result to outputs directory."""
        sql_path = os.path.join(self.outputs_path, f"{instance_id}.sql")
        with open(sql_path, "w", encoding="utf-8") as f:
            f.write(sql)

        if data is not None:
            csv_path = os.path.join(self.outputs_path, f"{instance_id}.csv")
            data.to_csv(csv_path, index=False)
            logger.info(f"Stored results: {sql_path}, {csv_path}")
        else:
            logger.info(f"Stored SQL only: {sql_path}")

    def _estimate_timeout(self, sql: str) -> int:
        """Estimate appropriate timeout based on query complexity."""
        complexity = 0
        sql_upper = sql.upper()

        if "LIKE '%" in sql or "ILIKE '%" in sql:
            complexity += 60
        if any(f in sql_upper for f in ["RANK()", "ROW_NUMBER()", "DENSE_RANK()"]):
            complexity += 30
        if sql.count("JOIN") > 2:
            complexity += 20 * (sql.count("JOIN") - 2)
        if "UNION ALL" in sql_upper:
            complexity += sql_upper.count("UNION ALL") * 15

        timeout = min(self.timeout_base + complexity, self.timeout_max)
        if timeout > self.timeout_base:
            logger.info(f"Estimated timeout: {timeout}s (complexity bonus: {complexity}s)")

        return timeout

    @staticmethod
    def _clean_sql(sql: str) -> str:
        """Remove markdown code block wrappers from SQL."""
        sql = sql.strip()
        pattern = r"```(?:sql)?\s*\n?(.*?)\n?\s*```"
        match = re.search(pattern, sql, re.DOTALL)
        if match:
            sql = match.group(1).strip()
        # Strip trailing semicolons
        sql = sql.rstrip('; \n\t')
        # If multiple statements remain, take only the first to avoid error 000008
        if ';' in sql:
            first_stmt = sql.split(';')[0].strip()
            if first_stmt:
                logger.warning("Multi-statement SQL detected; using only first statement")
                sql = first_stmt
        return sql
