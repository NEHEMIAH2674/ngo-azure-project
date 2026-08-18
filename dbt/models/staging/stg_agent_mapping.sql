-- Grain: 1 row per agent, i.e. per (country_name, ameyo_user_id).
--
-- Two data-quality issues in the source, handled explicitly:
--
-- 1. ~8 physical CSV lines are a lone `"` character on its own line (a
--    quoting artifact absorbed into the previous row's atlas_user_name as
--    an embedded newline). Those rows carry no ameyo_user_id and are
--    excluded here -- they were never a real agent record.
--
-- 2. 29 agents (out of ~1,600) have genuinely conflicting duplicate rows:
--    different team and/or atlas_user_name for the exact same
--    (country_name, ameyo_user_id), e.g. Kenya/Joseph.Ojungu appears once
--    as team=Attrition and separately as team=Upsell. The source has no
--    timestamp or effective-date column, so there is no way to determine
--    which row is current from the data alone -- this is a genuine
--    upstream gap, not something we can cleanly resolve (see WRITEUP.md).
--    We deterministically keep one row per agent (preferring a non-blank
--    name, then an alphabetically-last tie-break, purely for
--    reproducibility) and flag every affected agent via
--    has_conflicting_source_rows so this never masquerades as clean data
--    downstream. Recommendation to the business: add an updated_at column
--    to this export.

with source as (
    select * from {{ source('dlight_raw', 'agent_mapping') }}
),

typed as (
    select
        {{ clean_string('contact_centre') }} as country_name,
        {{ clean_string('ameyo_user_id') }} as ameyo_user_id,
        {{ clean_string('team') }} as team,
        {{ clean_string('atlas_user_name') }} as atlas_user_name,
        _source_file,
        _ingested_at
    from source
    -- Can't reference the `ameyo_user_id` alias above in this WHERE clause
    -- (WHERE evaluates before SELECT in the same query), so the same
    -- cleanup is necessarily re-expressed here rather than reused --
    -- SQL scoping, not sloppy duplication.
    where {{ clean_string('ameyo_user_id') }} is not null
),

flagged as (
    select
        *,
        count(*) over (partition by country_name, ameyo_user_id) > 1 as has_conflicting_source_rows
    from typed
),

deduped as (
    select
        *,
        row_number() over (
            partition by country_name, ameyo_user_id
            order by
                (atlas_user_name is not null) desc,
                team desc,
                atlas_user_name desc
        ) as _dedup_rank
    from flagged
)

select * except (_dedup_rank)
from deduped
where _dedup_rank = 1
