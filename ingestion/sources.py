"""Declarative registry of the four raw sources: expected columns and natural keys.

Every business column lands as STRING exactly as it appears in the raw CSV.
Row transformation logic (such as computing _payment_row_key) is kept intact
so downstream processors (dbt/Databricks) can utilize identical partition keys.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Source:
    name: str  # ADLS Gen2 target folder name
    filename: str  # Expected CSV filename in input directory
    columns: list[str]  # Expected CSV header in exact order
    key_columns: list[str]  # Natural or synthetic key (for documentation/downstream deduplication)
    transform_row: Callable[[dict], dict] = field(default=lambda row: row)


def _synthetic_payment_key(row: dict) -> dict:
    """Computes SHA-256 synthetic hash for payments missing natural primary keys."""
    raw = "|".join(
        str(row.get(c, ""))
        for c in [
            "pay_timestamp_utc",
            "tenant_id",
            "contract_id",
            "payment_request_provider",
            "create_program",
            "amount",
        ]
    )
    row["_payment_row_key"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return row


AMEYO_CALLS = Source(
    name="ameyo_calls",
    filename="Outbound Calls Ameyo.csv",
    columns=[
        "ch_call_id",
        "ch_date_added",
        "ch_contact_center_id",
        "ch_system_disposition",
        "ch_call_type",
        "total_talk_time",
        "udh_user_id",
        "campaign_name",
        "udh_notes",
    ],
    key_columns=["ch_call_id"],
)

ATLAS_DISPOSITIONS = Source(
    name="atlas_dispositions",
    filename="Calls Dispositions Atlas.csv",
    columns=[
        "call_log_id",
        "tenant_id",
        "customer_id",
        "contract_id",
        "created_timestamp_utc",
        "createdby",
        "call_type",
        "level_one",
        "level_two",
        "level_three",
    ],
    key_columns=["call_log_id"],
)

PAYMENTS = Source(
    name="payments",
    filename="Payments Data Atlas.csv",
    columns=[
        "pay_timestamp_utc",
        "tenant_id",
        "contract_id",
        "payment_request_provider",
        "create_program",
        "amount",
    ],
    key_columns=["_payment_row_key"],
    transform_row=_synthetic_payment_key,
)

AGENT_MAPPING = Source(
    name="agent_mapping",
    filename="Atlas Ameyo Mapping.csv",
    columns=["contact_centre", "ameyo_user_id", "team", "atlas_user_name"],
    key_columns=["contact_centre", "ameyo_user_id"],
)

SOURCES: list[Source] = [AMEYO_CALLS, ATLAS_DISPOSITIONS, PAYMENTS, AGENT_MAPPING]