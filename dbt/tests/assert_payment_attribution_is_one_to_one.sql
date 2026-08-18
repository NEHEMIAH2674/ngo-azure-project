-- Singular test: a single payment must never be attributed to more than
-- one call. int_payment_attribution.sql guarantees this by construction
-- (ROW_NUMBER() partitioned by payment_row_key), but this test asserts it
-- against the materialized output directly, as insurance against a future
-- refactor breaking that guarantee silently. Returns offending rows; a
-- dbt test fails if this query returns any.

select payment_row_key, count(distinct attributed_call_log_id) as call_count
from {{ ref('int_payment_attribution') }}
where is_attributed_to_a_call
group by payment_row_key
having count(distinct attributed_call_log_id) > 1
