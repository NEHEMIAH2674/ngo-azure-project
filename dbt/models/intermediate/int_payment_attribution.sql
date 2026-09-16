-- Grain: 1 row per payment (same grain as stg_atlas__payments), with the
-- single call it's attributed to (if any) and its USD conversion.
--
-- ATTRIBUTION RULE (assumption, since the brief leaves this open): a
-- customer may hold several contracts, be called more than once in a day,
-- and make several payments in a day. Each payment is attributed to its
-- single NEAREST-PRECEDING disposed call on the same contract, within the
-- {{ var('paid_post_call_window_days') }}-day window. Concretely: among all
-- dispositions on the same contract_id with disposed_at_utc <= paid_at_utc
-- and disposed_at_utc > paid_at_utc - N days, the one with the latest
-- disposed_at_utc wins.
--
-- Why nearest-preceding rather than "credit every call in the window":
-- Metric 3 sums money. If a customer is called three times in the 3 days
-- before paying, crediting all three calls would triple-count the same
-- shilling of recovered value across the coding-rate/paid-post-call
-- breakdown. Nearest-preceding guarantees each payment is attributed to
-- at most one call, so attributed amounts never double-count (see the
-- dbt_utils.unique_combination_of_columns test on this model and the
-- singular test in tests/assert_payment_attribution_is_one_to_one.sql).
-- The trade-off: an earlier call in a multi-call sequence gets no credit
-- even if it was the one that actually prompted the customer to pay.
-- That's a real limitation, not hidden -- see WRITEUP.md.
--
-- Zero-amount rows (is_zero_amount, the MANUAL adjustment entries) are
-- excluded from attribution entirely: they read as non-monetary ledger
-- adjustments, not payments a call could plausibly have driven.
--
-- FX conversion happens per-payment, at the payment's own date, not the
-- call's date -- more precise when a payment lands a day or two after the
-- call than converting the whole attributed total at one date would be.

with payments as (
    select * from {{ ref('stg_atlas__payments') }}
    where not is_zero_amount
),

dispositions as (
    select * from {{ ref('stg_atlas__dispositions') }}
    where contract_id is not null
),

fx as (
    select * from {{ ref('stg_fx__rates') }}
),

candidate_calls as (
    select
        p.payment_row_key,
        d.call_log_id,
        d.disposed_at_utc,
        row_number() over (
            partition by p.payment_row_key
            order by d.disposed_at_utc desc
        ) as _preference_rank
    from payments as p
    inner join dispositions as d
        on
            p.contract_id = d.contract_id
            and p.paid_at_utc >= d.disposed_at_utc
            and d.disposed_at_utc > p.paid_at_utc - INTERVAL {{ var('paid_post_call_window_days') }} DAY
),

attribution as (
    select
        payment_row_key,
        call_log_id as attributed_call_log_id
    from candidate_calls
    where _preference_rank = 1
)

select
    p.*,
    a.attributed_call_log_id,
    fx.usd_to_local_rate,
    fx.rate_is_estimated as fx_rate_is_estimated,
    a.attributed_call_log_id is not null as is_attributed_to_a_call,
    case
        when fx.usd_to_local_rate is not null then p.amount_local / fx.usd_to_local_rate
    end as amount_usd
from payments as p
left join attribution as a on p.payment_row_key = a.payment_row_key
left join fx
    on
        p.currency_code = fx.currency_code
        and fx.rate_date = date(p.paid_at_utc)
