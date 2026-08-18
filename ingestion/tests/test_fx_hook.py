import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # ingestion/

from api.fx import hook as fx  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, json_body, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {"content-type": "application/json"}
        self.text = str(json_body)

    def json(self):
        return self._json_body


def _hook():
    # api_key passed explicitly so these tests don't depend on the
    # environment having (or not having) EXCHANGE_RATE_API_KEY set.
    return fx.ExchangeRateApiHook(api_key="test-key")


def test_get_retries_on_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(503, {})
        return _FakeResponse(200, {"result": "success", "conversion_rates": {"KES": 129.5}})

    monkeypatch.setattr(fx.requests, "get", fake_get)
    body = _hook()._get("http://example.invalid")

    assert calls["n"] == 3
    assert body["conversion_rates"]["KES"] == 129.5


def test_get_raises_permanent_error_on_bad_key_without_retrying(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout):
        calls["n"] += 1
        return _FakeResponse(403, {"result": "error", "error-type": "invalid-key"})

    monkeypatch.setattr(fx.requests, "get", fake_get)

    with pytest.raises(fx.FxPermanentError):
        _hook()._get("http://example.invalid")

    assert calls["n"] == 1  # no retrying a bad key


def test_get_raises_plan_upgrade_required_distinctly(monkeypatch):
    def fake_get(url, timeout):
        return _FakeResponse(403, {"result": "error", "error-type": "plan-upgrade-required"})

    monkeypatch.setattr(fx.requests, "get", fake_get)

    with pytest.raises(fx.FxPlanUpgradeRequired):
        _hook()._get("http://example.invalid")


def test_resolve_api_key_rejects_missing_or_placeholder(monkeypatch):
    monkeypatch.delenv("EXCHANGE_RATE_API_KEY", raising=False)
    with pytest.raises(fx.FxPermanentError):
        fx.ExchangeRateApiHook()

    monkeypatch.setenv("EXCHANGE_RATE_API_KEY", "changeme")
    with pytest.raises(fx.FxPermanentError):
        fx.ExchangeRateApiHook()

    monkeypatch.setenv("EXCHANGE_RATE_API_KEY", "a-real-looking-key")
    assert fx.ExchangeRateApiHook().api_key == "a-real-looking-key"
