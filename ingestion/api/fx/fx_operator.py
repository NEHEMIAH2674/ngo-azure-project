"""FxRatesOperator -- the BigQuery-facing unit of work for FX rates.

Named fx_operator.py rather than operator.py to avoid shadowing Python's
own stdlib `operator` module -- see main.py's module docstring for why that
collision is real, not theoretical (it broke on the first live run here).

Given an ExchangeRateApiHook (or None, if no usable key is configured),
figures out which (date, currency) pairs raw.payments actually needs and
raw.fx_rates doesn't have yet, fetches just those, and upserts idempotently.
This is where the exchangerate-api.com-specific business rules live:
falling back to the "latest" rate (flagged estimated) when the historical
endpoint isn't available on the configured plan, and never re-fetching a
pair that's already cached.

Idempotency
    Every (rate_date, currency) pair is looked up before calling the API; a
    pair already cached in raw.fx_rates is skipped. The eventual write is
    also a MERGE keyed on (rate_date, currency), so even a concurrent or
    re-run never duplicates a rate or double-spends API quota.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # ingestion/

from common import fq_table, get_bigquery_client, get_logger, get_raw_dataset  # noqa: E402
from google.cloud import bigquery  # noqa: E402

from .hook import (  # noqa: E402
    CURRENCIES,
    ExchangeRateApiHook,
    FxPermanentError,
    FxPlanUpgradeRequired,
    FxTemporaryError,
)

log = get_logger("fx.operator")

FX_RATES_SCHEMA = [
    bigquery.SchemaField("rate_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("currency", "STRING", mode="REQUIRED"),
    # Units of local currency per 1 USD, e.g. usd_to_local_rate=129.5 for KES
    # means amount_usd = amount_local / 129.5.
    bigquery.SchemaField("usd_to_local_rate", "FLOAT64"),
    bigquery.SchemaField("rate_is_estimated", "BOOL"),
    bigquery.SchemaField("rate_source", "STRING"),
    bigquery.SchemaField("fetched_at", "TIMESTAMP"),
]


class FxRatesOperator:
    def __init__(self, hook: ExchangeRateApiHook | None, client: bigquery.Client | None = None):
        self.hook = hook
        self.client = client or get_bigquery_client()
        # Created regardless of whether we have a usable hook, so
        # downstream dbt staging models always have something to select
        # from (even empty) rather than failing on a missing table -- see
        # WRITEUP.md on the FX gap.
        self.client.create_table(
            bigquery.Table(fq_table(get_raw_dataset(), "fx_rates"), schema=FX_RATES_SCHEMA), exists_ok=True
        )

    def get_needed_dates(self) -> list[date]:
        query = f"""
            SELECT DISTINCT DATE(pay_timestamp_utc) AS d
            FROM `{fq_table(get_raw_dataset(), "payments")}`
            WHERE pay_timestamp_utc IS NOT NULL
            ORDER BY d
        """
        return [row["d"] for row in self.client.query(query).result()]

    def get_cached_pairs(self) -> set[tuple[date, str]]:
        query = f"SELECT rate_date, currency FROM `{fq_table(get_raw_dataset(), 'fx_rates')}`"
        return {(row["rate_date"], row["currency"]) for row in self.client.query(query).result()}

    def upsert_rates(self, rows: list[dict]) -> None:
        if not rows:
            return
        stage_table = fq_table(get_raw_dataset(), "_stg_fx_rates")
        job_config = bigquery.LoadJobConfig(
            schema=FX_RATES_SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
        )
        self.client.load_table_from_json(rows, stage_table, job_config=job_config).result()
        target = fq_table(get_raw_dataset(), "fx_rates")
        self.client.query(f"""
            MERGE `{target}` T
            USING `{stage_table}` S
            ON T.rate_date = S.rate_date AND T.currency = S.currency
            WHEN MATCHED THEN UPDATE SET
                usd_to_local_rate = S.usd_to_local_rate,
                rate_is_estimated = S.rate_is_estimated,
                rate_source = S.rate_source,
                fetched_at = S.fetched_at
            WHEN NOT MATCHED THEN INSERT ({', '.join(f.name for f in FX_RATES_SCHEMA)})
            VALUES ({', '.join('S.' + f.name for f in FX_RATES_SCHEMA)})
        """).result()
        self.client.delete_table(stage_table, not_found_ok=True)

    def execute(self) -> dict:
        """Fetch/cache missing daily FX rates. Returns a status dict so
        callers (main.py, and the Dagster asset in orchestration/) can
        report what happened without re-deriving it, and so a missing key
        or exhausted retries surface as structured status rather than only
        a log line.
        """
        if self.hook is None:
            log.error("FX fetch aborted: no usable API key. Downstream USD figures will be NULL until this is fixed.")
            return {"status": "no_api_key", "rows_upserted": 0, "dates_needed": 0, "dates_failed": 0}

        needed_dates = self.get_needed_dates()
        cached = self.get_cached_pairs()
        missing_dates = [d for d in needed_dates if any((d, c) not in cached for c in CURRENCIES)]

        if not missing_dates:
            log.info("fx: nothing to fetch, all %d payment dates already cached", len(needed_dates))
            return {"status": "up_to_date", "rows_upserted": 0, "dates_needed": len(needed_dates), "dates_failed": 0}

        log.info("fx: %d of %d payment dates need rates", len(missing_dates), len(needed_dates))

        latest_fallback: dict[str, float] | None = None
        rows: list[dict] = []
        dates_failed = 0
        now = datetime.now(timezone.utc).isoformat()

        for day in missing_dates:
            try:
                rates = self.hook.fetch_historical_rates(day)
                source, estimated = "history", False
            except FxPlanUpgradeRequired:
                log.warning(
                    "fx: historical endpoint unavailable on this plan for %s; "
                    "falling back to latest rate (flagged as estimated)", day,
                )
                if latest_fallback is None:
                    try:
                        latest_fallback = self.hook.fetch_latest_rates()
                    except FxPermanentError as exc:
                        log.error("fx: latest-rate fallback also failed for %s: %s", day, exc)
                        dates_failed += 1
                        continue
                rates, source, estimated = latest_fallback, "latest_fallback", True
            except FxPermanentError as exc:
                log.error("fx: giving up on %s: %s", day, exc)
                dates_failed += 1
                continue
            except FxTemporaryError as exc:
                log.error("fx: exhausted retries for %s: %s (will retry on next run)", day, exc)
                dates_failed += 1
                continue

            for currency, rate in rates.items():
                if (day, currency) in cached:
                    continue
                rows.append(
                    {
                        "rate_date": day.isoformat(),
                        "currency": currency,
                        "usd_to_local_rate": rate,
                        "rate_is_estimated": estimated,
                        "rate_source": source,
                        "fetched_at": now,
                    }
                )

        self.upsert_rates(rows)
        log.info("fx: upserted %d (date, currency) rate rows", len(rows))
        return {
            "status": "ok" if dates_failed == 0 else "partial_failure",
            "rows_upserted": len(rows),
            "dates_needed": len(missing_dates),
            "dates_failed": dates_failed,
        }
