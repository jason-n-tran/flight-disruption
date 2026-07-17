-- Per-carrier reliability (one row per carrier).
-- Contract name: GOLD_CARRIER_RELIABILITY = "agg_carrier_reliability".
select
    carrier,
    count(*)                            as flights,
    avg(cast(dep_del15 as double))      as delay_rate
from {{ ref('stg_flights') }}
group by carrier
