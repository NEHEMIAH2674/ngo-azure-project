import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_fx_rates as fx


class _FakeResponse:
    def __init__(self, status_code, json_body, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {"content-type": "application/json"}
        self.text = str(json_body)

    def json(self):
        return self._json_body


def test_get_retries_on_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(503, {})
        return _FakeResponse(200, {"result": "success", "conversion_rates": {"KES": 129.5}})

    monkeypatch.setattr(fx.requests, "get", fake_get)
    body = fx._get("http://example.invalid")

    assert calls["n"] == 3
    assert body["conversion_rates"]["KES"] == 129.5


def test_get_raises_permanent_error_on_bad_key_without_retrying(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout):
        calls["n"] += 1
        return _FakeResponse(403, {"result": "error", "error-type": "invalid-key"})

    monkeypatch.setattr(fx.requests, "get", fake_get)

    with pytest.raises(fx.FxPermanentError):
        fx._get("http://example.invalid")

    assert calls["n"] == 1  # no retrying a bad key


def test_get_raises_plan_upgrade_required_distinctly(monkeypatch):
    def fake_get(url, timeout):
        return _FakeResponse(403, {"result": "error", "error-type": "plan-upgrade-required"})

    monkeypatch.setattr(fx.requests, "get", fake_get)

    with pytest.raises(fx.FxPlanUpgradeRequired):
        fx._get("http://example.invalid")
