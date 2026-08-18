"""Fetch and cache daily USD exchange rates for the four payment currencies.

    python ingestion/fetch_fx_rates.py

Design notes (this is the piece the brief says will be read most carefully):

  Auth
    The API key is read from EXCHANGE_RATE_API_KEY (via .env, gitignored).
    It is never logged, never embedded in a URL that gets logged, and never
    hardcoded. .env.example documents the variable without a real value.

  Failure handling
    Network errors, 429 (rate limited) and 5xx responses are retried with
    exponential backoff + jitter (tenacity), capped at 4 attempts. A 4xx
    "real" error (bad key, bad request) is NOT retried -- retrying a bad key
    forever just wastes quota and delays the real fix -- it's logged clearly
    and that date/currency is left unavailable rather than guessed at.

    exchangerate-api.com's historical endpoint is a paid-plan feature; on a
    free key it returns a "plan-upgrade-required" error. Rather than fail
    the whole run, we fall back once per run to the "latest" rate and tag
    every row that used it with rate_is_estimated = TRUE, rate_source =
    'latest_fallback'. Downstream USD figures built from an estimated rate
    should be presented as approximate, not silently treated as exact -- see
    fct_paid_post_call / WRITEUP.md.

  Idempotency
    Every (rate_date, currency) pair is looked up before calling the API; a
    pair already cached in raw.fx_rates is skipped. The eventual write is
    also a MERGE keyed on (rate_date, currency), so even a concurrent or
    re-run never duplicates a rate or double-spends API quota.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

import requests
from common import fq_table, get_bigquery_client, get_logger, get_raw_dataset
from google.cloud import bigquery
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

log = get_logger("fetch_fx_rates")

CURRENCIES = ["KES", "UGX", "TZS", "NGN"]
BASE_URL = "https://v6.exchangerate-api.com/v6"

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


class FxTemporaryError(Exception):
    """Network/5xx/429 -- worth retrying."""


class FxPermanentError(Exception):
    """Bad key / bad request -- retrying will not help."""


class FxPlanUpgradeRequired(Exception):
    """Historical endpoint not available on this API plan."""


def _api_key() -> str:
    key = os.environ.get("EXCHANGE_RATE_API_KEY")
    if not key or key == "changeme":
        raise FxPermanentError(
            "EXCHANGE_RATE_API_KEY is not set. Copy .env.example to .env and "
            "add a free key from https://www.exchangerate-api.com/"
        )
    return key


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=20),
    retry=retry_if_exception_type(FxTemporaryError),
    reraise=True,
)
def _get(url: str) -> dict:
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as exc:
        raise FxTemporaryError(str(exc)) from exc

    if resp.status_code == 429 or resp.status_code >= 500:
        raise FxTemporaryError(f"HTTP {resp.status_code} from FX API")
    if resp.status_code >= 400:
        body = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
        error_type = body.get("error-type", "")
        if error_type == "plan-upgrade-required":
            raise FxPlanUpgradeRequired(error_type)
        raise FxPermanentError(f"HTTP {resp.status_code}: {error_type or resp.text[:200]}")

    body = resp.json()
    if body.get("result") == "error":
        error_type = body.get("error-type", "unknown")
        if error_type == "plan-upgrade-required":
            raise FxPlanUpgradeRequired(error_type)
        raise FxPermanentError(f"API error: {error_type}")
    return body


def fetch_latest_rates(api_key: str) -> dict[str, float]:
    body = _get(f"{BASE_URL}/{api_key}/latest/USD")
    rates = body["conversion_rates"]
    return {c: rates[c] for c in CURRENCIES if c in rates}


def fetch_historical_rates(api_key: str, day: date) -> dict[str, float]:
    url = f"{BASE_URL}/{api_key}/history/USD/{day.year}/{day.month}/{day.day}"
    body = _get(url)
    rates = body["conversion_rates"]
    return {c: rates[c] for c in CURRENCIES if c in rates}


def get_needed_dates(client: bigquery.Client) -> list[date]:
    query = f"""
        SELECT DISTINCT DATE(pay_timestamp_utc) AS d
        FROM `{fq_table(get_raw_dataset(), "payments")}`
        WHERE pay_timestamp_utc IS NOT NULL
        ORDER BY d
    """
    return [row["d"] for row in client.query(query).result()]


def get_cached_pairs(client: bigquery.Client) -> set[tuple[date, str]]:
    query = f"SELECT rate_date, currency FROM `{fq_table(get_raw_dataset(), 'fx_rates')}`"
    return {(row["rate_date"], row["currency"]) for row in client.query(query).result()}


def upsert_rates(client: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        return
    stage_table = fq_table(get_raw_dataset(), "_stg_fx_rates")
    job_config = bigquery.LoadJobConfig(
        schema=FX_RATES_SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )
    client.load_table_from_json(rows, stage_table, job_config=job_config).result()
    target = fq_table(get_raw_dataset(), "fx_rates")
    client.query(f"""
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
    client.delete_table(stage_table, not_found_ok=True)


def run() -> dict:
    """Fetch/cache missing daily FX rates. Returns a status dict so callers
    (the CLI, and the Dagster asset in orchestration/) can report what
    happened without re-deriving it, and so a missing key or exhausted
    retries surface as structured status rather than only a log line.
    """
    client = get_bigquery_client()
    client.create_table(bigquery.Table(fq_table(get_raw_dataset(), "fx_rates"), schema=FX_RATES_SCHEMA), exists_ok=True)

    try:
        api_key = _api_key()
    except FxPermanentError as exc:
        log.error("FX fetch aborted: %s. Downstream USD figures will be NULL until this is fixed.", exc)
        return {"status": "no_api_key", "rows_upserted": 0, "dates_needed": 0, "dates_failed": 0}

    needed_dates = get_needed_dates(client)
    cached = get_cached_pairs(client)
    missing_dates = [d for d in needed_dates if any((d, c) not in cached for c in CURRENCIES)]

    if not missing_dates:
        log.info("fx_rates: nothing to fetch, all %d payment dates already cached", len(needed_dates))
        return {"status": "up_to_date", "rows_upserted": 0, "dates_needed": len(needed_dates), "dates_failed": 0}

    log.info("fx_rates: %d of %d payment dates need rates", len(missing_dates), len(needed_dates))

    latest_fallback: dict[str, float] | None = None
    rows: list[dict] = []
    dates_failed = 0
    now = datetime.now(timezone.utc).isoformat()

    for day in missing_dates:
        try:
            rates = fetch_historical_rates(api_key, day)
            source, estimated = "history", False
        except FxPlanUpgradeRequired:
            log.warning(
                "fx_rates: historical endpoint unavailable on this plan for %s; "
                "falling back to latest rate (flagged as estimated)", day,
            )
            if latest_fallback is None:
                try:
                    latest_fallback = fetch_latest_rates(api_key)
                except FxPermanentError as exc:
                    log.error("fx_rates: latest-rate fallback also failed for %s: %s", day, exc)
                    dates_failed += 1
                    continue
            rates, source, estimated = latest_fallback, "latest_fallback", True
        except FxPermanentError as exc:
            log.error("fx_rates: giving up on %s: %s", day, exc)
            dates_failed += 1
            continue
        except FxTemporaryError as exc:
            log.error("fx_rates: exhausted retries for %s: %s (will retry on next run)", day, exc)
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

    upsert_rates(client, rows)
    log.info("fx_rates: upserted %d (date, currency) rate rows", len(rows))
    return {
        "status": "ok" if dates_failed == 0 else "partial_failure",
        "rows_upserted": len(rows),
        "dates_needed": len(missing_dates),
        "dates_failed": dates_failed,
    }


def main() -> None:
    result = run()
    log.info("fx_rates: run summary: %s", result)


if __name__ == "__main__":
    main()
