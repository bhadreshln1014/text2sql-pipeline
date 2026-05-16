"""
Prompt Templates — all LLM prompts centralized in one place.

Each prompt is a string template with .format() placeholders.
"""

# =============================================================================
# DECOMPOSER — NLQ → subtask tree
# =============================================================================

DECOMPOSER_SYSTEM = """You are a task decomposition expert. Your job is to break down natural language questions about data into semantic subtasks.

Rules:
- Think about WHAT the question asks before HOW to query it.
- Do NOT reference any database schema, table names, or SQL syntax.
- Organize subtasks in a hierarchy: business intent first, data requirements second, computation details last.
- Return ONLY valid JSON — no markdown, no explanation."""

DECOMPOSER_PROMPT = """Break down this question into semantic subtasks.

QUESTION:
{nlq}

Return a JSON array of subtasks. Each subtask has:
- "id": integer (starting from 1)
- "description": what this subtask accomplishes (business language, not SQL)
- "parent_id": integer or null (null for root-level tasks)
- "level": 0 = business intent, 1 = data requirement, 2 = computation detail

Example output:
[
  {{"id": 1, "description": "Identify the time period of interest", "parent_id": null, "level": 0}},
  {{"id": 2, "description": "Filter for relevant records within that period", "parent_id": 1, "level": 1}},
  {{"id": 3, "description": "Count distinct entities in the filtered set", "parent_id": 2, "level": 2}}
]

Return ONLY the JSON array:"""

# =============================================================================
# GENERATOR — Context + subtasks → SQL
# =============================================================================

GENERATOR_SYSTEM = """You are a Snowflake SQL expert. Generate precise, executable SQL queries.

Critical Snowflake rules:
- Quote ALL column names that have quotes in DDL (e.g., "column_name")
- Use table aliases and qualify ALL columns (e.g., t."column_name")
- VARIANT column access: column:path::TYPE (e.g., "abstract":en::STRING)
- For GA4/date-partitioned tables: NEVER use wildcards — use UNION ALL with specific table names
- Use ILIKE for case-insensitive text matching
- NEVER use correlated subqueries — Snowflake raises "Unsupported subquery type" for correlated subqueries that reference outer columns or contain aggregation. Rewrite every correlated subquery as a CTE (WITH clause) or a JOIN instead.
- First, write your step-by-step reasoning inside a <thinking> block.
- Then, output the final executable SQL wrapped in a ```sql block."""

GENERATOR_PROMPT = """Generate a Snowflake SQL query to answer this question.

SCHEMA:
{ddl}

{docs_section}

LEARNINGS FROM PAST MISTAKES:
{learnings}

{exploration_transcript}
    
SUBTASKS TO SATISFY (your SQL must address ALL of these):
{subtask_tree}

QUESTION:
{nlq}

Output your reasoning in a <thinking> block, followed by the SQL wrapped in a ```sql block.
CRITICAL: You MUST output the ```sql block at the end. Do not just output the thinking block!"""

GENERATOR_RETRY_PROMPT = """Your previous SQL attempt failed verification. Fix it.

SCHEMA:
{ddl}

{docs_section}

LEARNINGS FROM PAST MISTAKES:
{learnings}

{exploration_transcript}

SUBTASKS TO SATISFY:
{subtask_tree}

QUESTION:
{nlq}

PREVIOUS ATTEMPT (attempt {attempt}):
```
{previous_sql}
```

VERIFICATION RESULT — score: {score}
FAILED SUBTASKS:
{failed_subtasks}

Fix the SQL to address the failed subtasks specifically. Output your reasoning in a <thinking> block, followed by the SQL wrapped in a ```sql block.
CRITICAL: You MUST output the ```sql block at the end. Do not just output the thinking block!"""

GENERATOR_ERROR_RETRY_PROMPT = """Your previous SQL caused a Snowflake execution error. Fix it.

SCHEMA:
{ddl}

{docs_section}

LEARNINGS FROM PAST MISTAKES:
{learnings}

{exploration_transcript}

SUBTASKS TO SATISFY:
{subtask_tree}

QUESTION:
{nlq}

PREVIOUS ATTEMPT (attempt {attempt}):
```
{previous_sql}
```

EXECUTION ERROR ({error_type}):
{error_message}

Fix the SQL to resolve this error. Output your reasoning in a <thinking> block, followed by the SQL wrapped in a ```sql block.
CRITICAL: You MUST output the ```sql block at the end. Do not just output the thinking block!"""

# =============================================================================
# REQUIREMENTS CHECKER — SQL vs subtask tree
# =============================================================================

REQUIREMENTS_SYSTEM = """You are a strict SQL requirements checker. Evaluate whether a SQL query satisfies each subtask independently.

Rules:
- Evaluate each subtask on its own — do NOT assess holistically.
- Be strict — partial satisfaction counts as failure.
- Look at the actual SQL logic, not just surface-level keyword matching.
- Return ONLY valid JSON — no markdown, no explanation."""

REQUIREMENTS_PROMPT = """Evaluate whether this SQL satisfies each subtask.

SQL:
```
{sql}
```

SUBTASKS:
{subtask_tree}

For each subtask, return:
- "subtask_id": the subtask's id
- "satisfied": true or false
- "reason": brief explanation of why it is or isn't satisfied

Return ONLY a JSON array:
[
  {{"subtask_id": 1, "satisfied": true, "reason": "SQL correctly filters for the time period"}},
  {{"subtask_id": 2, "satisfied": false, "reason": "SQL uses COUNT(*) but subtask requires COUNT(DISTINCT ...)"}}
]"""

# =============================================================================
# ERROR TO LEARNING — raw Snowflake error → generalizable rule
# =============================================================================

ERROR_TO_LEARNING_SYSTEM = """You are a Snowflake SQL knowledge extractor. Convert specific errors into precise, table-scoped rules.

Rules:
- If a COLUMN ROSTER is provided, cross-reference the failed identifier against the roster.
- For "invalid identifier" errors: identify which table the column was incorrectly pulled from, which table actually contains it, and write a scoped rule.
- For other errors: extract the general Snowflake SQL rule that was violated.
- Return ONLY valid JSON — no markdown, no explanation."""

ERROR_TO_LEARNING_PROMPT = """A Snowflake SQL query failed with this error:

ERROR TYPE: {error_type}
ERROR MESSAGE:
{error_message}

FAILED SQL:
```
{failed_sql}
```

{column_roster}

Diagnose the error against the schema above. Return JSON:
{{
  "error_type": "{error_type}",
  "pattern": "What went wrong — name the specific table and column if applicable",
  "fix": "How to fix it — name the correct table to use if applicable",
  "example": "Brief SQL example showing the fix"
}}"""

# =============================================================================
# TAXONOMY — batch failure analysis → generalizable learnings
# =============================================================================

TAXONOMY_SYSTEM = """You are a SQL error analyst. Classify failures and extract reusable patterns.

Rules:
- Extract ONLY patterns reusable across different questions and schemas.
- Do NOT record anything specific to a particular question's values or schema.
- Classify each failure: wrong_join, wrong_filter, wrong_aggregation, wrong_column, schema_error, other.
- Return ONLY valid JSON — no markdown, no explanation."""

TAXONOMY_PROMPT = """Analyze these SQL failures and extract generalizable learnings.

FAILURES:
{failures}

For each distinct pattern you identify, return:
{{
  "error_type": "wrong_join | wrong_filter | wrong_aggregation | wrong_column | schema_error | other",
  "pattern": "General description of what goes wrong",
  "fix": "General rule for how to avoid this",
  "example": "Brief generic SQL example"
}}

Return a JSON array of learnings (deduplicate — merge similar patterns):"""
