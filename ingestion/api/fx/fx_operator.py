"""FxRatesOperator -- the Databricks-facing unit of work for FX rates.

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

from common import fq_table, get_logger, get_raw_dataset, get_adls_client  # noqa: E402
import json
import os

# Prefer the Databricks SQL connector. If unavailable, raise a helpful error.
try:
    from databricks import sql as dbsql  # type: ignore
except Exception:  # pragma: no cover - environment dependent
    dbsql = None

from .hook import (  # noqa: E402
    CURRENCIES,
    ExchangeRateApiHook,
    FxPermanentError,
    FxPlanUpgradeRequired,
    FxTemporaryError,
)

log = get_logger("fx.operator")

FX_RATES_COLUMNS = [
    "rate_date",
    "currency",
    "usd_to_local_rate",
    "rate_is_estimated",
    "rate_source",
    "fetched_at",
]


class DatabricksClientAdapter:
    """Minimal adapter to run the SQL operations fx_operator expects,
    implemented against the databricks-sql-connector.
    """

    def __init__(self):
        if dbsql is None:
            raise RuntimeError(
                "databricks-sql-connector is required for Databricks support."
            )
        self.host = os.environ.get("DATABRICKS_HOST")
        self.http_path = os.environ.get("DATABRICKS_HTTP_PATH")
        self.token = os.environ.get("DATABRICKS_TOKEN")
        if not all((self.host, self.http_path, self.token)):
            raise RuntimeError("DATABRICKS_HOST, DATABRICKS_HTTP_PATH and DATABRICKS_TOKEN must be set in the environment")

    def _execute(self, sql: str):
        with dbsql.connect(server_hostname=self.host, http_path=self.http_path, access_token=self.token) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                try:
                    cols = [c[0] for c in cur.description] if cur.description else []
                    rows = cur.fetchall()
                    return [dict(zip(cols, r)) for r in rows]
                except Exception:
                    return []

    def create_table_if_not_exists(self, fq_table_name: str):
        # Create a simple table with the expected columns if it doesn't exist.
        sql = f"""
        CREATE TABLE IF NOT EXISTS {fq_table_name} (
            rate_date DATE,
            currency STRING,
            usd_to_local_rate DOUBLE,
            rate_is_estimated BOOLEAN,
            rate_source STRING,
            fetched_at TIMESTAMP
        )
        USING DELTA
        """
        self._execute(sql)

    def query(self, sql: str):
        return self._execute(sql)

    def run_merge(self, target: str, source_select_sql: str):
        merge_sql = f"""
        MERGE INTO {target} T
        USING ({source_select_sql}) S
        ON T.rate_date = S.rate_date AND T.currency = S.currency
        WHEN MATCHED THEN UPDATE SET
            usd_to_local_rate = S.usd_to_local_rate,
            rate_is_estimated = S.rate_is_estimated,
            rate_source = S.rate_source,
            fetched_at = S.fetched_at
        WHEN NOT MATCHED THEN INSERT ({', '.join(FX_RATES_COLUMNS)})
        VALUES ({', '.join('S.' + c for c in FX_RATES_COLUMNS)})
        """
        self._execute(merge_sql)

    def drop_table_if_exists(self, fq_table_name: str):
        self._execute(f"DROP TABLE IF EXISTS {fq_table_name}")


class FxRatesOperator:
    def __init__(self, hook: ExchangeRateApiHook | None, client: object | None = None):
        self.hook = hook
        self.client = client or DatabricksClientAdapter()
        # Ensure the target table exists so downstream queries don't fail.
        self.client.create_table_if_not_exists(fq_table(get_raw_dataset(), "fx_rates"))

    def get_needed_dates(self) -> list[date]:
        query = f"SELECT DISTINCT CAST(pay_timestamp_utc AS DATE) AS d FROM {fq_table(get_raw_dataset(), 'payments')} WHERE pay_timestamp_utc IS NOT NULL ORDER BY d"
        return [row["d"] for row in self.client.query(query)]

    def get_cached_pairs(self) -> set[tuple[date, str]]:
        query = f"SELECT rate_date, currency FROM {fq_table(get_raw_dataset(), 'fx_rates')}"
        return {(row["rate_date"], row["currency"]) for row in self.client.query(query)}

    def upsert_rates(self, rows: list[dict]) -> None:
        if not rows:
            return
        stage_table = fq_table(get_raw_dataset(), "_stg_fx_rates")
        target = fq_table(get_raw_dataset(), "fx_rates")

        # Build a SELECT ... UNION ALL ... source for the MERGE statement.
        selects = []
        for r in rows:
            # rate_date needs to be a DATE literal, fetched_at as TIMESTAMP literal
            rd = r["rate_date"]
            fa = r["fetched_at"]
            usd = r["usd_to_local_rate"]
            est = 'TRUE' if r["rate_is_estimated"] else 'FALSE'
            src = r["rate_source"].replace("'", "''")
            cur = r["currency"]
            selects.append(
                f"SELECT DATE('{rd}') AS rate_date, '{cur}' AS currency, {usd} AS usd_to_local_rate, {est} AS rate_is_estimated, '{src}' AS rate_source, TIMESTAMP('{fa}') AS fetched_at"
            )

        source_select_sql = "\nUNION ALL\n".join(selects)

        # Run merge into target
        self.client.run_merge(target, source_select_sql)

        # Also persist the raw fetched rows to ADLS Gen2 as JSON for audit/backup
        try:
            self._write_rows_to_adls(rows)
        except Exception:
            log.exception("Failed to write fx rows to ADLS; continuing")

        # Clean up any staging table if used (no persistent stage used here)
        self.client.drop_table_if_exists(stage_table)

    def _write_rows_to_adls(self, rows: list[dict]) -> None:
        # Group rows by rate_date and write one file per date
        client = get_adls_client()
        container = os.environ.get("AZURE_CONTAINER_NAME", "raw-data")
        from azure.storage.blob import BlobClient

        by_date: dict[str, list[dict]] = {}
        for r in rows:
            by_date.setdefault(r["rate_date"], []).append(r)

        for date_str, recs in by_date.items():
            # Blob path: fx_rates/YYYY/MM/DD/fx_rates_<date>_<timestamp>.json
            y, m, d = date_str.split("-")
            blob_path = f"fx_rates/{y}/{m}/{d}/fx_rates_{date_str}.json"
            blob = client.get_blob_client(container=container, blob=blob_path)
            payload = json.dumps(recs, default=str)
            blob.upload_blob(payload, overwrite=True)

    def execute(self) -> dict:
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
                    "fx: historical endpoint unavailable on this plan for %s; falling back to latest rate (flagged as estimated)",
                    day,
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
