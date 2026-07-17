-- Per-route reliability (one row per origin+dest).
-- Feeds GET /api/reliability/route (the scalar fields; the by_carrier list
-- comes from agg_route_carrier_reliability).
-- Contract name: GOLD_ROUTE_RELIABILITY = "agg_route_reliability".
select
    origin,
    dest,
    count(*)                                        as flights,
    avg(cast(dep_del15 as double))                  as delay_rate,
    avg(dep_delay_minutes)                          as avg_delay_min
from {{ ref('stg_flights') }}
group by origin, dest
