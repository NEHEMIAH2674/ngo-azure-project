-- Grain: 1 row per call_log_id that has at least one payment attributed to
-- it via int_payment_attribution. Aggregates payment-level detail up to the
-- call grain that fct_paid_post_call needs.

select
    attributed_call_log_id as call_log_id,
    count(*) as attributed_payment_count,
    sum(amount_local) as attributed_payment_amount_local,
    sum(amount_usd) as attributed_payment_amount_usd,
    logical_or(amount_usd is null) as has_unconverted_payment,
    logical_or(coalesce(fx_rate_is_estimated, false)) as used_estimated_fx_rate,
    min(paid_at_utc) as first_attributed_payment_at
from {{ ref('int_payment_attribution') }}
where is_attributed_to_a_call
group by call_log_id
