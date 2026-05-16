WITH filtered_variants AS (
    SELECT
        t."reference_bases",
        t."start_position"
    FROM
        HUMAN_GENOME_VARIANTS.HUMAN_GENOME_VARIANTS._1000_GENOMES_PHASE_3_OPTIMIZED_SCHEMA_VARIANTS_20150220 t
    WHERE
        t."reference_bases" = 'AT' OR t."reference_bases" = 'TA'
),
min_max_positions AS (
    SELECT
        MIN(t."start_position") AS min_start_position,
        MAX(t."start_position") AS max_start_position
    FROM
        filtered_variants t
),
proportions AS (
    SELECT
        SUM(CASE WHEN t."reference_bases" = 'AT' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS proportion_AT,
        SUM(CASE WHEN t."reference_bases" = 'TA' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS proportion_TA
    FROM
        filtered_variants t
)
SELECT
    m.min_start_position,
    m.max_start_position,
    p.proportion_AT,
    p.proportion_TA
FROM
    min_max_positions m,
    proportions p;