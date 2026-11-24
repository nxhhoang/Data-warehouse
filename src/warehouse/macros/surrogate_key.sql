{% macro gen_sk(columns) -%}
  FARM_FINGERPRINT(
    CONCAT(
      {%- for col in columns -%}
        COALESCE(NULLIF(TRIM(CAST({{ col }} AS STRING)), ''), '__NULL__')
        {%- if not loop.last -%}, '|', {%- endif -%}
      {%- endfor -%}
    )
  )
{%- endmacro %}