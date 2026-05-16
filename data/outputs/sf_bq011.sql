WITH
-- 7-day period ending on January 7, 2021 at 23:59:59
seven_day_period AS (
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201225 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201226 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201227 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201228 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201229 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201230 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20201231 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210101 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210102 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210103 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210104 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210105 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210106 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210107 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NOT NULL
),

-- 2-day period ending on January 7, 2021 at 23:59:59
two_day_period AS (
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210106 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NULL
    UNION ALL
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210107 t
    WHERE
        t."EVENT_PARAMS":engagement_time_msec IS NULL
),

-- Intersection of distinct pseudo users from the 7-day and 2-day periods
intersection AS (
    SELECT
        s."USER_PSEUDO_ID"
    FROM
        seven_day_period s
    INTERSECT
    SELECT
        t."USER_PSEUDO_ID"
    FROM
        two_day_period t
)

-- Count the number of distinct pseudo users in the intersection
SELECT
    COUNT(DISTINCT i."USER_PSEUDO_ID") AS distinct_pseudo_users_count
FROM
    intersection i;