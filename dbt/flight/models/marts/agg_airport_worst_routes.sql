-- Per-origin-airport routes ranked worst-first by delay rate. Supplies the
-- `historical.worst_routes` list in GET /api/airport/{iata}.
-- One row per origin+dest; `rnk` lets the serving layer take the top N.
select
    origin,
    dest,
    count(*)                            as flights,
    avg(cast(dep_del15 as double))      as delay_rate,
    row_number() over (
        partition by origin
        order by avg(cast(dep_del15 as double)) desc, count(*) desc
    )                                   as rnk
from {{ ref('stg_flights') }}
group by origin, dest
