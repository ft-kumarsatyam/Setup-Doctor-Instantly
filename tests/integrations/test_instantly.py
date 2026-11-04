"""Instantly mode tests use recorded responses only — no live Instantly API calls."""
from __future__ import annotations

import json

import pytest

from setup_doctor.core.models import Finding
from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.explain import (
    parse_instantly_rewrite,
    rewrite_instantly_signals,
    verify_instantly_rewrite,
)
from setup_doctor.integrations.instantly import (
    InstantlyClient,
    InstantlyError,
    RecordingTransport,
    check_ctd,
    compare_warmup_to_placement,
    correlate_vitals,
    email_domain,
    filter_comparisons_by_domain,
    render_comparison_markdown,
    render_readiness_markdown,
    run_workspace_readiness,
    unique_sender_domains,
    verdict_for,
)

ACCOUNTS = {
    "items": [
        {"email": "strong@example.com", "stat_warmup_score": 92},
        {"email": "weak@example.com", "stat_warmup_score": 30},
        {"email": "mystery@example.com"},  # score absent -> unknown
        {"email": "other@other.test", "stat_warmup_score": 80},
    ],
    "next_starting_after": None,
}

TESTS = {
    "items": [
        {"id": "test-strong", "emails": ["strong@example.com"]},
        {"id": "test-weak", "emails": ["weak@example.com"]},
        {"id": "test-other", "emails": ["other@other.test"]},
        # mystery has no placement test
    ],
    "next_starting_after": None,
}

STATS = [
    {"test_id": "test-strong", "inbox_percent": 20, "spam_percent": 80, "inbox_count": 2, "spam_count": 8, "count": 10},
    {"test_id": "test-weak", "inbox_percent": 90, "spam_percent": 10, "inbox_count": 9, "spam_count": 1, "count": 10},
    {"test_id": "test-other", "inbox_percent": 85, "spam_percent": 15, "inbox_count": 8, "spam_count": 2, "count": 10},
]

ANALYTICS = {
    "aggregate_data": {
        "strong@example.com": {"health_score": 88, "sent": 10, "landed_inbox": 2, "landed_spam": 8},
        "weak@example.com": {"health_score": 40, "sent": 10, "landed_inbox": 9, "landed_spam": 1},
        "other@other.test": {"health_score": 90, "sent": 5, "landed_inbox": 5},
        # mystery: no aggregate — health missing
    },
    "email_date_data": {},
}

VITALS = {
    "status": "success",
    "success_list": [
        {
            "domain": "other.test",
            "allPass": True,
            "mx": True,
            "spf": True,
            "dkim": True,
            "dmarc": True,
            "indeterminate": [],
        },
    ],
    "failure_list": [
        {
            "domain": "example.com",
            "allPass": False,
            "mx": True,
            "spf": False,
            "dkim": False,
            "dmarc": True,
            "indeterminate": [],
        },
    ],
}

CTD_OK = {"success": True, "ssl": True, "cname": True, "host": "track.example.com"}

AGENT_STATE = {
    "agent": {"id": "agent-1"},
    "activity": None,
}

AGENT_FEED = {"items": [{"id": "feed-1", "type": "dns-health"}], "next_starting_after": None}

INSIGHTS = [
    {
        "test_id": "test-strong",
        "spam_percentage": 80,
        "inbox_percentage": 20,
        "category_percentage": 0,
    },
]

BLACKLIST = {
    "items": [
        {
            "id": "bl-1",
            "test_id": "test-strong",
            "domain": "example.com",
            "domain_ip": "1.2.3.4",
            "spam_assassin_score": 2.5,
            "timestamp_created": "2026-01-01T00:00:00Z",
            "timestamp_created_date": "2026-01-01",
            "organization_id": "org-1",
        },
    ],
    "next_starting_after": None,
}


def _routes(**overrides):
    base = {
        ("GET", "/accounts"): (200, ACCOUNTS),
        ("GET", "/inbox-placement-tests"): (200, TESTS),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (200, STATS),
        ("POST", "/accounts/warmup-analytics"): (200, ANALYTICS),
        ("POST", "/accounts/test/vitals"): (200, VITALS),
        ("GET", "/accounts/ctd/status"): (200, CTD_OK),
        ("GET", "/ai-agents/deliverability/state"): (200, AGENT_STATE),
        ("GET", "/ai-agents/deliverability/agent-1/feed-items"): (200, AGENT_FEED),
        ("POST", "/inbox-placement-analytics/deliverability-insights"): (200, INSIGHTS),
        ("GET", "/inbox-placement-reports"): (200, BLACKLIST),
    }
    base.update(overrides)
    return base


def _client(routes=None, sleeps=None) -> InstantlyClient:
    sleeps = sleeps if sleeps is not None else []
    transport = RecordingTransport(routes or _routes())
    return InstantlyClient(
        api_key="test-key-not-a-secret-for-ci",
        base_url="https://example.test/api/v2",
        transport=transport,
        sleep=lambda s: sleeps.append(s),
        max_retries=3,
    )


def test_verdict_never_healthy_when_data_missing():
    assert verdict_for(None, 90)[0] == "unknown"
    assert verdict_for(95, None)[0] == "unknown"
    assert verdict_for(None, None)[0] == "unknown"
    assert verdict_for(None, None, None)[0] == "unknown"


def test_verdict_uses_health_score_when_warmup_missing():
    v, note = verdict_for(None, 20, health_score=88)
    assert v == "mismatch"
    assert "Health score" in note


def test_verdict_prefers_warmup_over_health():
    v, note = verdict_for(92, 20, health_score=10)
    assert v == "mismatch"
    assert "Warmup score" in note


def test_verdict_mismatch_when_high_score_low_inbox():
    v, note = verdict_for(92, 20)
    assert v == "mismatch"
    assert "healthy" in note.lower() or "spam" in note.lower()


def test_compare_warmup_to_placement_with_recorded_responses():
    reports = compare_warmup_to_placement(_client())
    by_email = {r.email: r for r in reports}
    assert by_email["strong@example.com"].verdict == "mismatch"
    assert by_email["strong@example.com"].warmup_score == 92
    assert by_email["strong@example.com"].inbox_percent == 20
    assert by_email["weak@example.com"].verdict == "mismatch"  # low score, high inbox
    assert by_email["mystery@example.com"].verdict == "unknown"
    assert by_email["mystery@example.com"].warmup_score is None
    assert by_email["mystery@example.com"].inbox_percent is None


def test_domain_filter_on_compare():
    reports = compare_warmup_to_placement(_client(), domain="example.com")
    emails = {r.email for r in reports}
    assert emails == {"strong@example.com", "weak@example.com", "mystery@example.com"}
    assert all(email_domain(e) == "example.com" for e in emails)


def test_filter_comparisons_by_domain_helper():
    all_reports = compare_warmup_to_placement(_client())
    filtered = filter_comparisons_by_domain(all_reports, "other.test")
    assert len(filtered) == 1
    assert filtered[0].email == "other@other.test"


def test_unique_sender_domains():
    domains = unique_sender_domains(ACCOUNTS["items"])
    assert domains == ["example.com", "other.test"]


def test_render_marks_unknown_explicitly():
    md = render_comparison_markdown(compare_warmup_to_placement(_client()))
    assert "unknown" in md
    assert "mystery@example.com" in md


def test_429_retries_with_backoff():
    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky(method, url, headers, body):
        calls["n"] += 1
        if calls["n"] < 3:
            return 429, b'{"message":"Rate limit exceeded"}', {"retry-after": "0"}
        return 200, json.dumps(ACCOUNTS).encode(), {}

    client = InstantlyClient(
        api_key="k",
        base_url="https://example.test/api/v2",
        transport=flaky,
        sleep=lambda s: sleeps.append(s),
        max_retries=5,
    )
    items = client.list_accounts()
    assert len(items) == 4
    assert sleeps  # backoff invoked


def test_http_error_raises_without_treating_as_healthy():
    transport = RecordingTransport({("GET", "/accounts"): (403, {"message": "forbidden"})})
    client = InstantlyClient(api_key="k", base_url="https://example.test/api/v2", transport=transport)
    with pytest.raises(InstantlyError) as ei:
        client.list_accounts()
    assert ei.value.status == 403


def test_authorization_header_sent_but_key_not_in_error_str():
    transport = RecordingTransport({("GET", "/accounts"): (401, {"message": "bad"})})
    secret = "super-secret-key-value"
    client = InstantlyClient(api_key=secret, base_url="https://example.test/api/v2", transport=transport)
    with pytest.raises(InstantlyError) as ei:
        client.list_accounts()
    assert secret not in str(ei.value)


def test_ctd_status_ok():
    sig = check_ctd(_client(), "track.example.com")
    assert sig.status == "ok"
    assert sig.success is True


def test_ctd_missing_host_not_checked():
    sig = check_ctd(_client(), None)
    assert sig.status == "not_checked"


def test_correlate_vitals_agree_and_disagree():
    failing = Finding(
        id="SPF_MISSING",
        severity="critical",
        title="SPF missing",
        why="why",
        fix="fix",
        evidence={},
    )
    row = VITALS["failure_list"][0]
    corr = correlate_vitals("example.com", row, [failing])
    assert corr.correlation == "agree"

    ok_row = VITALS["success_list"][0]
    disagree = correlate_vitals("other.test", ok_row, [failing])
    assert disagree.correlation == "disagree"

    unknown = correlate_vitals("example.com", None, [failing])
    assert unknown.correlation == "unknown"


def test_workspace_readiness_recorded():
    # Minimal DNS fixture so diagnose does not invent Instantly health
    records = {
        "example.com": {"TXT": [], "MX": [], "A": []},
        "other.test": {"TXT": [], "MX": [], "A": []},
    }
    resolver = FixtureResolver(records)
    report = run_workspace_readiness(
        _client(),
        resolver,
        ctd_hosts=["track.example.com"],
        include_rich_signals=True,
    )
    domains = {d.domain for d in report.domains}
    assert "example.com" in domains
    assert "other.test" in domains
    md = render_readiness_markdown(report)
    assert "workspace readiness" in md.lower()
    assert "unknown" in md.lower() or "Findings" in md or "finding" in md.lower()


def test_client_rich_endpoints():
    client = _client()
    assert client.test_account_vitals(["strong@example.com"])["status"] == "success"
    assert client.custom_tracking_domain_status("track.example.com")["success"] is True
    assert client.get_default_deliverability_agent_state()["agent"]["id"] == "agent-1"
    assert len(client.list_deliverability_agent_feed("agent-1")) == 1
    assert client.inbox_placement_deliverability_insights("test-strong")
    assert client.list_inbox_placement_blacklist_reports("test-strong")


def test_instantly_rewrite_grounding_rejects_invented_scores():
    reports = compare_warmup_to_placement(_client(), domain="example.com")
    bad = json.dumps([
        {"email": "strong@example.com", "summary": "Warmup 99 looks fine (aligned)."},
        {"email": "weak@example.com", "summary": "mismatch with inbox 90."},
        {"email": "mystery@example.com", "summary": "unknown — no data."},
    ])
    items, _ = parse_instantly_rewrite(bad)
    assert items is not None
    violations = verify_instantly_rewrite(items, reports)
    assert any("verdict" in v or "numeric" in v for v in violations)


def test_instantly_rewrite_fallback_on_bad_model():
    reports = compare_warmup_to_placement(_client(), domain="example.com")

    def bad_complete(_prompt: str) -> str:
        return "not json"

    md, source, violations = rewrite_instantly_signals(reports, bad_complete)
    assert source == "template_fallback"
    assert violations
    assert "mystery@example.com" in md


def test_instantly_rewrite_accepts_grounded_draft():
    reports = compare_warmup_to_placement(_client(), domain="example.com")
    by = {r.email: r for r in reports}

    def good_complete(_prompt: str) -> str:
        return json.dumps([
            {
                "email": "strong@example.com",
                "summary": (
                    f"Engine verdict mismatch: warmup {by['strong@example.com'].warmup_score:g} "
                    f"vs inbox {by['strong@example.com'].inbox_percent:g}."
                ),
            },
            {
                "email": "weak@example.com",
                "summary": (
                    f"Engine verdict mismatch: warmup {by['weak@example.com'].warmup_score:g} "
                    f"vs inbox {by['weak@example.com'].inbox_percent:g}."
                ),
            },
            {
                "email": "mystery@example.com",
                "summary": "Engine verdict unknown — missing warmup and placement data.",
            },
        ])

    md, source, violations = rewrite_instantly_signals(reports, good_complete)
    assert source == "model_verified"
    assert violations == []
    assert "GTM summary" in md
