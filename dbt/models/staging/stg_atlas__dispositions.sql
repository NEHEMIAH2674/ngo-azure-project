-- Grain: 1 row per Atlas disposition (call_log_id). Confirmed unique in the
-- source extract (0 duplicate call_log_id values) -- no dedup needed.
--
-- 6,318 of 52,132 rows (12.1%) have a blank contract_id and 1,847 (3.5%)
-- have a blank customer_id. Both are kept here (this is staging, not a
-- filter layer) with NULL contract_id/customer_id; they're excluded only
-- where the mart logic specifically requires a contract (payment
-- attribution), and that exclusion is counted, not silent -- see
-- int_payment_attribution.sql and WRITEUP.md.

with source as (
    select * from {{ source('dlight_raw', 'atlas_dispositions') }}
),

typed as (
    select
        try_cast(call_log_id as BIGINT) as call_log_id,
        try_cast(tenant_id as BIGINT) as atlas_tenant_id,
        try_cast(customer_id as BIGINT) as customer_id,
        try_cast(contract_id as BIGINT) as contract_id,
        try_cast(created_timestamp_utc as TIMESTAMP) as disposed_at_utc,
        {{ clean_string('createdby') }} as created_by,
        {{ clean_string('call_type') }} as call_type,
        {{ clean_string('level_one') }} as level_one,
        {{ clean_string('level_two') }} as level_two,
        {{ clean_string('level_three') }} as level_three,
        CAST(NULL AS STRING) AS _source_file,
        CAST(NULL AS TIMESTAMP) AS _ingested_at
    from source
)

select
    t.*,
    c.country_name,
    c.ameyo_contact_center_id,
    c.currency_code
from typed as t
left join {{ ref('country_code_mapping') }} as c
    on t.atlas_tenant_id = c.atlas_tenant_id
