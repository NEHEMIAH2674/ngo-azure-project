-- Grain: 1 row per payment transaction, after collapsing exact-duplicate
-- transmissions of the same event.
--
-- Payments has no natural id. 23 rows in this extract are byte-identical
-- across every business column (timestamp to the millisecond, tenant,
-- contract, provider, program, amount) -- almost certainly the same
-- payment event transmitted twice, not two independent payments that
-- coincidentally match down to the millisecond. We collapse those to one
-- row (keeping the earliest-ingested copy; the choice of which physical
-- copy survives doesn't matter since they're identical in every column
-- that isn't pipeline metadata). Anything that differs in even one column
-- is a distinct row and is never touched here.
--
-- Two rows have provider = 'MANUAL' and amount = 0.0 (Nigeria): these read
-- as non-monetary adjustment entries, not real payments. They are flagged
-- via is_zero_amount rather than dropped, so row counts stay honest;
-- downstream monetary sums (Metric 3) exclude them explicitly.

with source as (
    select * from {{ source('dlight_raw', 'payments') }}
),

typed as (
    select
        CONCAT_WS("-", tenant_id, contract_id, CAST(pay_timestamp_utc AS STRING)) AS payment_row_key,
        {{ clean_string('payment_request_provider') }} as payment_provider,
        {{ clean_string('create_program') }} as ingest_program,
        try_cast(tenant_id as BIGINT) as atlas_tenant_id,
        try_cast(contract_id as BIGINT) as contract_id,
            try_cast(amount as DOUBLE) as amount_local,
            try_cast(pay_timestamp_utc as TIMESTAMP) as paid_at_utc,
        CAST(NULL AS STRING) AS _source_file,
        CAST(NULL AS TIMESTAMP) AS _ingested_at
    from source
),

deduped as (
    select
        *,
        row_number() over (
            partition by payment_row_key
            order by _ingested_at asc
        ) as _dedup_rank
    from typed
)

select
    d.* except (_dedup_rank),
    c.country_name,
    c.ameyo_contact_center_id,
    c.currency_code,
    (d.amount_local = 0) as is_zero_amount
from deduped as d
left join {{ ref('country_code_mapping') }} as c
    on d.atlas_tenant_id = c.atlas_tenant_id
where d._dedup_rank = 1
