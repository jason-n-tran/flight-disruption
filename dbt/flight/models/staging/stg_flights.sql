-- Light typing/renaming over the flights source.
-- Source toggle: when var('use_seeds') is true (CI / no real lake), read from
-- the dbt seed; otherwise read the silver parquet via the source.
{% if var('use_seeds', false) %}
    {% set flights_relation = ref('seed_flights') %}
{% else %}
    {% set flights_relation = source('silver', 'flights') %}
{% endif %}

with src as (
    select * from {{ flights_relation }}
)

select
    cast(flight_date as date)                                as flight_date,
    cast(year as integer)                                   as year,
    cast(month as integer)                                  as month,
    cast(day_of_week as integer)                            as day_of_week,
    cast(dep_hour as integer)                               as dep_hour,
    cast(time_of_day_bucket as varchar)                     as time_of_day_bucket,
    cast(carrier as varchar)                                as carrier,
    cast(flight_number_reporting_airline as varchar)        as flight_number,
    cast(origin as varchar)                                 as origin,
    cast(dest as varchar)                                   as dest,
    cast(distance as double)                                as distance,
    cast(crs_dep_time as integer)                           as crs_dep_time,
    cast(crs_arr_time as integer)                           as crs_arr_time,
    cast(crs_elapsed_time as double)                        as crs_elapsed_time,
    cast(dep_del15 as integer)                              as dep_del15,
    cast(dep_delay_minutes as double)                       as dep_delay_minutes,
    cast(arr_del15 as integer)                              as arr_del15,
    cast(cancelled as integer)                              as cancelled,
    cast(diverted as integer)                               as diverted,
    cast(carrier_delay as double)                           as carrier_delay,
    cast(weather_delay as double)                           as weather_delay,
    cast(nas_delay as double)                               as nas_delay,
    cast(security_delay as double)                          as security_delay,
    cast(late_aircraft_delay as double)                     as late_aircraft_delay,
    cast(is_holiday_window as integer)                      as is_holiday_window
from src
-- Reliability marts describe operated flights; exclude cancelled rows so a
-- cancellation is not silently counted as "not delayed".
where coalesce(cast(cancelled as integer), 0) = 0
