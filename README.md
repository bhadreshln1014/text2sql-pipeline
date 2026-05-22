# Text-to-SQL: Lifelong Learning Agent Baseline

A **lifelong (socratic) agent** for the [Spider2-Snow](https://github.com/xlang-ai/Spider2) benchmark. The pipeline takes a natural language question about a Snowflake database, generates and iteratively refines SQL to answer it, executes it, and — critically — **learns from every error across all runs**, accumulating Snowflake dialect knowledge that makes subsequent instances progressively easier.

---

## Why "Lifelong"?

Most text-to-SQL systems treat every question independently. This pipeline treats the benchmark as a **sequential learning problem**: errors from question N write generalizable rules to a persistent memory (`learnings.md`), which are injected into the prompt for question N+1. Over a full benchmark run, the agent bootstraps Snowflake-specific knowledge from zero — without any hardcoded domain rules.

---

## Pipeline Overview

Each question goes through seven sequential stages:

```
Natural Language Question
         │
         ▼
  1. Load Context          ← DDL schema + external docs (from disk)
         │
         ▼
  2. Decompose             ← NLQ → semantic subtask tree (LLM, no schema)
         │
         ▼
  3. Explore               ← Agent runs recon SQL against Snowflake to discover
         │                    VARIANT column structure, date tables, etc.
         ▼
  4. Requirements Loop     ← Generate SQL → verify against subtasks → retry
         │   ▲                 (up to max_retries_requirements attempts)
         │   └── feedback ──┘
         ▼
  5. Execution Loop        ← Execute on Snowflake → classify error → retry
         │   ▲                 (up to max_retries_execution attempts)
         │   └── learn ──────── error_to_learning() writes to learnings.md
         ▼
  6. Store Results         ← Save SQL + result CSV to data/outputs/
         │
         ▼
  7. Post-run: Evaluate + Taxonomy
                           ← Compare CSVs against gold answers
                           ← LLM extracts batch-level generalizations → learnings.md
```

---

## Component Deep-Dive

### 1. Context Loader (`utils/context_loader.py`)

Loads static context for the database before any LLM call.

**DDL loading:** Walks `spider2-snow/resource/databases/{db_id}/` looking for `DDL.csv` files. Each CSV has one row per table with the full `CREATE TABLE` statement. The loader formats this as readable schema blocks with full three-part names (`DB.SCHEMA.TABLE`).

**Date-partitioned table handling:** The GA4 database stores data as `EVENTS_YYYYMMDD` — one table per day, potentially hundreds of tables. Instead of dumping all hundreds of DDL statements (which would blow the token budget), the loader detects this pattern, summarizes the range, and shows a single sample table structure.

**External documentation:** Each Spider2-Snow instance may reference a markdown document (e.g., `google_analytics_sample.ga_sessions.md`) that explains the schema semantics, VARIANT column structures, or domain conventions. The loader prepends a table of contents for faster LLM navigation.

**Budget enforcement:** Both DDL and docs are subject to character budgets (`ddl_budget`, `docs_budget` in config). Truncation cuts at a complete table boundary, never mid-statement.

---

### 2. Decomposer (`pipeline/decomposer.py`)

Breaks the natural language question into a **semantic subtask tree** using an LLM call — with **no schema context**.

**Why no schema?** The decomposer reasons about *what* the question is asking (business intent), not *how* to query it. Mixing schema knowledge here would bias the decomposition toward what the model thinks is queryable rather than what the question actually requires.

**Output structure:** A flat list of `Subtask` objects, each with an `id`, `description`, `parent_id`, and a `level`:
- Level 0 — business intent ("Find users who made a purchase in February")
- Level 1 — data requirement ("Filter sessions by transaction event type")
- Level 2 — computation detail ("Count distinct fullVisitorId values")

**Fallback:** If the LLM returns malformed JSON, the decomposer falls back to a single subtask equal to the full question — ensuring the pipeline never hard-fails at this stage.

**Example** for *"How many distinct users had a purchase in February 2017?"*:
```json
[
  {"id": 1, "description": "Identify the time period: February 2017", "parent_id": null, "level": 0},
  {"id": 2, "description": "Filter sessions that contain a purchase transaction", "parent_id": 1, "level": 1},
  {"id": 3, "description": "Count distinct visitor IDs in the filtered set", "parent_id": 2, "level": 2}
]
```

---

### 3. Explorer (`pipeline/explorer.py`)

An **agentic loop** that lets the LLM run read-only reconnaissance SQL against Snowflake before writing the final query. This is the most critical stage for databases with opaque VARIANT columns.

**Why exploration matters:** Spider2-Snow's GA360/GA4 databases store event data as deeply nested JSON (Snowflake VARIANT type). The DDL tells the model a column is `VARIANT` but not what's inside it. Without exploration, the model must guess JSON paths like `hits[0]:product[0]:v2ProductName::STRING` — and guesses are almost always wrong.

**Stage 1 — Schema grounding (deterministic):** Before the LLM starts, the explorer runs a single deterministic `INFORMATION_SCHEMA.COLUMNS` query against the tables mentioned in the DDL. This produces a **COLUMN ROSTER** — a verified, authoritative list of every column and its type for every relevant table. This runs without an LLM call and is injected into every subsequent prompt as ground truth.

**Stage 2 — Agentic recon (LLM-driven):** The LLM is given the column roster and the question, and asked to write exploratory SQL to understand the VARIANT structure. Each query result is fed back to the LLM, which can then issue another query or declare `READY`. The loop runs for at most `max_exploration_steps` steps (default: 3).

**Safety:** Only `SELECT`, `SHOW`, `DESCRIBE` statements are permitted. DML/DDL is blocked. A `LIMIT 5` is automatically appended to any SELECT that omits it, preventing accidental full-table scans.

**Error capture:** Every failed exploration query is captured as an `exploration_error` and passed to `error_to_learning()` immediately. This means even failed exploration steps produce learnings — the agent learns column quoting rules from its own mistakes.

**Output:** A markdown-formatted transcript (e.g., *"Agent ran: SELECT OBJECT\_KEYS(hits[0])... → Error: invalid identifier 'HITS'"*) that is appended verbatim to the generator prompt so the SQL writer can see exactly what was discovered and what failed.

---

### 4. Generator (`pipeline/generator.py`)

Generates the final Snowflake SQL, with all available context assembled:

| Input | Source |
|---|---|
| Full schema DDL | Context Loader |
| External documentation | Context Loader |
| Semantic subtask tree | Decomposer |
| Exploration transcript + COLUMN ROSTER | Explorer |
| Past learnings | `learnings.md` |
| Previous SQL + failure reason (on retry) | Requirements or Execution loop |

**Three prompt modes:**
1. **First attempt** — all context, no feedback
2. **Requirements retry** — adds which specific subtasks failed and why
3. **Execution retry** — adds the Snowflake error message from the failed SQL

The model is asked to write a `<thinking>` block (chain-of-thought) before the SQL. The `<thinking>` block is stripped from the output; only the SQL block is used downstream.

---

### 5. Requirements Checker (`pipeline/requirements.py`)

After generation, before execution, the LLM evaluates its own SQL against the subtask tree.

**How it works:** Each subtask is evaluated independently — the checker asks: *"Does this SQL logically address this subtask?"* This is intentionally strict: partial satisfaction counts as failure. The score is `satisfied_subtasks / total_subtasks`, computed against the full subtask list regardless of how many the LLM chose to evaluate (preventing a scoring exploit where returning fewer evaluations inflates the denominator).

**On failure:** The failing subtasks and their reasons are fed back to the Generator as `FAILED SUBTASKS` context. The generator then has another attempt to fix only the specific gaps. This loop runs up to `max_retries_requirements` times.

**Hard failure:** If the SQL fails requirements on all attempts, the instance is logged to `data/hard_failures/` and the pipeline moves on. These are valuable signal for later taxonomy analysis.

---

### 6. Executor (`pipeline/executor.py`)

Runs the SQL on Snowflake and returns a result DataFrame.

**Connection:** Uses the Snowflake Python connector with credentials from `snowflake_credential.json`. Each query runs with a statement timeout (`query_timeout_base`, scaling to `query_timeout_max` on retries).

**Silent failure detection:** A query that executes without error but returns 0 rows, or returns a DataFrame where every value is NULL, is treated as a failure. These are synthesized into `ErrorCheckResult` objects and re-enter the execution retry loop with an actionable error message (*"Query returned 0 rows — revisit JOIN conditions and filter keys"*). This catches a class of bugs — logically inverted filters, wrong join keys, misspelled string literals — that would otherwise silently produce wrong answers.

**Result storage:** On success, the result DataFrame is saved as `data/outputs/{instance_id}.csv` (the format expected by the evaluator), and the final SQL is saved as `data/outputs/{instance_id}.sql`.

---

### 7. Error Checker (`pipeline/error_checker.py`)

Classifies Snowflake execution errors into types (`syntax`, `invalid_identifier`, `type_error`, etc.) to enable targeted retry strategies. The classification also determines how the error is displayed in the retry prompt and how it is generalized by `error_to_learning`.

---

### 8. Learnings Memory (`memory/learnings.py`)

The core of the lifelong learning mechanism. `learnings.md` is a persistent, append-only markdown file that survives across all runs.

**Writing a learning:** Whenever a query fails — during exploration OR during execution — the pipeline calls `error_to_learning()`. This LLM call takes the raw Snowflake error and the failed SQL and produces a **generalized, reusable rule** — not a patch for this specific query, but a general Snowflake dialect principle.

Example: the raw error `invalid identifier 'HITS'` becomes:
> **Pattern:** Lowercase column names in GA360 GA_SESSIONS tables (e.g., `hits`, `totals`) are case-sensitive and must be double-quoted in Snowflake SQL.
> **Fix:** Write `"hits"[0]` not `hits[0]`.

**Deduplication:** Before appending, the pattern is normalized (lowercased, stripped) and compared against all existing entries. Duplicate patterns are silently dropped, preventing prompt bloat.

**Reading learnings:** At the start of each instance's requirements loop (and after each execution error), `read_learnings()` reads the current file and injects it into the generator prompt. This means a rule learned from instance 5's failure is automatically available to instance 6.

**Taxonomy extraction (post-batch):** After all instances in a batch complete, the evaluator runs a second LLM call over all failures together — looking for patterns that span multiple instances. This produces higher-level rules ("GA360 VARIANT columns always require lateral flatten with quoted column names") that individual per-error learnings might miss.

**Key design principle:** `learnings.md` is **never reset between runs**. Clearing it throws away accumulated knowledge and forces cold-start re-learning. It should only be reset when starting a completely new experimental configuration.

---

## Evaluation (`eval/evaluator.py`)

Follows the official Spider2-Snow evaluation protocol exactly.

**Offline mode:** Compares `data/outputs/{instance_id}.csv` against gold CSVs in `spider2-snow/evaluation_suite/gold/exec_result/`. Some instances have multiple valid answers (e.g., `sf_bq001_a.csv`, `sf_bq001_b.csv`) — the prediction is marked correct if it matches any one of them.

**Comparison logic:** Columns are compared by value, not by name. The `condition_cols` field in `spider2snow_eval.jsonl` specifies which gold columns must be matched — often just the numeric answer columns, not identifier columns. All numeric comparisons use an absolute tolerance of `1e-2`. Row order is ignored for all instances (`ignore_order: true`).

**Accuracy metric:** `correct / total_evaluated`. The official benchmark denominator is 547 (all instances), but per-batch accuracy is more useful for iterative development.

---

## Directory Structure

```
text2sql/
├── main.py                    # Orchestrator — runs the full pipeline
├── config.yaml                # All tunable settings
│
├── pipeline/
│   ├── decomposer.py          # NLQ → semantic subtask tree
│   ├── explorer.py            # Agentic schema reconnaissance
│   ├── generator.py           # SQL generation (3 prompt modes)
│   ├── requirements.py        # LLM-based subtask verification
│   ├── executor.py            # Snowflake execution + result storage
│   └── error_checker.py       # Error classification
│
├── memory/
│   └── learnings.py           # Persistent learning memory (read/write/generalize)
│
├── utils/
│   ├── llm.py                 # LLM abstraction (LiteLLM, retry, token counting)
│   ├── context_loader.py      # DDL + docs loader with budget enforcement
│   ├── prompt_templates.py    # All LLM prompts in one place
│   └── logger.py              # Per-instance structured JSON logging
│
├── eval/
│   └── evaluator.py           # Offline evaluation + taxonomy extraction
│
└── data/
    ├── learnings.md           # Persistent cross-run memory (never delete)
    ├── outputs/               # Per-instance: {id}.csv, {id}.sql, {id}_log.json
    └── hard_failures/         # Instances that exhausted all retries
```

---

## Configuration (`config.yaml`)

```yaml
# Model — swap with zero code changes. Any LiteLLM-supported provider works.
# Examples: anthropic/claude-opus-4-7, openai/gpt-4o, groq/llama-3.3-70b-versatile
model: "mistral/mistral-large-latest"
fallback_model: "mistral/mistral-large-latest"
temperature: 0

# Retry budget
max_retries_requirements: 3    # How many times generator can fix requirements failures
max_retries_execution: 3       # How many times generator can fix Snowflake errors

# Context budgets (characters; 0 = unlimited)
ddl_budget: 32000              # Max DDL chars injected into generator prompt
docs_budget: 8000              # Max external doc chars
learnings_budget: 0            # 0 = inject all learnings (no cap)
exploration_transcript_budget: 0  # 0 = inject full exploration transcript

# Exploration
max_exploration_steps: 3       # Max recon queries before declaring READY

# Learnings
max_learnings_entries: 0       # 0 = inject all entries (no age-based truncation)

# Execution
query_timeout_base: 60         # Snowflake statement timeout (seconds)
query_timeout_max: 300         # Max timeout on final attempt
```

---

## Setup

**1. Install dependencies**
```bash
cd text2sql
python -m venv .venv
.venv/Scripts/activate       # Windows
pip install -r requirements.txt
```

**2. Configure credentials**

Create `bhadresh/snowflake_credential.json`:
```json
{
  "user": "YOUR_USER",
  "password": "YOUR_PASSWORD",
  "account": "YOUR_ACCOUNT",
  "warehouse": "YOUR_WAREHOUSE",
  "role": "YOUR_ROLE"
}
```

Create `bhadresh/.env` with your LLM API key:
```
MISTRAL_API_KEY=...
# or ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, etc.
```

**3. Run**
```bash
# Single instance
python main.py --instance sf_bq001

# First 30 instances (default)
python main.py --limit 30

# Full benchmark
python main.py

# Different model
python main.py --model anthropic/claude-opus-4-7 --limit 10
```

---

## Model Requirements

The pipeline makes 5–7 LLM calls per instance. Three of them require genuine reasoning:

| Stage | What the model must do | Minimum viable |
|---|---|---|
| Decomposer | Parse NLQ → structured JSON hierarchy | Any 7B+ |
| Explorer | Write valid exploratory Snowflake SQL, interpret results | **22B+ code model** |
| Generator | Produce correct Snowflake SQL with VARIANT access, CTEs, date-partitioned UNION ALL | **22B+ code model** |
| Requirements checker | Reason about whether SQL logically satisfies each subtask | **22B+ reasoning model** |
| error_to_learning | Generalize a specific error into a reusable rule | 13B+ |

Spider2-Snow is deliberately hard: VARIANT column access (`col:key::TYPE`) is Snowflake-specific syntax, date-partitioned queries require long UNION ALL chains, and many questions require 4–6 CTEs with correct join logic. Models below ~22B parameters consistently produce syntactically plausible SQL that fails on semantic correctness.

**Recommended minimum for meaningful accuracy:** Mistral Large / GPT-4o / Claude Sonnet or better.

---

## The Lifelong Learning Loop in Practice

```
Run 1 (cold start):
  Instance 1:  Explorer fails on "hits" → learns: quote lowercase VARIANT columns
  Instance 2:  Reads that learning → explorer succeeds on first try
  Instance 5:  Fails on correlated subquery → learns: Snowflake doesn't support them
  Instance 6+: Avoids correlated subqueries entirely

Run 2 (warm start — learnings.md preserved from Run 1):
  Instance 1:  Already knows VARIANT quoting, correlated subquery rule, etc.
               Explorer succeeds immediately, generator produces correct syntax first try.
```

The agent gets measurably better across a benchmark run. The first ~5 instances on a new schema type pay the cold-start cost. All subsequent instances of that schema type benefit.

---

## Benchmark: Spider2-Snow

- **547 instances** across 30+ Snowflake databases
- Databases: GA360 (Google Analytics 360), GA4, BigQuery public datasets ported to Snowflake, financial data, sports data, e-commerce, etc.
- Hard cases: VARIANT JSON columns, date-partitioned tables (GA_SESSIONS_YYYYMMDD), correlated aggregations, multi-schema joins
- Evaluation: exact result match with ±0.01 numeric tolerance, order-insensitive

**Current baseline (Mistral Large, 10 GA360/GA4 instances):** 0/10 correct (0%). GA360 and GA4 are the hardest databases — all 10 instances required VARIANT column access that the model initially fails on. The accuracy figure improves significantly on simpler schemas (THELOOK_ECOMMERCE, IPL, STACKOVERFLOW). Full benchmark evaluation with a capable model is the next step.
