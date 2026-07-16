-- Light typing/renaming over the airports source.
{% if var('use_seeds', false) %}
    {% set airports_relation = ref('seed_airports') %}
{% else %}
    {% set airports_relation = source('silver', 'airports') %}
{% endif %}

with src as (
    select * from {{ airports_relation }}
)

select
    cast(iata as varchar)   as iata,
    cast(name as varchar)   as name,
    cast(city as varchar)   as city,
    cast(lat as double)     as lat,
    cast(lon as double)     as lon,
    cast(tz as varchar)     as tz
from src
where iata is not null
