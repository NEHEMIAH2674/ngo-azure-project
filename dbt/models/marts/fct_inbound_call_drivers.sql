-- Grain: 1 row per (disposition_date_utc, market, level_one, level_two,
-- level_three) among calls disposed as inbound (call_type = 'Inbound
-- Team'). A BI tool can roll this up to level_one alone for the top-line
-- view and drill into level_two/three from the same table, per the brief's
-- "start at level one and drill down" ask.
--
-- level_two and level_three are genuinely optional in the source (populated
-- less often at each level down) -- coalesced to 'Not specified' rather
-- than left NULL, so GROUP BY/aggregation in a BI tool doesn't silently
-- drop rows with a missing level_two/three.

select
    date(disposed_at_utc) as disposition_date_utc,
    country_name as market,
    coalesce(level_one, 'Not specified') as level_one,
    coalesce(level_two, 'Not specified') as level_two,
    coalesce(level_three, 'Not specified') as level_three,
    count(*) as call_count
from {{ ref('stg_atlas__dispositions') }}
where call_type = 'Inbound Team'
group by all
