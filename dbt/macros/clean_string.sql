{#
    Empty-string-to-null cleanup for a raw STRING column. Every raw.* column
    lands as a literal string with no NULL conversion (see
    ingestion/load_csv_to_adls.py's module docstring on why) -- this macro is
    where that conversion happens instead, once, rather than 17 times across
    4 staging models with `nullif(trim(x), '')` repeated verbatim.

    Usage: {{ clean_string('udh_notes') }} as notes_raw
#}
{% macro clean_string(column_name) %}
    nullif(trim({{ column_name }}), '')
{% endmacro %}
