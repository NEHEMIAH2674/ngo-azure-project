-- Grain: 1 row per (call_date_local, market, campaign, agent) -- the exact
-- breakdown the brief asks for, since it's meant for coaching individual
-- agents.
--
-- "Day" here is the agent's LOCAL operational day (from Ameyo's local
-- ch_date_added), not the UTC calendar day: a call-centre coaching report
-- should group by the day the agent experienced, not by a UTC boundary
-- that can fall mid-shift. Documented as an assumption in WRITEUP.md.

with coded as (
    select * from {{ ref('int_calls__coded') }}
),

agents as (
    select * from {{ ref('stg_agent_mapping') }}
)

select
    date(coded.call_placed_at_local) as call_date_local,
    coded.country_name as market,
    coded.campaign_name,
    coded.agent_ameyo_user_id,
    agents.atlas_user_name as agent_name,
    agents.team as agent_team,
    agents.has_conflicting_source_rows as agent_has_conflicting_mapping,
    count(*) as total_outbound_calls,
    countif(coded.is_coded) as coded_calls,
    safe_divide(countif(coded.is_coded), count(*)) as coding_rate
from coded
left join agents
    on
        coded.country_name = agents.country_name
        and coded.agent_ameyo_user_id = agents.ameyo_user_id
group by all
