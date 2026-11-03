"""Compare Instantly warmup scores with inbox-placement test outcomes.

Read-only. Missing warmup score or missing placement data is reported as
"unknown" — never as healthy. This module does not call an LLM.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .client import InstantlyClient


@dataclass
class AccountComparison:
    email: str
    warmup_score: float | None
    health_score: float | None
    inbox_percent: float | None
    spam_percent: float | None
    test_ids: list[str] = field(default_factory=list)
    # aligned | mismatch | unknown — never invent "healthy" when data is missing
    verdict: str = "unknown"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def verdict_for(warmup: float | None, inbox_percent: float | None) -> tuple[str, str]:
    """How well the warmup score predicts placement. Missing data => unknown."""
    if warmup is None and inbox_percent is None:
        return "unknown", "No warmup score and no inbox-placement results for this account."
    if warmup is None:
        return "unknown", "Warmup score missing on the account; cannot judge prediction."
    if inbox_percent is None:
        return "unknown", "No inbox-placement test results linked to this sending account."
    # High score claiming health while placement is poor — the complaint this mode targets.
    if warmup >= 70 and inbox_percent < 50:
        return (
            "mismatch",
            f"Warmup score {warmup:g} looks strong but inbox placement is {inbox_percent:g}% "
            "(dashboard can look healthy while mail lands in spam).",
        )
    if warmup < 50 and inbox_percent >= 70:
        return (
            "mismatch",
            f"Warmup score {warmup:g} is weak but inbox placement is {inbox_percent:g}% "
            "(score understates placement).",
        )
    if (warmup >= 70 and inbox_percent >= 70) or (warmup < 50 and inbox_percent < 50):
        return (
            "aligned",
            f"Warmup score {warmup:g} and inbox placement {inbox_percent:g}% point the same way.",
        )
    return (
        "aligned",
        f"Warmup score {warmup:g} and inbox placement {inbox_percent:g}% are in a mid range; no strong contradiction.",
    )


def compare_warmup_to_placement(client: InstantlyClient) -> list[AccountComparison]:
    accounts = client.list_accounts()
    tests = client.list_inbox_placement_tests()

    # Map sending email -> test ids (emails[] on the test are sending accounts).
    tests_by_email: dict[str, list[str]] = {}
    all_test_ids: list[str] = []
    for t in tests:
        tid = t.get("id")
        if not tid:
            continue
        all_test_ids.append(str(tid))
        for em in t.get("emails") or []:
            if isinstance(em, str) and em.strip():
                tests_by_email.setdefault(em.strip().lower(), []).append(str(tid))

    stats_by_id: dict[str, dict[str, Any]] = {}
    if all_test_ids:
        for row in client.inbox_placement_stats_by_test_ids(all_test_ids):
            tid = row.get("test_id")
            if tid:
                stats_by_id[str(tid)] = row

    emails = [
        a["email"].strip().lower()
        for a in accounts
        if isinstance(a.get("email"), str) and a["email"].strip()
    ]
    analytics = client.warmup_analytics(emails) if emails else {"aggregate_data": {}}
    aggregate = analytics.get("aggregate_data") or {}

    reports: list[AccountComparison] = []
    for acct in accounts:
        email = (acct.get("email") or "").strip().lower()
        if not email:
            continue
        warmup = _as_float(acct.get("stat_warmup_score"))
        agg = aggregate.get(email) or aggregate.get(acct.get("email")) or {}
        health = _as_float(agg.get("health_score")) if isinstance(agg, dict) else None

        tids = tests_by_email.get(email, [])
        inbox_vals: list[float] = []
        spam_vals: list[float] = []
        for tid in tids:
            row = stats_by_id.get(tid) or {}
            ip = _as_float(row.get("inbox_percent"))
            sp = _as_float(row.get("spam_percent"))
            if ip is not None:
                inbox_vals.append(ip)
            if sp is not None:
                spam_vals.append(sp)
        inbox_pct = _mean(inbox_vals)
        spam_pct = _mean(spam_vals)
        verdict, note = verdict_for(warmup, inbox_pct)
        reports.append(AccountComparison(
            email=email,
            warmup_score=warmup,
            health_score=health,
            inbox_percent=inbox_pct,
            spam_percent=spam_pct,
            test_ids=list(tids),
            verdict=verdict,
            note=note,
        ))
    return reports


def render_comparison_markdown(reports: list[AccountComparison]) -> str:
    lines = [
        "# Instantly warmup vs inbox placement",
        "",
        "Read-only Instantly API v2 comparison. Missing scores or tests are **unknown**, never treated as healthy.",
        "Real predictive validity needs a real Instantly workspace; recorded fixtures only prove the wiring.",
        "",
    ]
    if not reports:
        lines += ["No sending accounts returned.", ""]
        return "\n".join(lines)
    lines += [
        "| Email | Warmup score | Health score | Inbox % | Spam % | Verdict |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.email}` | {_fmt(r.warmup_score)} | {_fmt(r.health_score)} | "
            f"{_fmt(r.inbox_percent)} | {_fmt(r.spam_percent)} | {r.verdict} |"
        )
    lines.append("")
    for r in reports:
        lines += [f"### `{r.email}`", "", r.note, ""]
        if r.test_ids:
            lines.append(f"Placement test ids: {', '.join(r.test_ids)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _fmt(v: float | None) -> str:
    return "unknown" if v is None else f"{v:g}"
