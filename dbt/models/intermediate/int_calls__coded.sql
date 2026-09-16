-- Grain: 1 row per Ameyo call leg (same grain as stg_ameyo__calls), with
-- is_coded and the matched Atlas call_log_id (if any) appended.
--
-- "Coded" per the brief: the agent wrote a valid Atlas call_log_id into the
-- Ameyo notes field, AND that id exists in the Atlas dispositions data.
--
-- udh_notes is free text, not a structured id field: alongside genuine
-- numeric call_log_ids it also contains prose, phone numbers, and junk
-- ("silence", "hung up", "254757421943 254757421943"). Rather than guess a
-- digit-length pattern to tell a call_log_id apart from a phone number
-- (fragile -- both are just runs of digits), every digit run in the notes
-- is extracted as a *candidate* and checked for actual existence in Atlas.
-- A phone number will essentially never collide with a real call_log_id by
-- chance, so this is both simpler and more robust than a length heuristic.
--
-- If a note contains more than one digit run that matches a real
-- call_log_id (not observed in this extract, but possible), the smallest
-- matching value is taken deterministically so the result is reproducible.

with calls as (
    select * from {{ ref('stg_ameyo__calls') }}
),

real_call_log_ids as (
    select distinct call_log_id
    from {{ ref('stg_atlas__dispositions') }}
    where call_log_id is not null
),

candidates as (
    select
        c.call_id,
        try_cast(candidate as BIGINT) as candidate_call_log_id
    from calls as c
    lateral view explode(split(regexp_replace(coalesce(c.notes_raw, ''), '[^0-9]+', ' '), ' ')) exploded as candidate
    where c.notes_raw is not null and candidate != ''
),

matched as (
    select
        candidates.call_id,
        min(candidates.candidate_call_log_id) as matched_call_log_id
    from candidates
    inner join real_call_log_ids
        on candidates.candidate_call_log_id = real_call_log_ids.call_log_id
    group by candidates.call_id
)

select
    c.*,
    m.matched_call_log_id,
    m.matched_call_log_id is not null as is_coded
from calls as c
left join matched as m on c.call_id = m.call_id
