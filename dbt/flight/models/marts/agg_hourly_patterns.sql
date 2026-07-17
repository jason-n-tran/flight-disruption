-- Temporal delay patterns by departure hour and day-of-week. Feeds the
-- temporal-patterns chart. One row per (dep_hour, day_of_week); the serving /
-- BI layer can roll up to hour-only by aggregating across day_of_week.
-- Contract name: GOLD_HOURLY_PATTERNS = "agg_hourly_patterns".
select
    dep_hour,
    day_of_week,
    count(*)                            as flights,
    avg(cast(dep_del15 as double))      as delay_rate
from {{ ref('stg_flights') }}
group by dep_hour, day_of_week
