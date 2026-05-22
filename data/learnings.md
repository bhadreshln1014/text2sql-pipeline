
## [2026-05-23 01:07] [EXPLORER_invalid_identifier]
**Pattern:** A column is referenced in a SQL query that does not exist in the specified table or is not spelled/cased correctly according to the table's schema.
**Fix:** Always verify the column names against the table's schema before writing queries. Pay special attention to case sensitivity, especially for columns defined with double-quotes in Snowflake, as these must be referenced exactly as defined (including quotes).
**Example:** `{'incorrect': 'SELECT "hcpcs_drug_indicator" FROM CMS_DATA.CMS_MEDICARE.PART_D_PRESCRIBER_2014;', 'correct': 'SELECT "hcpcs_drug_indicator" FROM CMS_DATA.CMS_MEDICARE.PHYSICIANS_AND_OTHER_SUPPLIER_2014;'}`

---

## [2026-05-23 01:07] [schema_error]
**Pattern:** No prediction CSV found
**Fix:** Ensure the SQL query is executed in an environment where the required tables and data sources are accessible. Verify that the query is syntactically correct and that the output path for the CSV is properly specified or that the query is being run in a context where results can be generated.
**Example:** `For instance, if the query is supposed to run in a BigQuery environment, ensure the dataset and tables referenced exist and the user has the necessary permissions. If running locally, ensure the data is loaded into the database before executing the query.`

---

## [2026-05-23 01:07] [other]
**Pattern:** Missing or incomplete SQL query in error report
**Fix:** Provide the full SQL query in the error report to enable debugging. Ensure the query logic aligns with the question requirements and that all referenced columns and tables exist in the schema.
**Example:** `For the question 'How many distinct pseudo users had positive engagement time in the 7-day period...', the SQL query should include filters for the date range, conditions for positive engagement time, and proper aggregation (e.g., COUNT DISTINCT).`

---

## [2026-05-23 01:14] [EXPLORER_invalid_identifier]
**Pattern:** A column alias defined in a subquery or CTE is referenced in an outer query, but the alias is not recognized due to scoping rules or incorrect quoting.
**Fix:** Ensure that column aliases used in outer queries are either: (1) defined in the immediate SELECT clause of the outer query, or (2) referenced from the correct table or subquery with proper scoping. Always verify column names match exactly, including case sensitivity when double-quotes are used.
**Example:** `{'incorrect': 'SELECT MAX("total_runs") FROM (SELECT SUM(runs) AS total_runs FROM table);', 'correct': 'SELECT MAX(runs_sum) FROM (SELECT SUM(runs) AS runs_sum FROM table);'}`

---

## [2026-05-23 01:15] [other]
**Pattern:** Execution environment failure (missing output generation)
**Fix:** Validate that the execution environment is configured to produce output (e.g., CSV files). If using a script or tool to run the query, ensure it supports output generation. Test with a simple query (e.g., `SELECT 1`) to confirm the environment works as expected.
**Example:** `If a script fails to generate a CSV for `SELECT * FROM users LIMIT 1`, the issue is likely with the execution environment rather than the SQL query itself.`

---

## [2026-05-23 01:19] [invalid_identifier]
**Pattern:** A column name referenced in the SQL query does not exist in the specified table or is not spelled/cased correctly according to the source of truth. This often occurs when the column is case-sensitive and not properly quoted or when the column name is misspelled.
**Fix:** Always verify column names against the verified column roster for the table being queried. Use double-quotes around column names if they are case-sensitive or contain special characters. Ensure the column exists in the table referenced in the query.
**Example:** `{'incorrect': 'SELECT name FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES;', 'correct': 'SELECT "name" FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES;'}`

---

## [2026-05-23 01:20] [syntax]
**Pattern:** Referencing a case-sensitive column without using double-quotes in Snowflake SQL, or referencing a column that does not exist in the specified table.
**Fix:** Always verify column names and their case sensitivity in the source table. For case-sensitive columns, enclose the column name in double-quotes. For case-insensitive columns, use uppercase without quotes or ensure the column exists in the table.
**Example:** `{'incorrect': "SELECT year FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES WHERE year = '2020';", 'correct': 'SELECT "year" FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES WHERE "year" = \'2020\';'}`

---

## [2026-05-23 01:20] [other]
**Pattern:** Execution environment failure (missing output file)
**Fix:** Confirm that the execution engine or script is configured to generate and save output files (e.g., CSV). Debug the execution pipeline to ensure the query result is being captured and written to the expected location.
**Example:** `If a script expects a CSV file at `/output/results.csv` but the directory does not exist or lacks write permissions, the error will occur. The fix is to ensure the output directory exists and is writable.`

---

## [2026-05-23 01:34] [syntax]
**Pattern:** Referencing a column with incorrect case sensitivity or missing quotes for a case-sensitive identifier
**Fix:** Always verify the exact column name and case sensitivity from the schema. For case-sensitive columns (typically those with lowercase or mixed-case names), ensure they are enclosed in double quotes in SQL queries
**Example:** `{'incorrect': 'SELECT t.lat FROM my_table t;', 'correct': 'SELECT t."lat" FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES t;'}`

---

## [2026-05-23 01:34] [other]
**Pattern:** Missing or incomplete SQL query in the execution request
**Fix:** Provide a complete and valid SQL query for execution. Ensure all required clauses (e.g., SELECT, FROM, WHERE) are included and correctly formatted.
**Example:** `In the provided failures, SQL queries are missing entirely, leading to 'No prediction CSV found'. Always include a full SQL query in the request.`

---

## [2026-05-23 01:44] [syntax]
**Pattern:** Incomplete or incorrect function name in SQL expression, particularly when using Snowflake's geospatial functions. The error occurs when a function name is truncated or misspelled.
**Fix:** Always ensure that function names are complete and correctly spelled. For Snowflake geospatial functions, verify the full function name (e.g., ST_MAKEPOINT, ST_DISTANCE) and include the proper type casting (e.g., ::GEOGRAPHY).
**Example:** `{'incorrect': 'ST_MAKEPOINT("lon", "lat")::GE', 'correct': 'ST_MAKEPOINT("lon", "lat")::GEOGRAPHY'}`

---

## [2026-05-23 02:00] [syntax]
**Pattern:** Attempting to cast a spatial function result directly to a GEOGRAPHY type without ensuring the input values are valid for the target type
**Fix:** Validate or transform the input values (e.g., longitude and latitude) to ensure they are within the valid range for the GEOGRAPHY type before casting. Use explicit conversion functions or handle NULL/invalid values appropriately
**Example:** `{'incorrect': 'SELECT CAST(ST_MAKEPOINT(longitude, latitude) AS GEOGRAPHY) FROM my_table;', 'correct': 'SELECT TO_GEOGRAPHY(ST_ASWKT(ST_MAKEPOINT(longitude, latitude))) FROM my_table WHERE longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90;'}`

---

## [2026-05-23 02:01] [syntax]
**Pattern:** Attempting to cast a spatial function result directly to a GEOGRAPHY type using CAST()
**Fix:** Use the TRY_TO_GEOGRAPHY function or TO_GEOGRAPHY function directly with ST_MAKEPOINT instead of wrapping it in a CAST. Snowflake requires spatial functions to be explicitly converted using spatial-specific functions rather than generic CAST.
**Example:** `{'incorrect': 'CAST(ST_MAKEPOINT(longitude, latitude) AS GEOGRAPHY)', 'correct': 'TO_GEOGRAPHY(ST_MAKEPOINT(longitude, latitude))'}`

---

## [2026-05-23 02:03] [EXPLORER_invalid_identifier]
**Pattern:** A column referenced in the SQL query does not exist in the specified table or is not spelled correctly according to the column roster.
**Fix:** Always verify that the column names used in your query exactly match those listed in the table's column roster. Pay special attention to case sensitivity, especially if the column is defined with double quotes (e.g., "column_name"). Use the correct table name and ensure the column belongs to that table.
**Example:** `{'incorrect': "SELECT COUNT(*) FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES WHERE basin = 'NA' AND season = '2020' LIMIT 5;", 'correct': 'SELECT COUNT(*) FROM NOAA_DATA.NOAA_HURRICANES.HURRICANES WHERE "BASIN" = \'NA\' AND "SEASON" = \'2020\' LIMIT 5;'}`

---

## [2026-05-23 02:08] [syntax]
**Pattern:** Unexpected identifier or keyword in a window function or aggregate function definition, often due to incorrect placement or missing keywords like OVER, AS, or parentheses mismatch.
**Fix:** Ensure window functions are properly structured with the OVER clause, correct parentheses matching, and valid identifiers. Verify that all required keywords are present and in the right order (e.g., PARTITION BY, ORDER BY, ROWS/RANGE).
**Example:** `{'incorrect': 'SELECT column1, AVG(column2) PARTITION BY column3 FROM table1;', 'correct': 'SELECT column1, AVG(column2) OVER (PARTITION BY column3) FROM table1;'}`

---

## [2026-05-23 02:09] [empty_result]
**Pattern:** A query executes successfully but returns no rows due to overly restrictive filtering or join conditions, often caused by incorrect column references, mismatched data types, or logical errors in WHERE/JOIN clauses.
**Fix:** 1) Verify column names and data types match the source tables. 2) Check for case sensitivity in column names (use double-quotes for case-sensitive columns). 3) Test filter conditions independently to isolate the issue. 4) Use LEFT JOINs temporarily to identify which join is eliminating rows. 5) Validate date ranges and value formats (e.g., 'DE' vs 'de').
**Example:** `{'problematic': 'WHERE p."country_code" = \'de\' AND p."grant_date" BETWEEN 20161201 AND 20161231', 'fixed': 'WHERE p."country_code" = \'DE\' AND p."grant_date" BETWEEN 20161201 AND 20161231 -- Corrected case sensitivity and validated date format'}`

---

## [2026-05-23 02:09] [other]
**Pattern:** Execution environment or pipeline failure
**Fix:** Check the execution environment or pipeline for issues unrelated to the SQL syntax or logic. This may include missing input files, permission issues, or misconfigured execution steps. Ensure the query is being passed correctly to the SQL engine.
**Example:** `If the SQL query is correct but the system reports 'No prediction CSV found', the issue may lie in the data export or pipeline step rather than the query itself.`

---

## [2026-05-23 02:12] [syntax]
**Pattern:** Incomplete or malformed Common Table Expression (CTE) definition, specifically missing closing parenthesis or incomplete SQL statement before a new CTE or query begins. This can also occur when referencing a CTE alias incorrectly or truncating a query mid-expression.
**Fix:** Ensure all CTEs are properly closed with a parenthesis and followed by a comma (except the last one). Verify that all referenced CTE aliases match exactly (case-sensitive if quoted) and that the SQL statement is complete before starting a new CTE or main query. Always terminate expressions properly and check for balanced parentheses.
**Example:** `{'incorrect': 'WITH cte1 AS (SELECT col1 FROM table1), cte2 AS (SELECT col2 FROM cte1', 'correct': 'WITH cte1 AS (SELECT col1 FROM table1), cte2 AS (SELECT col2 FROM cte1) SELECT * FROM cte2;'}`

---

## [2026-05-23 02:13] [syntax]
**Pattern:** Using an invalid or undefined identifier (table alias, column name, or CTE name) in a SQL query
**Fix:** 1. Verify all identifiers (table aliases, column names, CTE names) are correctly spelled and exist in the referenced tables or CTEs. 2. Ensure CTE names are properly defined before use. 3. Check for typos or case sensitivity issues (especially in Snowflake where quoted identifiers are case-sensitive). 4. Use the provided column roster to confirm valid column/table names.
**Example:** `{'incorrect': 'SELECT gp."filing_date" FROM german_p', 'correct': 'SELECT gp."filing_date" FROM german_patents_dec_2016 gp'}`

---

## [2026-05-23 02:13] [other]
**Pattern:** Execution environment or output handling failure
**Fix:** Validate that the execution environment supports CSV output generation. If the query is part of a pipeline, ensure downstream processes (e.g., CSV writing or reading) are correctly configured. Test the query in a standalone environment to isolate the issue.
**Example:** `A query executed in a notebook environment may fail if the output path for the CSV is not specified or permissions are missing. Specify a valid output path or check permissions.`

---
