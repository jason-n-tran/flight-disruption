{#
    Self-contained accepted_range generic test (no dbt_utils dependency, so the
    project runs in an offline CI where dbt hub is unreachable).

    Returns rows that fall OUTSIDE [min_value, max_value]. A passing test
    returns zero rows. Nulls are ignored here (use not_null separately).

    Usage in schema.yml:
        data_tests:
          - accepted_range:
              min_value: 0
              max_value: 1
#}
{% test accepted_range(model, column_name, min_value, max_value) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and (
        {{ column_name }} < {{ min_value }}
     or {{ column_name }} > {{ max_value }}
  )

{% endtest %}
