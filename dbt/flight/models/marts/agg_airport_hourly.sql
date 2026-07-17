-- Per-origin-airport, per-hour reliability. Supplies the `historical.by_hour`
-- chart in GET /api/airport/{iata} (one row per origin+hour).
select
    origin,
    dep_hour                            as hour,
    count(*)                            as flights,
    avg(cast(dep_del15 as double))      as delay_rate
from {{ ref('stg_flights') }}
group by origin, dep_hour
