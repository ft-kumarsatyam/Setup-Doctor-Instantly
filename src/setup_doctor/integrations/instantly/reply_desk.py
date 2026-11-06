"""Reply Desk — unread Unibox mail, quoted from Instantly.

Reads the unread count and up to five pages of received thread heads. Does not
reply, forward, or label interest. A missing count stays unknown, never clear.
A sending domain is domain_blocked only when the caller supplies that domain
as blocked. Unchecked domains stay null, never clean.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from setup_doctor.core.result import SCHEMA_VERSION

from .client import InstantlyClient, InstantlyError

PREVIEW_LIMIT = 160
PAGE_LIMIT = 20
MAX_PAGES = 5


def unread_verdict(count: int | None) -> str:
    """Workspace verdict from GET /emails/unread/count. Missing count is unknown."""
    if count is None:
        return "unknown"
    if count > 0:
        return "attention"
    return "clear"


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


@dataclass
class ReplyThread:
    email_id: str | None
    lead: str | None
    subject: str | None
    timestamp_email: str | None
    eaccount: str | None
    campaign_id: str | None
    is_unread: bool | None
    is_auto_reply: bool | None
    i_status: int | None
    ai_interest_value: float | None
    content_preview: str | None
    sender_domain: str | None = None
    domain_blocked: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReplyDeskReport:
    verdict: str
    summary_spoken: str
    unread_count: int | None
    threads: list[ReplyThread] = field(default_factory=list)
    more_threads: bool = False
    pages_read: int = 0
    not_checked: list[str] = field(default_factory=list)
    campaign_id: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "agent": "reply_desk",
            "verdict": self.verdict,
            "summary_spoken": self.summary_spoken,
            "unread_count": self.unread_count,
            "campaign_id": self.campaign_id,
            "more_threads": self.more_threads,
            "pages_read": self.pages_read,
            "not_checked": list(self.not_checked),
            "note": self.note,
            "threads": [thread.to_dict() for thread in self.threads],
        }


def _flag(value: Any) -> bool | None:
    """Instantly uses 1 and 0. Anything else is unknown."""
    number = _as_int(value)
    if number == 1:
        return True
    if number == 0:
        return False
    return None


def _interest(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _email_domain(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    host = value.rsplit("@", 1)[1].strip().lower().rstrip(".")
    return host or None


def _thread(row: dict[str, Any]) -> ReplyThread:
    preview = _as_str(row.get("content_preview"))
    if preview and len(preview) > PREVIEW_LIMIT:
        preview = preview[:PREVIEW_LIMIT].rstrip() + "…"
    return ReplyThread(
        email_id=_as_str(row.get("id")),
        lead=_as_str(row.get("lead")),
        subject=_as_str(row.get("subject")),
        timestamp_email=_as_str(row.get("timestamp_email")),
        eaccount=_as_str(row.get("eaccount")),
        campaign_id=_as_str(row.get("campaign_id")),
        is_unread=_flag(row.get("is_unread")),
        is_auto_reply=_flag(row.get("is_auto_reply")),
        i_status=_as_int(row.get("i_status")),
        ai_interest_value=_interest(row.get("ai_interest_value")),
        content_preview=preview,
        sender_domain=_email_domain(_as_str(row.get("eaccount"))),
    )


def _speak(report: ReplyDeskReport) -> str:
    if report.unread_count is None:
        count_line = "Unread count is missing, so this inbox is unknown, not clear."
    else:
        count_line = f"Unread count {report.unread_count}."
    unread_threads = sum(1 for thread in report.threads if thread.is_unread is True)
    auto = sum(1 for thread in report.threads if thread.is_auto_reply is True)
    page = (
        f"Read {report.pages_read} page(s), {len(report.threads)} received thread(s), "
        f"{unread_threads} unread on those pages, {auto} marked auto-reply."
    )
    parts = [count_line, f"Verdict {report.verdict}.", page]
    if report.campaign_id:
        parts.append(
            "The unread count is the whole workspace. The thread list is filtered to "
            f"campaign {report.campaign_id}."
        )
    if report.more_threads:
        parts.append("Instantly still has threads after the pages read here.")
    blocked = sum(1 for thread in report.threads if thread.domain_blocked is True)
    if blocked:
        parts.append(f"{blocked} thread(s) are on a sending domain with a blocking Finding.")
    shown = [thread for thread in report.threads if thread.is_unread is True][:3]
    if not shown:
        shown = report.threads[:3]
    for thread in shown:
        who = thread.lead or "unknown lead"
        subject = thread.subject or "(no subject)"
        parts.append(f"{who}: {subject}.")
    if "email_list" in report.not_checked:
        parts.append("The thread list was not returned.")
    return " ".join(parts)


def _mark_blocked(threads: list[ReplyThread], blocked_domains: set[str] | None) -> None:
    """True only for a sender the caller already found blocking. Else null."""
    if not blocked_domains:
        return
    for thread in threads:
        if thread.sender_domain and thread.sender_domain in blocked_domains:
            thread.domain_blocked = True


def _read_pages(
    client: InstantlyClient,
    *,
    campaign_id: str | None,
    limit: int,
    not_checked: list[str],
) -> tuple[list[ReplyThread], bool, int]:
    """Walk next_starting_after. Stop on a repeated cursor or MAX_PAGES."""
    threads: list[ReplyThread] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    more = False
    pages = 0
    while pages < MAX_PAGES:
        try:
            page = client.list_received_emails(
                limit=limit, campaign_id=campaign_id, starting_after=cursor,
            )
        except InstantlyError:
            not_checked.append("email_list")
            break
        pages += 1
        items = page.get("items") if isinstance(page, dict) else None
        if not isinstance(items, list):
            not_checked.append("email_list")
            break
        for row in items:
            if not isinstance(row, dict):
                continue
            # 1 = sent from campaign, 3 = sent, 4 = scheduled. Keep received (2) and unlabeled.
            ue_type = _as_int(row.get("ue_type"))
            if ue_type in (1, 3, 4):
                continue
            thread = _thread(row)
            if thread.email_id and thread.email_id in seen_ids:
                continue
            if thread.email_id:
                seen_ids.add(thread.email_id)
            threads.append(thread)
        nxt = _as_str(page.get("next_starting_after")) if isinstance(page, dict) else None
        if not nxt:
            more = False
            break
        if nxt in seen_cursors:
            more = True
            break
        seen_cursors.add(nxt)
        if pages >= MAX_PAGES:
            more = True
            not_checked.append("email_list_capped")
            break
        cursor = nxt
    return threads, more, pages


def run_reply_desk(
    client: InstantlyClient,
    *,
    campaign_id: str | None = None,
    limit: int = PAGE_LIMIT,
    blocked_domains: set[str] | None = None,
) -> ReplyDeskReport:
    """Read Unibox across pages. Never sends a reply."""
    named = (campaign_id or "").strip() or None
    not_checked: list[str] = []
    payload = client.count_unread_emails()
    unread = _as_int(payload.get("count")) if isinstance(payload, dict) else None
    if unread is None:
        not_checked.append("unread_count")

    threads, more, pages = _read_pages(
        client, campaign_id=named, limit=limit, not_checked=not_checked,
    )
    blocked = {d.strip().lower().rstrip(".") for d in (blocked_domains or set()) if d.strip()}
    _mark_blocked(threads, blocked or None)

    note = (
        "Interest status is the raw i_status number from Instantly. "
        "This agent does not name that number and does not send replies."
    )
    report = ReplyDeskReport(
        verdict=unread_verdict(unread),
        summary_spoken="",
        unread_count=unread,
        threads=threads,
        more_threads=more,
        pages_read=pages,
        not_checked=sorted(set(not_checked)),
        campaign_id=named,
        note=note,
    )
    report.summary_spoken = _speak(report)
    return report


def render_reply_desk_markdown(report: ReplyDeskReport) -> str:
    lines = [
        "# Reply Desk",
        "",
        f"**Verdict:** `{report.verdict}`",
        "",
        report.summary_spoken,
        "",
        report.note,
        "",
    ]
    if report.not_checked:
        lines.append(f"Not checked: {', '.join(report.not_checked)}")
        lines.append("")
    for thread in report.threads:
        who = thread.lead or "unknown lead"
        lines.append(f"## {who}")
        lines.append("")
        lines.append(f"- Subject: {thread.subject or '(no subject)'}")
        if thread.timestamp_email:
            lines.append(f"- When: {thread.timestamp_email}")
        if thread.is_unread is True:
            lines.append("- Unread: yes")
        elif thread.is_unread is False:
            lines.append("- Unread: no")
        else:
            lines.append("- Unread: unknown")
        if thread.is_auto_reply is True:
            lines.append("- Auto-reply: yes")
        elif thread.is_auto_reply is False:
            lines.append("- Auto-reply: no")
        if thread.i_status is not None:
            lines.append(f"- Interest status number: {thread.i_status}")
        if thread.ai_interest_value is not None:
            lines.append(f"- AI interest value: {thread.ai_interest_value}")
        if thread.content_preview:
            lines.append(f"- Preview: {thread.content_preview}")
        if thread.domain_blocked is True:
            lines.append(f"- Sending domain `{thread.sender_domain}` has a blocking Finding.")
        lines.append("")
    lines.append("Read-only. This agent does not reply or forward.")
    return "\n".join(lines).rstrip() + "\n"


def verify_reply_desk_honesty(payload: dict[str, Any]) -> list[str]:
    """A positive or missing unread count must not be reported as clear."""
    violations: list[str] = []
    count = payload.get("unread_count")
    verdict = payload.get("verdict")
    if isinstance(count, int) and not isinstance(count, bool) and count > 0 and verdict == "clear":
        violations.append("clear while unread_count > 0")
    if count is None and verdict == "clear":
        violations.append("clear while unread count is missing")
    for thread in payload.get("threads") or []:
        if isinstance(thread, dict) and thread.get("domain_blocked") is False:
            violations.append("domain_blocked false treats an unchecked sender as clean")
            break
    return violations
