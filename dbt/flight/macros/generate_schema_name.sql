{#
    Override dbt's default schema-name generation.

    Default behaviour concatenates the target schema with the custom schema
    (e.g. `main` + `staging` -> `main_staging`). For this project the gold
    MARTS must live in the bare target schema (`main`) so the FastAPI serving
    layer can read them as unqualified table names (SELECT * FROM dim_airports).

    Behaviour here:
      - no custom +schema set  -> use the target schema verbatim (main)
      - custom +schema set     -> use that custom name verbatim (staging, seeds)
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
