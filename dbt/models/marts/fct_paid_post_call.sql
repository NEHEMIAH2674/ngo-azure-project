-- Grain: 1 row per Atlas disposition (call_log_id) -- every disposed call,
-- not just outbound/coded ones, since "of the calls disposed in Atlas"
-- (the brief's own wording for Metric 2) is the base population.
--
-- THE MOVING-WINDOW PROBLEM: a call disposed today cannot be finally
-- assessed for paid-post-call until {{ var('paid_post_call_window_days') }}
-- days from now, because its payment window is still open. This model does
-- not try to avoid that -- it's re-materialized (full table rebuild) on
-- every run, so is_paid_post_call and attributed_payment_amount_* always
-- reflect payments known as of THIS run and will keep changing for calls
-- inside their window. is_window_closed tells a consumer whether a given
-- row's numbers are final or still provisional:
--   - is_window_closed = true  -> settled, will not change again.
--   - is_window_closed = false -> provisional; will be recomputed and may
--     change on every subsequent daily run until the window closes.
-- Any published Metric 2/3 figure should be read alongside this flag (see
-- the dashboard and WRITEUP.md) -- this is the classic accumulating-
-- snapshot pattern, applied at the row level rather than only in prose.
--
-- 6,318 dispositions (12.1%) have no contract_id and can never be
-- attributed to a payment; they appear here with is_paid_post_call = false
-- and attributed_payment_count = 0, not excluded, so the denominator for
-- Metric 2 stays the full, honest population of disposed calls. Whether to
-- report Metric 2 over all dispositions or only those with a contract_id
-- is a judgment call the team should make deliberately -- both cuts are
-- computable from this mart (filter on contract_id is not null).

select
    d.*,
    coalesce(cps.attributed_payment_count, 0) as attributed_payment_count,
    coalesce(cps.attributed_payment_count, 0) > 0 as is_paid_post_call,
    cps.attributed_payment_amount_local,
    cps.attributed_payment_amount_usd,
    coalesce(cps.has_unconverted_payment, false) as has_unconverted_payment,
    coalesce(cps.used_estimated_fx_rate, false) as used_estimated_fx_rate,
    cps.first_attributed_payment_at,
    timestamp_add(d.disposed_at_utc, interval {{ var('paid_post_call_window_days') }} day) as window_closes_at_utc,
    current_timestamp() >= timestamp_add(d.disposed_at_utc, interval {{ var('paid_post_call_window_days') }} day) as is_window_closed
from {{ ref('stg_atlas__dispositions') }} d
left join {{ ref('int_call_payment_summary') }} cps using (call_log_id)
