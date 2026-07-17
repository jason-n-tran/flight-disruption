-- Per-origin-airport overall reliability (one row per origin).
-- Feeds the scalar `historical.overall_delay_rate` in GET /api/airport/{iata}.
-- Contract name: GOLD_AIRPORT_RELIABILITY = "agg_airport_reliability".
select
    origin,
    count(*)                            as flights,
    avg(cast(dep_del15 as double))      as overall_delay_rate
from {{ ref('stg_flights') }}
group by origin
