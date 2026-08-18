"""Asset checks on the raw ingestion layer: row-count sanity and null-rate
on each source's grain key. These exist so a broken extract (e.g. a future
day's file with a shifted column, or a load that silently produced zero
rows) is visible in the Dagster UI as a check failure attached to the
specific asset, rather than only surfacing three layers downstream as a
confusing dbt test failure or a wrong number on a dashboard.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

import dagster as dg
from common import fq_table, get_bigquery_client, get_raw_dataset

# (asset_name, key_column) -- the column that should never be null for that source.
_KEY_COLUMNS = [
    ("ameyo_calls", "ch_call_id"),
    ("atlas_dispositions", "call_log_id"),
    ("payments", "_payment_row_key"),
    ("agent_mapping", "ameyo_user_id"),
]


def _make_row_count_check(asset_name: str) -> dg.AssetChecksDefinition:
    @dg.asset_check(
        asset=dg.AssetKey(asset_name),
        name="has_rows",
        description=f"raw.{asset_name} must not be empty after a load.",
    )
    def _check() -> dg.AssetCheckResult:
        client = get_bigquery_client()
        table = fq_table(get_raw_dataset(), asset_name)
        n = next(iter(client.query(f"SELECT COUNT(*) AS n FROM `{table}`").result()))["n"]
        return dg.AssetCheckResult(passed=n > 0, metadata={"row_count": n})

    return _check


def _make_null_key_check(asset_name: str, key_column: str) -> dg.AssetChecksDefinition:
    @dg.asset_check(
        asset=dg.AssetKey(asset_name),
        name=f"{key_column}_never_null",
        description=f"raw.{asset_name}.{key_column} is this source's grain key and must never be null.",
    )
    def _check() -> dg.AssetCheckResult:
        client = get_bigquery_client()
        table = fq_table(get_raw_dataset(), asset_name)
        n_null = next(iter(client.query(
            f"SELECT COUNTIF({key_column} IS NULL OR {key_column} = '') AS n FROM `{table}`"
        ).result()))["n"]
        return dg.AssetCheckResult(passed=n_null == 0, metadata={"null_count": n_null})

    return _check


@dg.asset_check(
    asset=dg.AssetKey("fx_rates"),
    name="covers_all_payment_dates",
    description=(
        "Every (date, currency) pair present in raw.payments should have a "
        "matching fx_rates row. WARN (not fail) since this is expected to be "
        "unmet until a real EXCHANGE_RATE_API_KEY is configured -- see "
        "ingestion/fetch_fx_rates.py."
    ),
)
def fx_rates_covers_all_payment_dates() -> dg.AssetCheckResult:
    client = get_bigquery_client()
    payments_table = fq_table(get_raw_dataset(), "payments")
    fx_table = fq_table(get_raw_dataset(), "fx_rates")
    missing = next(iter(client.query(f"""
        SELECT COUNT(*) AS n FROM (
            SELECT DISTINCT DATE(SAFE_CAST(pay_timestamp_utc AS TIMESTAMP)) AS d
            FROM `{payments_table}`
            WHERE pay_timestamp_utc IS NOT NULL
        ) p
        LEFT JOIN (SELECT DISTINCT rate_date FROM `{fx_table}`) f
            ON p.d = f.rate_date
        WHERE f.rate_date IS NULL
    """).result()))["n"]
    return dg.AssetCheckResult(
        passed=missing == 0,
        severity=dg.AssetCheckSeverity.WARN,
        metadata={"payment_dates_missing_a_rate": missing},
    )


raw_ingestion_checks = (
    [_make_row_count_check(name) for name, _ in _KEY_COLUMNS]
    + [_make_null_key_check(name, col) for name, col in _KEY_COLUMNS]
    + [fx_rates_covers_all_payment_dates]
)
