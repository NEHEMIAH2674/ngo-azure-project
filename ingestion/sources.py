"""Declarative registry of the four raw sources: expected columns, BigQuery
schema, and each source's natural (or synthetic) key.

`key_columns` is documentation, not behavior: the loader itself is
idempotent at the whole-file-hash level, not by key (see the "Idempotency
strategy" note at the top of load_csv_to_bq.py for why key-based MERGE was
tried and rejected). What each source's real-world identity actually is
stays true and worth recording regardless -- readers of this file get it
at a glance, and it's what dbt staging's own dedup logic (e.g.
stg_atlas__payments.sql, partitioning by payment_row_key) is built on.

Every business column lands as STRING, exactly as it appears in the CSV --
no type casting, no trimming, no "" -> NULL conversion happens here. Raw is
raw: what arrived is what you'll see in raw.*, byte-for-byte. All typing
(INT64/TIMESTAMP/etc.), trimming, and NULL-handling is deferred to the dbt
staging layer, where transformation is supposed to happen. load_csv_to_bq.py
adds two pipeline-metadata columns (_source_file, _ingested_at) on top of
each schema below -- those describe the load, not the source data, so they
live outside this file.

Adding "tomorrow's file" means dropping a new CSV with one of these
filenames into --input-dir; nothing here needs to change for that case.
Adding a genuinely new *source* means adding one entry to SOURCES.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from google.cloud import bigquery


@dataclass(frozen=True)
class Source:
    name: str  # -> raw table name
    filename: str  # expected CSV filename under --input-dir
    columns: list[str]  # expected CSV header, in order (also validates the file)
    schema: list[bigquery.SchemaField]  # all STRING; see module docstring
    key_columns: list[str]  # this source's natural/synthetic key (docs only -- see module docstring)
    # Optional per-row transform, e.g. to compute a synthetic key. Receives
    # the raw dict of strings from csv parsing, returns the dict to load.
    # Must not alter the values of real source columns -- only add columns.
    transform_row: Callable[[dict], dict] = field(default=lambda row: row)


def _synthetic_payment_key(row: dict) -> dict:
    # A hash of the row's own (untouched) string values -- not a value
    # judgment, just a stable identifier for a payment that has no natural
    # id in the source system. The loader doesn't use it for anything
    # (loading is append-only, gated by file hash, not by key -- see
    # load_csv_to_bq.py); it's carried through raw.payments so dbt staging
    # can partition on it to collapse exact-duplicate transmissions
    # (see stg_atlas__payments.sql).
    raw = "|".join(
        str(row.get(c, "")) for c in
        ["pay_timestamp_utc", "tenant_id", "contract_id",
         "payment_request_provider", "create_program", "amount"]
    )
    row["_payment_row_key"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return row


AMEYO_CALLS = Source(
    name="ameyo_calls",
    filename="Outbound Calls Ameyo.csv",
    columns=[
        "ch_call_id", "ch_date_added", "ch_contact_center_id",
        "ch_system_disposition", "ch_call_type", "total_talk_time",
        "udh_user_id", "campaign_name", "udh_notes",
    ],
    schema=[bigquery.SchemaField(c, "STRING") for c in [
        "ch_call_id", "ch_date_added", "ch_contact_center_id",
        "ch_system_disposition", "ch_call_type", "total_talk_time",
        "udh_user_id", "campaign_name", "udh_notes",
    ]],
    key_columns=["ch_call_id"],
)

ATLAS_DISPOSITIONS = Source(
    name="atlas_dispositions",
    filename="Calls Dispositions Atlas.csv",
    columns=[
        "call_log_id", "tenant_id", "customer_id", "contract_id",
        "created_timestamp_utc", "createdby", "call_type",
        "level_one", "level_two", "level_three",
    ],
    schema=[bigquery.SchemaField(c, "STRING") for c in [
        "call_log_id", "tenant_id", "customer_id", "contract_id",
        "created_timestamp_utc", "createdby", "call_type",
        "level_one", "level_two", "level_three",
    ]],
    key_columns=["call_log_id"],
)

PAYMENTS = Source(
    name="payments",
    filename="Payments Data Atlas.csv",
    columns=[
        "pay_timestamp_utc", "tenant_id", "contract_id",
        "payment_request_provider", "create_program", "amount",
    ],
    schema=[bigquery.SchemaField(c, "STRING") for c in [
        "pay_timestamp_utc", "tenant_id", "contract_id",
        "payment_request_provider", "create_program", "amount",
        "_payment_row_key",
    ]],
    key_columns=["_payment_row_key"],
    transform_row=_synthetic_payment_key,
)

AGENT_MAPPING = Source(
    name="agent_mapping",
    filename="Atlas Ameyo Mapping.csv",
    columns=["contact_centre", "ameyo_user_id", "team", "atlas_user_name"],
    schema=[bigquery.SchemaField(c, "STRING") for c in
            ["contact_centre", "ameyo_user_id", "team", "atlas_user_name"]],
    key_columns=["contact_centre", "ameyo_user_id"],
)

SOURCES: list[Source] = [AMEYO_CALLS, ATLAS_DISPOSITIONS, PAYMENTS, AGENT_MAPPING]
