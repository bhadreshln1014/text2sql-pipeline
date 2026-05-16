"""
Context Loader — loads DDL schemas and external documentation for a given database.

Handles date-partitioned tables (GA4 pattern) specially.
Applies token budgets to keep context within LLM limits.
"""

import os
import re
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class ContextLoader:
    """Loads DDL and external docs for a given Spider2-Snow database."""

    def __init__(self, config: dict):
        self.database_path = config.get("database_path", "../spider2-snow/resource/databases")
        self.documents_path = config.get("documents_path", "../spider2-snow/resource/documents")
        self.ddl_budget = config.get("ddl_budget", 4000)
        self.docs_budget = config.get("docs_budget", 3000)

    def load_context(self, db_id: str, external_knowledge: Optional[str] = None) -> dict:
        """
        Load DDL schemas and external documentation for a database.

        Returns:
            {
                "ddl": str,          # DDL text within budget
                "docs": str,         # External knowledge markdown within budget
            }
        """
        ddl = self._load_ddl(db_id)
        docs = self._load_docs(external_knowledge)

        return {
            "ddl": ddl,
            "docs": docs,
        }

    def _load_ddl(self, db_id: str) -> str:
        """Load DDL for ALL schemas under the database directory."""
        db_path = os.path.join(self.database_path, db_id)

        if not os.path.exists(db_path):
            logger.warning(f"Database path not found: {db_path}")
            return ""

        schema_blocks = []

        # A Snowflake database can have many schemas — collect them all
        for root, dirs, files in os.walk(db_path):
            if "DDL.csv" not in files:
                continue

            ddl_file = os.path.join(root, "DDL.csv")
            schema_name = os.path.basename(root)

            try:
                df = pd.read_csv(ddl_file)
            except Exception as e:
                logger.warning(f"Could not read DDL file {ddl_file}: {e}")
                continue

            table_names = df["table_name"].tolist()

            block = f"DATABASE: {db_id} | SCHEMA: {schema_name}\n"
            block += f"Full path format: {db_id}.{schema_name}.TABLE_NAME\n"
            block += "IMPORTANT: Quote column names exactly as shown in DDL.\n\n"

            # Detect date-partitioned tables (GA4 pattern: EVENTS_YYYYMMDD)
            events_tables = [t for t in table_names if re.match(r"^EVENTS_\d{8}$", t)]

            if events_tables:
                block += self._format_partitioned_tables(
                    df, db_id, schema_name, events_tables, table_names
                )
            else:
                block += self._format_regular_tables(df, db_id, schema_name, table_names)

            schema_blocks.append(block)

        if not schema_blocks:
            return ""

        logger.info(f"Loaded {len(schema_blocks)} schema(s) for {db_id}")

        ddl_text = "\n".join(schema_blocks)

        # Enforce budget across all schemas combined — cut at a table boundary
        # so the LLM never receives a half-written CREATE TABLE statement
        if len(ddl_text) > self.ddl_budget:
            cut = ddl_text.rfind("\n\n--", 0, self.ddl_budget)
            if cut == -1:
                cut = self.ddl_budget
            ddl_text = ddl_text[:cut] + "\n... (truncated)\n"
            logger.info(f"DDL truncated to {self.ddl_budget} chars for {db_id}")

        return ddl_text

    def _format_partitioned_tables(
        self,
        df: pd.DataFrame,
        db_id: str,
        schema_name: str,
        events_tables: list,
        all_tables: list,
    ) -> str:
        """Format date-partitioned tables concisely."""
        sorted_events = sorted(events_tables)
        first_date = sorted_events[0].replace("EVENTS_", "")
        last_date = sorted_events[-1].replace("EVENTS_", "")

        text = f"DATE-PARTITIONED TABLES ({len(events_tables)} total):\n"
        text += f"- Pattern: EVENTS_YYYYMMDD\n"
        text += f"- Date range: {first_date} to {last_date}\n"
        text += f"- Example tables: EVENTS_{first_date}, EVENTS_{last_date}\n"
        text += f"- MUST use UNION ALL for multiple dates (no wildcards!)\n\n"

        # Show 1 sample table DDL
        sample_row = df[df["table_name"] == sorted_events[0]].iloc[0]
        text += f"SAMPLE TABLE STRUCTURE (all date tables identical):\n"
        text += f"Table: {db_id}.{schema_name}.EVENTS_YYYYMMDD\n"
        text += f"{sample_row['DDL']}\n\n"

        # List non-event tables if any
        other_tables = [t for t in all_tables if t not in events_tables]
        if other_tables:
            text += f"OTHER TABLES: {', '.join(other_tables)}\n\n"
            for _, row in df[df["table_name"].isin(other_tables)].iterrows():
                text += f"-- {db_id}.{schema_name}.{row['table_name']}\n"
                text += f"{row['DDL']}\n\n"

        return text

    def _format_regular_tables(
        self, df: pd.DataFrame, db_id: str, schema_name: str, table_names: list
    ) -> str:
        """Format regular (non-partitioned) tables."""
        if len(table_names) > 15:
            text = (
                f"TABLES ({len(table_names)} total): "
                f"{', '.join(table_names[:15])}... (and {len(table_names) - 15} more)\n\n"
            )
        else:
            text = f"TABLES: {', '.join(table_names)}\n\n"

        text += "TABLE STRUCTURES:\n\n"
        for _, row in df.iterrows():
            table_name = row["table_name"]
            ddl = row["DDL"]
            text += f"-- {db_id}.{schema_name}.{table_name}\n"
            text += f"{ddl}\n\n"

        return text

    def _load_docs(self, external_knowledge: Optional[str]) -> str:
        """Load external knowledge markdown document."""
        if not external_knowledge:
            return ""

        doc_path = os.path.join(self.documents_path, external_knowledge)

        if not os.path.exists(doc_path):
            logger.warning(f"External knowledge file not found: {doc_path}")
            return ""

        try:
            with open(doc_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Fix 0: Extract Table of Contents
            toc = []
            for line in content.splitlines():
                if line.startswith("#"):
                    toc.append(line.strip())
            
            if toc:
                toc_str = "## DOCUMENTATION TABLE OF CONTENTS\n" + "\n".join(toc) + "\n\n"
                content = toc_str + content

            if len(content) > self.docs_budget:
                content = content[: self.docs_budget] + "\n... (truncated)\n"
                logger.info(f"Docs truncated to {self.docs_budget} chars")

            return content
        except Exception as e:
            logger.warning(f"Could not read docs file {doc_path}: {e}")
            return ""
