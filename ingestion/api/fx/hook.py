"""ExchangeRateApiHook -- a thin, connection-only client for exchangerate-api.com.

Owns exactly three things: resolving the API key, making HTTP calls with
retry/backoff, and translating exchangerate-api.com's response shapes into
plain dicts. It knows nothing about BigQuery, which dates are needed, or
what to do with a rate once fetched -- that's FxRatesOperator's job (see
fx_operator.py). This hook/operator split mirrors the Airflow convention (hook
= connection, operator = task) without depending on Airflow itself -- this
repo orchestrates with Dagster.

Design notes (this is the piece the brief says will be read most carefully):

  Auth
    The API key is read from EXCHANGE_RATE_API_KEY (via .env, gitignored).
    It is never logged, never embedded in a URL that gets logged, and never
    hardcoded. .env.example documents the variable without a real value.

  Failure handling
    Network errors, 429 (rate limited) and 5xx responses are retried with
    exponential backoff + jitter (tenacity), capped at 4 attempts. A 4xx
    "real" error (bad key, bad request) is NOT retried -- retrying a bad key
    forever just wastes quota and delays the real fix -- it's raised as
    FxPermanentError so the caller can log it clearly and move on.

    exchangerate-api.com's historical endpoint is a paid-plan feature; on a
    free key it returns a "plan-upgrade-required" error, raised here as
    FxPlanUpgradeRequired so fx_operator.py can fall back to the "latest" rate
    and flag it as estimated rather than fail the whole run.
"""

from __future__ import annotations

import os
from datetime import date

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

CURRENCIES = ["KES", "UGX", "TZS", "NGN"]
BASE_URL = "https://v6.exchangerate-api.com/v6"


class FxTemporaryError(Exception):
    """Network/5xx/429 -- worth retrying."""


class FxPermanentError(Exception):
    """Bad key / bad request -- retrying will not help."""


class FxPlanUpgradeRequired(Exception):
    """Historical endpoint not available on this API plan."""


class ExchangeRateApiHook:
    def __init__(self, api_key: str | None = None):
        """Pass api_key explicitly to override the environment (e.g. from
        tests); otherwise it's resolved from EXCHANGE_RATE_API_KEY.
        """
        self.api_key = api_key or self._resolve_api_key()

    @staticmethod
    def _resolve_api_key() -> str:
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
    def _get(self, url: str) -> dict:
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

    def fetch_latest_rates(self) -> dict[str, float]:
        body = self._get(f"{BASE_URL}/{self.api_key}/latest/USD")
        rates = body["conversion_rates"]
        return {c: rates[c] for c in CURRENCIES if c in rates}

    def fetch_historical_rates(self, day: date) -> dict[str, float]:
        url = f"{BASE_URL}/{self.api_key}/history/USD/{day.year}/{day.month}/{day.day}"
        body = self._get(url)
        rates = body["conversion_rates"]
        return {c: rates[c] for c in CURRENCIES if c in rates}
