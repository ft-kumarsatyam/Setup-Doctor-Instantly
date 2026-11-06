"""Campaign Desk and Reply Desk. Recorded Instantly responses only."""
from __future__ import annotations

from setup_doctor.integrations.instantly import (
    InstantlyClient,
    RecordingTransport,
    render_campaign_desk_markdown,
    render_reply_desk_markdown,
    run_campaign_desk,
    run_reply_desk,
    verify_campaign_desk_honesty,
    verify_reply_desk_honesty,
)

LIVE = "camp-live"
OLD = "camp-old"


def _analytics(campaign_id: str, *, replies: int, bounced: int, sent: int) -> dict:
    return {
        "campaign_name": "Outreach" if campaign_id == LIVE else "Old draft",
        "campaign_id": campaign_id,
        "campaign_status": 1 if campaign_id == LIVE else 2,
        "campaign_is_evergreen": False,
        "leads_count": 100,
        "contacted_count": 80,
        "open_count": 10,
        "reply_count": replies,
        "reply_count_unique": replies,
        "link_click_count": 0,
        "bounced_count": bounced,
        "unsubscribed_count": 0,
        "completed_count": 0,
        "emails_sent_count": sent,
        "new_leads_contacted_count": 5,
        "total_opportunities": 1,
        "total_opportunity_value": 0,
    }


def _client(routes: dict) -> InstantlyClient:
    return InstantlyClient(
        api_key="test-key-not-a-secret-for-ci",
        base_url="https://example.test/api/v2",
        transport=RecordingTransport(routes),
        sleep=lambda _s: None,
    )


def _campaign_routes(sending_status: str | None) -> dict:
    sending = {
        "diagnostics": {
            "campaign_id": LIVE,
            "status": sending_status,
            "accounts_summary": {"total_connected": 4, "available": 0},
        },
        "summary": {
            "status": sending_status,
            "status_message": "Accounts are unhealthy." if sending_status != "healthy" else "Campaign is sending normally",
        },
    }
    return {
        ("GET", "/campaigns"): (200, {
            "items": [
                {"id": LIVE, "name": "Outreach", "status": 1, "not_sending_status": None},
                {"id": OLD, "name": "Paused one", "status": 2, "not_sending_status": None},
            ],
            "next_starting_after": None,
        }),
        ("GET", "/campaigns/analytics"): (200, [
            _analytics(LIVE, replies=12, bounced=40, sent=500),
            _analytics(OLD, replies=0, bounced=0, sent=10),
        ]),
        ("GET", f"/campaigns/{LIVE}/sending-status"): (200, sending),
    }


def test_unhealthy_sending_status_stalls_and_skips_parked():
    transport = RecordingTransport(_campaign_routes("campaign_accounts_unhealthy"))
    client = InstantlyClient(
        api_key="test-key-not-a-secret-for-ci",
        base_url="https://example.test/api/v2",
        transport=transport,
        sleep=lambda _s: None,
    )
    report = run_campaign_desk(client)
    by_id = {row.campaign_id: row for row in report.campaigns}
    assert report.verdict == "stalled"
    assert by_id[LIVE].verdict == "stalled"
    assert by_id[LIVE].counts["reply_count_unique"] == 12
    assert by_id[LIVE].counts["bounced_count"] == 40
    assert by_id[OLD].verdict == "parked"
    assert ("GET", f"/campaigns/{OLD}/sending-status") not in transport.calls
    assert "unique replies 12" in report.summary_spoken
    assert "bounced leads 40" in report.summary_spoken
    assert verify_campaign_desk_honesty(report.to_dict()) == []
    lied = report.to_dict()
    lied["verdict"] = "sending"
    assert verify_campaign_desk_honesty(lied)


def test_healthy_campaign_is_sending_and_missing_code_is_unknown():
    report = run_campaign_desk(_client(_campaign_routes("healthy")))
    assert report.verdict == "sending"
    missing = _campaign_routes(None)
    missing[("GET", f"/campaigns/{LIVE}/sending-status")] = (
        200, {"diagnostics": None, "summary": None},
    )
    unknown = run_campaign_desk(_client(missing))
    by_id = {row.campaign_id: row for row in unknown.campaigns}
    assert by_id[LIVE].verdict == "unknown"
    assert unknown.verdict == "unknown"
    text = render_campaign_desk_markdown(unknown)
    assert "unknown" in text


def test_empty_workspace_is_idle_not_sending():
    routes = {
        ("GET", "/campaigns"): (200, {"items": [], "next_starting_after": None}),
        ("GET", "/campaigns/analytics"): (200, []),
    }
    report = run_campaign_desk(_client(routes))
    assert report.verdict == "idle"
    assert report.campaigns == []
    assert "no campaigns" in report.summary_spoken


def test_reply_desk_attention_clear_and_unknown():
    received = {
        "items": [
            {
                "id": "mail-1",
                "ue_type": 2,
                "lead": "ada@client.test",
                "subject": "Re: intro",
                "is_unread": 1,
                "is_auto_reply": 0,
                "i_status": 1,
                "ai_interest_value": 0.75,
                "content_preview": "Can we talk Thursday?",
                "timestamp_email": "2026-11-06T05:09:51.246Z",
                "eaccount": "rep@example.com",
            },
            {
                "id": "mail-sent",
                "ue_type": 1,
                "lead": "ada@client.test",
                "subject": "intro",
                "is_unread": 0,
            },
            {
                "id": "mail-ooo",
                "ue_type": 2,
                "lead": "bob@client.test",
                "subject": "Out of office",
                "is_unread": 1,
                "is_auto_reply": 1,
                "content_preview": "I am away.",
            },
        ],
        "next_starting_after": "more",
    }
    attention = run_reply_desk(_client({
        ("GET", "/emails/unread/count"): (200, {"count": 4}),
        ("GET", "/emails"): (200, received),
    }))
    assert attention.verdict == "attention"
    assert attention.unread_count == 4
    assert [thread.email_id for thread in attention.threads] == ["mail-1", "mail-ooo"]
    assert attention.threads[0].i_status == 1
    assert attention.more_threads is True
    assert "Unread count 4" in attention.summary_spoken
    assert verify_reply_desk_honesty(attention.to_dict()) == []
    lied = attention.to_dict()
    lied["verdict"] = "clear"
    assert verify_reply_desk_honesty(lied)
    markdown = render_reply_desk_markdown(attention)
    assert "ada@client.test" in markdown
    assert "does not reply" in markdown

    clear = run_reply_desk(_client({
        ("GET", "/emails/unread/count"): (200, {"count": 0}),
        ("GET", "/emails"): (200, {"items": [], "next_starting_after": None}),
    }))
    assert clear.verdict == "clear"

    unknown = run_reply_desk(_client({
        ("GET", "/emails/unread/count"): (200, {}),
        ("GET", "/emails"): (200, {"items": []}),
    }))
    assert unknown.verdict == "unknown"
    assert unknown.unread_count is None
    assert "unknown" in unknown.summary_spoken
    assert verify_reply_desk_honesty(unknown.to_dict()) == []


def test_reply_desk_joins_pages_and_marks_only_named_domains():
    routes = {
        ("GET", "/emails/unread/count"): (200, {"count": 2}),
        ("GET", "/emails", ""): (200, {
            "items": [{
                "id": "mail-a",
                "ue_type": 2,
                "lead": "a@client.test",
                "subject": "First",
                "is_unread": 1,
                "eaccount": "rep@send.test",
            }],
            "next_starting_after": "cursor-2",
        }),
        ("GET", "/emails", "cursor-2"): (200, {
            "items": [{
                "id": "mail-b",
                "ue_type": 2,
                "lead": "b@client.test",
                "subject": "Second",
                "is_unread": 1,
                "eaccount": "rep@other.test",
            }],
            "next_starting_after": None,
        }),
    }
    report = run_reply_desk(_client(routes), blocked_domains={"send.test"})
    assert [thread.email_id for thread in report.threads] == ["mail-a", "mail-b"]
    assert report.pages_read == 2
    assert report.more_threads is False
    assert report.threads[0].domain_blocked is True
    assert report.threads[1].domain_blocked is None
    lied = report.to_dict()
    lied["threads"][1]["domain_blocked"] = False
    assert verify_reply_desk_honesty(lied)
