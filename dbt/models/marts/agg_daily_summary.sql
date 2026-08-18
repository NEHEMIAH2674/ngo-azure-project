-- Grain: 1 row per (day, market) -- a dashboard-friendly rollup of all four
-- metrics. Not asked for explicitly by the brief; added because a BI user
-- generally wants one landing table before drilling into the detailed
-- marts.
--
-- KNOWN LIMITATION: "day" is not perfectly aligned across the two source
-- systems being unioned here. fct_coding_rate's day is Ameyo's LOCAL
-- operational day; fct_paid_post_call/fct_inbound_call_drivers's day is
-- derived from Atlas's UTC timestamp. A call placed late in the evening
-- local time can therefore land in a different UTC calendar day. For the
-- days in this sample (Aug 4-7 2026) this shifts at most a handful of rows
-- across a day boundary and does not change the story, but it is not
-- exact -- flagged here and in WRITEUP.md rather than presented as a
-- perfectly reconciled join key.

with coding as (
    select
        call_date_local as day,
        market,
        sum(total_outbound_calls) as total_outbound_calls,
        sum(coded_calls) as coded_calls
    from {{ ref('fct_coding_rate') }}
    group by all
),

paid as (
    select
        date(disposed_at_utc) as day,
        country_name as market,
        count(*) as total_dispositions,
        countif(is_paid_post_call) as paid_post_call_count,
        sum(attributed_payment_amount_usd) as value_recovered_usd,
        countif(not is_window_closed) as still_in_window_count
    from {{ ref('fct_paid_post_call') }}
    group by all
),

inbound as (
    select
        disposition_date_utc as day,
        market,
        sum(call_count) as inbound_call_count
    from {{ ref('fct_inbound_call_drivers') }}
    group by all
),

coding_paid as (
    select
        coalesce(coding.day, paid.day) as day,
        coalesce(coding.market, paid.market) as market,
        coding.total_outbound_calls,
        coding.coded_calls,
        paid.total_dispositions,
        paid.paid_post_call_count,
        paid.value_recovered_usd,
        paid.still_in_window_count
    from coding
    full outer join paid
        on coding.day = paid.day and coding.market = paid.market
)

select
    coalesce(coding_paid.day, inbound.day) as day,
    coalesce(coding_paid.market, inbound.market) as market,
    coding_paid.total_outbound_calls,
    coding_paid.coded_calls,
    safe_divide(coding_paid.coded_calls, coding_paid.total_outbound_calls) as coding_rate,
    coding_paid.total_dispositions,
    coding_paid.paid_post_call_count,
    safe_divide(coding_paid.paid_post_call_count, coding_paid.total_dispositions) as paid_post_call_rate,
    coding_paid.value_recovered_usd,
    coding_paid.still_in_window_count,
    inbound.inbound_call_count
from coding_paid
full outer join inbound
    on coding_paid.day = inbound.day and coding_paid.market = inbound.market
