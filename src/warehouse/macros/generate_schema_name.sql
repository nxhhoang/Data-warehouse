{#
  Use custom schema names as-is (staging, core, marts) instead of dbt's
  default <target_schema>_<custom> suffix. The KPI views (src/kpi/*.sql) and
  the benchmark (tests/benchmark_kpi.py) reference `${PROJECT_ID}.core.*`
  and `${PROJECT_ID}.marts.*`, so the three datasets must keep exact names.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
