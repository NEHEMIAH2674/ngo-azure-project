-- Singular test: coded_calls can never exceed total_outbound_calls for the
-- same row. A join fan-out bug (e.g. an agent-mapping join that duplicates
-- rows) would silently inflate coded_calls without this guard.

select *
from {{ ref('fct_coding_rate') }}
where coded_calls > total_outbound_calls
