{% macro unknown_member(sk_col, columns=[]) -%}
SELECT
    CAST(-1 AS INT64) AS {{ sk_col }}
    {%- for col_name, col_type in columns -%}
    ,
    {%- set t = col_type | upper -%}
    {%- if t == 'STRING' %}
    CAST('Không xác định' AS STRING) AS {{ col_name }}
    {%- elif t in ['INT64', 'INT', 'INTEGER'] %}
    CAST(-1 AS INT64) AS {{ col_name }}
    {%- elif t in ['FLOAT64', 'FLOAT'] %}
    CAST(-1.0 AS FLOAT64) AS {{ col_name }}
    {%- elif t == 'NUMERIC' %}
    CAST(-1 AS NUMERIC) AS {{ col_name }}
    {%- elif t in ['BOOL', 'BOOLEAN'] %}
    CAST(FALSE AS BOOL) AS {{ col_name }}
    {%- elif t == 'DATE' %}
    CAST('1900-01-01' AS DATE) AS {{ col_name }}
    {%- elif t == 'DATETIME' %}
    CAST('1900-01-01 00:00:00' AS DATETIME) AS {{ col_name }}
    {%- elif t == 'TIMESTAMP' %}
    CAST('1900-01-01 00:00:00' AS TIMESTAMP) AS {{ col_name }}
    {%- else %}
    CAST(NULL AS {{ col_type }}) AS {{ col_name }}
    {%- endif %}
    {%- endfor %}
{%- endmacro %}