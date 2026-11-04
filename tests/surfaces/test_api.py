"""API tests use FixtureResolver only — no real network."""
from __future__ import annotations

import pytest
from evals.fixtures import CASES
from fastapi.testclient import TestClient

from setup_doctor.dns.resolver import FixtureResolver, ResolverError
from setup_doctor.surfaces.api import (
    _RateLimiter,
    _ResponseCache,
    create_app,
    validate_hostname,
)

CLEAN = next(c for c in CASES if c["name"] == "clean")
MESS = next(c for c in CASES if c["name"] == "worst_case_combo")


def _client(records: dict, **kwargs) -> TestClient:
    app = create_app(resolver_factory=lambda: FixtureResolver(records), **kwargs)
    return TestClient(app)


@pytest.mark.parametrize(
    "raw",
    [
        "https://evil.example/path",
        "example.com/path",
        "user@example.com",
        "127.0.0.1",
        "::1",
        "[::1]",
        "localhost",
        "foo.localhost",
        "printer.local",
        "db.internal",
        "intranet.corp",
        "singlelabel",
        "example.com:443",
        "a" * 300,
        "exa mple.com",
    ],
)
def test_validate_hostname_rejects_unsafe_input(raw):
    with pytest.raises(ValueError):
        validate_hostname(raw)


def test_validate_hostname_accepts_public_fqdn():
    assert validate_hostname("  Mail.Example.COM. ") == "mail.example.com"
    assert validate_hostname("clean.test") == "clean.test"


def test_diagnose_returns_findings_and_report():
    client = _client(MESS["records"])
    r = client.post("/diagnose", json={"domain": MESS["domain"]})
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "1.0"
    assert body["domain"] == MESS["domain"]
    assert {f["id"] for f in body["findings"]} == set(MESS["expected"])
    assert "Setup Doctor report" in body["report"]
    assert body["explanation_source"] in ("template", "model_verified", "template_fallback")
    assert body["cached"] is False


def test_diagnose_clean_domain():
    client = _client(CLEAN["records"])
    r = client.post("/diagnose", json={"domain": CLEAN["domain"]})
    assert r.status_code == 200
    assert r.json()["findings"] == []


@pytest.mark.parametrize("domain", ["127.0.0.1", "localhost", "https://x.test", "x.local"])
def test_diagnose_rejects_bad_hosts_with_400(domain):
    client = _client(CLEAN["records"])
    r = client.post("/diagnose", json={"domain": domain})
    assert r.status_code == 400
    assert "findings" not in r.json()


def test_diagnose_resolver_error_is_502_not_a_fake_diagnosis():
    class Boom:
        def txt(self, name):
            raise ResolverError("timeout")

        def mx(self, name):
            raise ResolverError("timeout")

        def a(self, name):
            raise ResolverError("timeout")

    app = create_app(resolver_factory=lambda: Boom())
    r = TestClient(app).post("/diagnose", json={"domain": "example.com"})
    assert r.status_code == 502
    detail = r.json()["detail"].lower()
    assert "outage" in detail or "resolver" in detail
    assert "findings" not in r.json()


def test_rate_limit_returns_429():
    limiter = _RateLimiter(limit=2, window=60.0)
    client = _client(CLEAN["records"], rate_limiter=limiter)
    assert client.post("/diagnose", json={"domain": CLEAN["domain"]}).status_code == 200
    assert client.post("/diagnose", json={"domain": CLEAN["domain"]}).status_code == 200
    # Cache may satisfy the second call without consuming... actually both go through
    # rate limiter before cache. Third should 429.
    # Clear cache effect: first two may be cache hit on second — still counted by limiter.
    r = client.post("/diagnose", json={"domain": "other.test"})
    # other.test not in CLEAN records → still runs diagnose with empty-ish DNS via fixture
    # Rate limit key is IP; third request should fail.
    assert r.status_code == 429


def test_response_cache_sets_cached_flag():
    cache = _ResponseCache(ttl=60.0, max_entries=8)
    client = _client(CLEAN["records"], cache=cache)
    r1 = client.post("/diagnose", json={"domain": CLEAN["domain"]})
    r2 = client.post("/diagnose", json={"domain": CLEAN["domain"]})
    assert r1.status_code == 200 and r1.json()["cached"] is False
    assert r2.status_code == 200 and r2.json()["cached"] is True
    assert r2.headers.get("X-Cache") == "HIT"


def test_healthz():
    r = _client(CLEAN["records"]).get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_instantly_compare_endpoint_with_factory():
    from setup_doctor.integrations.instantly import InstantlyClient, RecordingTransport

    accounts = {
        "items": [{"email": "a@clean.test", "stat_warmup_score": 80}],
        "next_starting_after": None,
    }
    tests = {"items": [{"id": "t1", "emails": ["a@clean.test"]}], "next_starting_after": None}
    stats = [{"test_id": "t1", "inbox_percent": 80, "spam_percent": 20}]
    analytics = {"aggregate_data": {"a@clean.test": {"health_score": 80}}, "email_date_data": {}}
    transport = RecordingTransport({
        ("GET", "/accounts"): (200, accounts),
        ("GET", "/inbox-placement-tests"): (200, tests),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (200, stats),
        ("POST", "/accounts/warmup-analytics"): (200, analytics),
    })

    def factory():
        return InstantlyClient(
            api_key="k",
            base_url="https://example.test/api/v2",
            transport=transport,
        )

    client = _client(CLEAN["records"], instantly_factory=factory)
    r = client.post("/instantly/compare", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "1.0"
    assert body["accounts"][0]["email"] == "a@clean.test"
    assert body["accounts"][0]["verdict"] in ("aligned", "mismatch", "unknown")

    r2 = client.get("/instantly/compare", params={"domain": "clean.test"})
    assert r2.status_code == 200
    assert len(r2.json()["accounts"]) == 1


def test_diagnose_include_instantly_attaches_signals():
    from setup_doctor.integrations.instantly import InstantlyClient, RecordingTransport

    accounts = {
        "items": [{"email": f"a@{CLEAN['domain']}", "stat_warmup_score": 40}],
        "next_starting_after": None,
    }
    tests = {"items": [], "next_starting_after": None}
    analytics = {"aggregate_data": {}, "email_date_data": {}}
    transport = RecordingTransport({
        ("GET", "/accounts"): (200, accounts),
        ("GET", "/inbox-placement-tests"): (200, tests),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (200, []),
        ("POST", "/accounts/warmup-analytics"): (200, analytics),
    })

    def factory():
        return InstantlyClient(
            api_key="k",
            base_url="https://example.test/api/v2",
            transport=transport,
        )

    client = _client(CLEAN["records"], instantly_factory=factory)
    r = client.post(
        "/diagnose",
        json={"domain": CLEAN["domain"], "include_instantly": True},
    )
    assert r.status_code == 200
    signals = r.json()["signals"]
    assert signals is not None
    assert signals["instantly"] is not None
    assert "instantly" not in signals["not_checked"]
    assert signals["instantly"][0]["verdict"] == "unknown"
