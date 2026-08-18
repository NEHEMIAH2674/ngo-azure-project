-- Grain: 1 row per Ameyo call leg (ch_call_id), matching the raw source
-- exactly except: typed columns, blank-string -> NULL, and a UTC timestamp
-- derived from the source's local-time field via the country seed's fixed
-- offset (Kenya/Uganda/Tanzania = EAT = UTC+3, Nigeria = WAT = UTC+1; none
-- observe DST, so a static offset is safe -- see WRITEUP.md).
--
-- Deliberately NOT deduplicated here: raw.ameyo_calls has no genuine
-- duplicate ch_call_id in this extract. A naive line-based scan of the CSV
-- (splitting on commas without respecting quoting) appears to show one, but
-- that's a false positive: it's a lone `"` character sitting alone on its
-- own physical line, which a spec-correct CSV parser (what ingestion uses)
-- absorbs as an embedded newline inside the adjacent row's last field --
-- the same artifact confirmed in Atlas Ameyo Mapping.csv. Ingestion already
-- parsed this file correctly (10,508 valid rows, 0 rejected), so no
-- filtering for it is needed here.

with source as (
    select * from {{ source('dlight_raw', 'ameyo_calls') }}
),

typed as (
    select
        ch_call_id as call_id,
        nullif(trim(udh_user_id), '') as agent_ameyo_user_id,
        nullif(trim(campaign_name), '') as campaign_name,
        nullif(trim(ch_call_type), '') as call_dial_type,
        nullif(trim(ch_system_disposition), '') as system_disposition,
        safe_cast(ch_contact_center_id as int64) as ameyo_contact_center_id,
        safe_cast(total_talk_time as float64) as total_talk_time_ms,
        nullif(trim(udh_notes), '') as notes_raw,
        safe_cast(ch_date_added as datetime) as call_placed_at_local,
        _source_file,
        _ingested_at
    from source
)

select
    t.*,
    c.country_name,
    c.atlas_tenant_id,
    c.currency_code,
    timestamp_sub(
        timestamp(t.call_placed_at_local),
        interval c.local_tz_offset_hours hour
    ) as call_placed_at_utc
from typed t
left join {{ ref('country_code_mapping') }} c
    on t.ameyo_contact_center_id = c.ameyo_contact_center_id
