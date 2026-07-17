-- Airport dimension served at /api/meta/options and /api/airport/{iata}.
-- One row per IATA code. Contract name: GOLD_AIRPORTS_DIM = "dim_airports".
select
    iata,
    name,
    city,
    lat,
    lon
from {{ ref('stg_airports') }}
