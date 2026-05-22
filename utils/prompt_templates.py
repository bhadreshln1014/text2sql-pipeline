"""Prompt Templates — all LLM prompts in one place."""

# =============================================================================
# DECOMPOSER
# =============================================================================

DECOMPOSER_SYSTEM = "Break down data questions into semantic subtasks. Return ONLY valid JSON."

DECOMPOSER_PROMPT = """Break this question into subtasks.

QUESTION: {nlq}

Return a JSON array where each item has:
- "id": integer
- "description": what to accomplish (plain language, no SQL)
- "parent_id": integer or null
- "level": 0=intent, 1=data need, 2=computation

Return ONLY the JSON array:"""

# =============================================================================
# GENERATOR
# =============================================================================

GENERATOR_SYSTEM = """You are a Snowflake SQL expert. Write a single executable SQL query.

- Output reasoning in <thinking> tags, then SQL in a ```sql block.
- Qualify all columns with table aliases.
- Lowercase columns in the COLUMN ROSTER are case-sensitive — double-quote them."""

GENERATOR_PROMPT = """Write a Snowflake SQL query to answer the question.

SCHEMA:
{ddl}

{docs_section}

{exploration_transcript}

LEARNINGS:
{learnings}

SUBTASKS:
{subtask_tree}

QUESTION: {nlq}

Output <thinking> then ```sql:"""

GENERATOR_RETRY_PROMPT = """Fix your SQL — it failed requirements.

SCHEMA:
{ddl}

{docs_section}

{exploration_transcript}

LEARNINGS:
{learnings}

SUBTASKS:
{subtask_tree}

QUESTION: {nlq}

PREVIOUS SQL (attempt {attempt}):
```
{previous_sql}
```

FAILED SUBTASKS:
{failed_subtasks}

Output <thinking> then ```sql:"""

GENERATOR_ERROR_RETRY_PROMPT = """Fix your SQL — it hit a Snowflake error.

SCHEMA:
{ddl}

{docs_section}

{exploration_transcript}

LEARNINGS:
{learnings}

SUBTASKS:
{subtask_tree}

QUESTION: {nlq}

PREVIOUS SQL (attempt {attempt}):
```
{previous_sql}
```

ERROR ({error_type}): {error_message}

Output <thinking> then ```sql:"""

# =============================================================================
# REQUIREMENTS CHECKER
# =============================================================================

REQUIREMENTS_SYSTEM = "Check whether SQL satisfies each subtask. Return ONLY valid JSON."

REQUIREMENTS_PROMPT = """Does this SQL satisfy each subtask?

SQL:
```
{sql}
```

SUBTASKS:
{subtask_tree}

Return a JSON array — one entry per subtask:
[{{"subtask_id": 1, "satisfied": true, "reason": "..."}}]"""

# =============================================================================
# ERROR TO LEARNING
# =============================================================================

ERROR_TO_LEARNING_SYSTEM = "Convert a Snowflake SQL error into a generalizable rule. Return ONLY valid JSON."

ERROR_TO_LEARNING_PROMPT = """A Snowflake SQL query failed.

ERROR TYPE: {error_type}
ERROR: {error_message}

SQL:
```
{failed_sql}
```

{column_roster}

Return JSON:
{{"error_type": "...", "pattern": "what went wrong (general)", "fix": "how to avoid it (general)", "example": "brief SQL example"}}"""

# =============================================================================
# TAXONOMY
# =============================================================================

TAXONOMY_SYSTEM = "Extract reusable SQL error patterns from failures. Return ONLY valid JSON."

TAXONOMY_PROMPT = """Find generalizable patterns in these SQL failures.

FAILURES:
{failures}

Return a JSON array of distinct patterns (deduplicate):
[{{"error_type": "wrong_join|wrong_filter|wrong_aggregation|wrong_column|schema_error|other", "pattern": "...", "fix": "...", "example": "..."}}]"""
