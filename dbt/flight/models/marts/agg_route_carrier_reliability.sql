-- Per-route, per-carrier reliability. Supplies the `by_carrier` breakdown for
-- GET /api/reliability/route (one row per origin+dest+carrier).
select
    origin,
    dest,
    carrier,
    count(*)                            as flights,
    avg(cast(dep_del15 as double))      as delay_rate
from {{ ref('stg_flights') }}
group by origin, dest, carrier
