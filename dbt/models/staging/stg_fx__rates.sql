-- Grain: 1 row per (rate_date, currency). Produced by our own
-- ingestion/api/fx/, already correctly typed at landing (unlike
-- the four case-study CSVs, this isn't a source we've committed to
-- preserving byte-for-byte) -- this model just passes it through under
-- staging naming conventions.

select
    rate_date,
    currency as currency_code,
    usd_to_local_rate,
    rate_is_estimated,
    rate_source,
    fetched_at
from {{ source('dlight_raw', 'fx_rates') }}
