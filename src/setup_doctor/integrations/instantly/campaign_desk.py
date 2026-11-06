"""Campaign Desk — why Instantly campaigns are or are not sending.

Reads campaign list, per-campaign analytics, and sending-status. Does not
activate, pause, or invent a health score. A missing status stays unknown.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from setup_doctor.core.result import SCHEMA_VERSION

from .client import InstantlyClient, InstantlyError

# Documented on GET /campaigns and GET /campaigns/analytics.
CAMPAIGN_STATUS_LABELS: dict[int, str] = {
    0: "Draft",
    1: "Active",
    2: "Paused",
    3: "Completed",
    4: "Running Subsequences",
    -99: "Account Suspended",
    -1: "Accounts Unhealthy",
    -2: "Bounce Protect",
}

# Documented on Campaign.not_sending_status.
NOT_SENDING_LABELS: dict[int, str] = {
    1: "Campaign is currently not within its sending schedule.",
    2: "Campaign is currently waiting for a lead to process.",
    3: "Campaign has reached its daily sending limit.",
    4: "All sending accounts for this campaign have reached their daily sending limit.",
    99: "Campaign is currently not sending due to an error. Please contact support for assistance.",
}

# Documented sending-status codes except "healthy".
SENDING_ISSUE_CODES = frozenset({
    "campaign_paused",
    "campaign_draft",
    "campaign_completed",
    "campaign_running_subsequences",
    "campaign_bounce_protect",
    "campaign_accounts_unhealthy",
    "campaign_account_suspended",
    "out_of_schedule",
    "waiting_for_lead_timezone_window",
    "invalid_lead_timezone_configuration",
    "waiting_for_leads",
    "daily_limit_met",
    "account_daily_limit_met",
    "account_slow_ramp_limit_met",
    "new_lead_limit_met",
    "all_accounts_unhealthy",
    "waiting_for_esp_match",
    "domain_limit_reached",
    "follow_up_delay_not_met",
    "no_accounts_available",
})

# Draft, paused, completed: the campaign record already says it is not live.
PARKED_STATUSES = frozenset({0, 2, 3})

SENDING_STATUS_CAP = 25

COUNT_FIELDS = (
    "leads_count",
    "contacted_count",
    "emails_sent_count",
    "reply_count",
    "reply_count_unique",
    "bounced_count",
    "unsubscribed_count",
    "total_opportunities",
)


def sending_code_verdict(code: str | None) -> str:
    """Map Instantly's sending-status code. Unknown codes stay unknown."""
    if code is None or code == "":
        return "unknown"
    if code == "healthy":
        return "sending"
    if code in SENDING_ISSUE_CODES:
        return "stalled"
    return "unknown"


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


@dataclass
class CampaignRow:
    campaign_id: str
    name: str | None
    campaign_status: int | None
    campaign_status_label: str | None
    not_sending_status: int | None
    not_sending_label: str | None
    sending_status: str | None
    sending_status_message: str | None
    accounts_connected: int | None
    accounts_available: int | None
    counts: dict[str, int | None]
    verdict: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CampaignDeskReport:
    verdict: str
    summary_spoken: str
    campaigns: list[CampaignRow] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)
    campaign_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "agent": "campaign_desk",
            "verdict": self.verdict,
            "summary_spoken": self.summary_spoken,
            "campaign_id": self.campaign_id,
            "not_checked": list(self.not_checked),
            "campaigns": [row.to_dict() for row in self.campaigns],
        }


def _analytics_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = _as_str(row.get("campaign_id"))
        if cid:
            out[cid] = row
    return out


def _counts(row: dict[str, Any] | None) -> dict[str, int | None]:
    if not row:
        return {name: None for name in COUNT_FIELDS}
    return {name: _as_int(row.get(name)) for name in COUNT_FIELDS}


def _needs_sending_status(status: int | None, named: bool) -> bool:
    if named:
        return True
    if status is None:
        return True
    return status not in PARKED_STATUSES


def _row_from(
    campaign: dict[str, Any],
    analytics: dict[str, Any] | None,
    sending: dict[str, Any] | None,
    *,
    sending_error: str | None,
) -> CampaignRow:
    cid = _as_str(campaign.get("id")) or _as_str(campaign.get("campaign_id")) or ""
    status = _as_int(campaign.get("status"))
    if status is None and analytics:
        status = _as_int(analytics.get("campaign_status"))
    label = CAMPAIGN_STATUS_LABELS.get(status) if status is not None else None
    not_sending = _as_int(campaign.get("not_sending_status"))
    not_sending_label = NOT_SENDING_LABELS.get(not_sending) if not_sending is not None else None
    if not_sending is not None and not_sending_label is None:
        not_sending_label = None

    code: str | None = None
    message: str | None = None
    connected: int | None = None
    available: int | None = None
    if isinstance(sending, dict):
        diagnostics = sending.get("diagnostics") if isinstance(sending.get("diagnostics"), dict) else {}
        summary = sending.get("summary") if isinstance(sending.get("summary"), dict) else {}
        code = _as_str(diagnostics.get("status")) or _as_str(summary.get("status"))
        message = _as_str(summary.get("status_message"))
        accounts = diagnostics.get("accounts_summary") if isinstance(diagnostics.get("accounts_summary"), dict) else {}
        connected = _as_int(accounts.get("total_connected"))
        available = _as_int(accounts.get("available"))

    counts = _counts(analytics)
    if sending_error:
        verdict = "unknown"
        note = sending_error
        if not_sending_label:
            note = f"{note} {not_sending_label}"
    elif status in PARKED_STATUSES and code is None and not _needs_named_override(sending):
        verdict = "parked"
        note = f"Campaign status is {label or status}."
    else:
        verdict = sending_code_verdict(code)
        if code is None:
            note = "Instantly returned no sending-status code."
        elif verdict == "unknown":
            note = f"Instantly sending status `{code}` is not in the documented code list."
        elif message:
            note = f"Instantly sending status `{code}`. {message}"
        else:
            note = f"Instantly sending status `{code}`."
        if not_sending_label and verdict != "sending":
            note = f"{note} {not_sending_label}"

    if status in (-1, -2, -99) and verdict == "sending":
        # The campaign record itself says accounts are unhealthy, suspended, or in bounce protect.
        verdict = "stalled"
        note = f"Campaign status is {label}. {note}"

    return CampaignRow(
        campaign_id=cid,
        name=_as_str(campaign.get("name")) or _as_str((analytics or {}).get("campaign_name")),
        campaign_status=status,
        campaign_status_label=label,
        not_sending_status=not_sending,
        not_sending_label=not_sending_label,
        sending_status=code,
        sending_status_message=message,
        accounts_connected=connected,
        accounts_available=available,
        counts=counts,
        verdict=verdict,
        note=note.strip(),
    )


def _needs_named_override(sending: dict[str, Any] | None) -> bool:
    return isinstance(sending, dict) and (
        isinstance(sending.get("diagnostics"), dict) or isinstance(sending.get("summary"), dict)
    )


def _workspace_verdict(rows: list[CampaignRow]) -> str:
    if not rows:
        return "idle"
    verdicts = {row.verdict for row in rows}
    if "stalled" in verdicts:
        return "stalled"
    if "unknown" in verdicts:
        return "unknown"
    if "sending" in verdicts:
        return "sending"
    return "idle"


def _speak(report_rows: list[CampaignRow], verdict: str, not_checked: list[str]) -> str:
    if not report_rows:
        return "Instantly returned no campaigns. Nothing was marked sending."
    buckets = {"sending": 0, "stalled": 0, "parked": 0, "unknown": 0}
    for row in report_rows:
        buckets[row.verdict] = buckets.get(row.verdict, 0) + 1
    parts = [
        f"{len(report_rows)} campaign(s).",
        f"Workspace verdict {verdict}.",
        (
            f"{buckets['sending']} sending, {buckets['stalled']} stalled, "
            f"{buckets['parked']} parked, {buckets['unknown']} unknown."
        ),
    ]
    focus = next((row for row in report_rows if row.verdict == "stalled"), None)
    if focus is None:
        focus = next((row for row in report_rows if row.verdict == "unknown"), None)
    if focus is not None:
        title = focus.name or focus.campaign_id
        parts.append(f"{title}: {focus.note}")
        unique = focus.counts.get("reply_count_unique")
        bounced = focus.counts.get("bounced_count")
        sent = focus.counts.get("emails_sent_count")
        bits = []
        if unique is not None:
            bits.append(f"unique replies {unique}")
        if bounced is not None:
            bits.append(f"bounced leads {bounced}")
        if sent is not None:
            bits.append(f"emails sent {sent}")
        if bits:
            parts.append("Analytics on that campaign: " + ", ".join(bits) + ".")
        else:
            parts.append("Analytics counts for that campaign were missing.")
    if "sending_status_capped" in not_checked:
        parts.append(
            f"Sending status was read for at most {SENDING_STATUS_CAP} campaigns that are not parked."
        )
    return " ".join(parts)


def run_campaign_desk(
    client: InstantlyClient,
    *,
    campaign_id: str | None = None,
) -> CampaignDeskReport:
    """Read Instantly campaigns. Never calls activate or pause."""
    named = (campaign_id or "").strip() or None
    not_checked: list[str] = []
    if named:
        campaigns = [client.get_campaign(named)]
    else:
        campaigns = client.list_campaigns()

    try:
        analytics_rows = client.list_campaign_analytics()
    except InstantlyError:
        analytics_rows = []
        not_checked.append("campaign_analytics")
    by_analytics = _analytics_index(analytics_rows)

    ranked: list[tuple[int, dict[str, Any]]] = []
    for campaign in campaigns:
        status = _as_int(campaign.get("status"))
        cid = _as_str(campaign.get("id")) or ""
        if named and cid and cid != named and _as_str(campaign.get("campaign_id")) != named:
            continue
        if not _needs_sending_status(status, named=bool(named)):
            ranked.append((9, campaign))
            continue
        not_sending = _as_int(campaign.get("not_sending_status"))
        if status in (-99, -1, -2) or not_sending == 99:
            rank = 0
        elif not_sending is not None:
            rank = 1
        else:
            rank = 2
        ranked.append((rank, campaign))
    ranked.sort(key=lambda item: item[0])

    fetched = 0
    rows: list[CampaignRow] = []
    for rank, campaign in ranked:
        cid = _as_str(campaign.get("id")) or ""
        analytics = by_analytics.get(cid)
        sending: dict[str, Any] | None = None
        sending_error: str | None = None
        if rank == 9:
            rows.append(_row_from(campaign, analytics, None, sending_error=None))
            continue
        if fetched >= SENDING_STATUS_CAP:
            not_checked.append("sending_status_capped")
            rows.append(_row_from(
                campaign,
                analytics,
                None,
                sending_error="Sending status was not read (cap reached).",
            ))
            continue
        fetched += 1
        if not cid:
            rows.append(_row_from(
                campaign, analytics, None,
                sending_error="Campaign id missing; sending status was not read.",
            ))
            continue
        try:
            sending = client.get_campaign_sending_status(cid)
        except InstantlyError as exc:
            sending_error = f"Instantly sending-status request failed (HTTP {exc.status})."
        rows.append(_row_from(campaign, analytics, sending, sending_error=sending_error))

    if named and not rows:
        not_checked.append("campaign")
    verdict = _workspace_verdict(rows)
    summary = _speak(rows, verdict, not_checked)
    return CampaignDeskReport(
        verdict=verdict,
        summary_spoken=summary,
        campaigns=rows,
        not_checked=sorted(set(not_checked)),
        campaign_id=named,
    )


def render_campaign_desk_markdown(report: CampaignDeskReport) -> str:
    lines = [
        "# Campaign Desk",
        "",
        f"**Verdict:** `{report.verdict}`",
        "",
        report.summary_spoken,
        "",
    ]
    if report.not_checked:
        lines.append(f"Not checked: {', '.join(report.not_checked)}")
        lines.append("")
    for row in report.campaigns:
        title = row.name or row.campaign_id
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"- Verdict: `{row.verdict}`")
        if row.campaign_status_label:
            lines.append(f"- Campaign status: {row.campaign_status_label}")
        elif row.campaign_status is not None:
            lines.append(f"- Campaign status code: {row.campaign_status} (no documented label)")
        if row.sending_status:
            lines.append(f"- Sending status: `{row.sending_status}`")
        if row.sending_status_message:
            lines.append(f"- Instantly: {row.sending_status_message}")
        lines.append(f"- {row.note}")
        shown = [f"{key} {value}" for key, value in row.counts.items() if value is not None]
        if shown:
            lines.append("- Counts: " + ", ".join(shown))
        lines.append("")
    lines.append("Read-only. This agent does not activate or pause campaigns.")
    return "\n".join(lines).rstrip() + "\n"


def verify_campaign_desk_honesty(payload: dict[str, Any]) -> list[str]:
    """Reject a sending verdict when any campaign row is stalled."""
    violations: list[str] = []
    rows = payload.get("campaigns") or []
    stalled = False
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("verdict") == "stalled":
                stalled = True
                code = row.get("sending_status")
                if code == "healthy":
                    violations.append("stalled row has sending status healthy")
    if stalled and payload.get("verdict") == "sending":
        violations.append("workspace verdict sending while a campaign is stalled")
    if payload.get("verdict") == "sending" and not rows:
        violations.append("sending with no campaigns")
    return violations
