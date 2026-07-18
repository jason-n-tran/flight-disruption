{#
    Self-contained composite-uniqueness test (no dbt_utils dependency).
    Fails (returns rows) when any combination of the given columns appears
    more than once. A passing test returns zero rows.

    Usage in schema.yml (model-level):
        data_tests:
          - unique_combination:
              columns: [origin, dest]
#}
{% test unique_combination(model, columns) %}

with grouped as (
    select
        {{ columns | join(", ") }},
        count(*) as n
    from {{ model }}
    group by {{ columns | join(", ") }}
)
select * from grouped where n > 1

{% endtest %}
