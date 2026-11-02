"""Instantly mode tests use recorded responses only — no live Instantly API calls."""
from __future__ import annotations

import json

import pytest

from setup_doctor.instantly_client import InstantlyClient, InstantlyError, RecordingTransport
from setup_doctor.instantly_compare import compare_warmup_to_placement, render_comparison_markdown, verdict_for

ACCOUNTS = {
    "items": [
        {"email": "strong@example.com", "stat_warmup_score": 92},
        {"email": "weak@example.com", "stat_warmup_score": 30},
        {"email": "mystery@example.com"},  # score absent -> unknown
    ],
    "next_starting_after": None,
}

TESTS = {
    "items": [
        {"id": "test-strong", "emails": ["strong@example.com"]},
        {"id": "test-weak", "emails": ["weak@example.com"]},
        # mystery has no placement test
    ],
    "next_starting_after": None,
}

STATS = [
    {"test_id": "test-strong", "inbox_percent": 20, "spam_percent": 80, "inbox_count": 2, "spam_count": 8, "count": 10},
    {"test_id": "test-weak", "inbox_percent": 90, "spam_percent": 10, "inbox_count": 9, "spam_count": 1, "count": 10},
]

ANALYTICS = {
    "aggregate_data": {
        "strong@example.com": {"health_score": 88, "sent": 10, "landed_inbox": 2, "landed_spam": 8},
        "weak@example.com": {"health_score": 40, "sent": 10, "landed_inbox": 9, "landed_spam": 1},
    },
    "email_date_data": {},
}


def _client(routes=None, sleeps=None) -> InstantlyClient:
    sleeps = sleeps if sleeps is not None else []
    transport = RecordingTransport(routes or {
        ("GET", "/accounts"): (200, ACCOUNTS),
        ("GET", "/inbox-placement-tests"): (200, TESTS),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (200, STATS),
        ("POST", "/accounts/warmup-analytics"): (200, ANALYTICS),
    })
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
    assert len(items) == 3
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
