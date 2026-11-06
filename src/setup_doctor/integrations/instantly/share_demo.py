"""Offline demo of the gap Instantly's boolean DNS check does not close.

Frozen records for ``client.test`` all exist, so a vitals-style check reports
``allPass``. The same records are still a critical SPF problem. A scripted
model then tries to soften the result; the verifier rejects it and the
template stands. No network and no API keys.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.integrations.instantly.client import InstantlyClient, RecordingTransport
from setup_doctor.integrations.instantly.launch import build_pre_launch_gate
from setup_doctor.integrations.instantly.readiness import run_workspace_readiness

DOMAIN = "client.test"
EMAIL = "sender@client.test"

# Same 1024-bit fixture key as evals/detection/fixtures.py (below RFC 8301).
_DKIM_P_1024 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCzX7QtE91+aVHFcIV82S12Thrc"
    "VxO0Dh39MurQD37tT8mY5FxEzl8zzVsfbFJsH8c6bOqrd7SIZTiPQNaO2WI/dqC6"
    "r+VULdITDNF8ZbN0lpkwYhWymc22cAAYgRwHPf7tI2yFm/RsxxhANDQsbuXgW2y9"
    "CF90eo/6kEq4C9yAFwIDAQAB"
)


def gap_records() -> dict[str, dict[str, list[str]]]:
    """Records that exist, and are still wrong for a cold-email launch."""
    return {
        DOMAIN: {
            "TXT": ["v=spf1 +all"],
            "MX": ["mail.client.test"],
        },
        f"_dmarc.{DOMAIN}": {
            "TXT": [f"v=DMARC1; p=none; rua=mailto:dmarc@{DOMAIN}"],
        },
        f"google._domainkey.{DOMAIN}": {
            "TXT": [f"v=DKIM1; k=rsa; p={_DKIM_P_1024}"],
        },
    }


def gap_client() -> InstantlyClient:
    """Recorded Instantly workspace: vitals all pass, warmup strong, inbox weak."""
    routes: dict[tuple[str, str], tuple[int, Any]] = {
        ("GET", "/accounts"): (
            200,
            {
                "items": [{"email": EMAIL, "stat_warmup_score": 95}],
                "next_starting_after": None,
            },
        ),
        ("GET", "/inbox-placement-tests"): (
            200,
            {
                "items": [{"id": "test-gap", "emails": [EMAIL]}],
                "next_starting_after": None,
            },
        ),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (
            200,
            [{
                "test_id": "test-gap",
                "inbox_percent": 20,
                "spam_percent": 80,
                "inbox_count": 2,
                "spam_count": 8,
                "count": 10,
            }],
        ),
        ("POST", "/accounts/warmup-analytics"): (
            200,
            {
                "aggregate_data": {
                    EMAIL: {"health_score": 90, "sent": 10, "landed_inbox": 2, "landed_spam": 8},
                },
                "email_date_data": {},
            },
        ),
        ("POST", "/accounts/test/vitals"): (
            200,
            {
                "status": "success",
                "success_list": [{
                    "domain": DOMAIN,
                    "allPass": True,
                    "mx": True,
                    "spf": True,
                    "dkim": True,
                    "dmarc": True,
                    "indeterminate": [],
                }],
                "failure_list": [],
            },
        ),
    }
    return InstantlyClient(
        api_key="share-demo-not-a-live-key",
        base_url="https://example.test/api/v2",
        transport=RecordingTransport(routes),
        sleep=lambda _seconds: None,
    )


def _liar_rewrite(_prompt: str) -> str:
    """Scripted model: invents a score and calls a broken mailbox healthy."""
    return json.dumps([{
        "email": EMAIL,
        "summary": "This mailbox is healthy. Warmup score 100 and inbox 99%.",
    }])


@dataclass
class ShareDemo:
    domain: str
    instantly_all_pass: bool
    finding_ids: list[str]
    vitals_correlation: str
    warmup_verdict: str
    launch_verdict: str
    allowed_to_activate: bool
    summary_spoken: str
    ai_rewrite_source: str
    ai_rewrite_violations: list[str]
    ai_plan_violations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "instantly_all_pass": self.instantly_all_pass,
            "finding_ids": list(self.finding_ids),
            "vitals_correlation": self.vitals_correlation,
            "warmup_verdict": self.warmup_verdict,
            "launch_verdict": self.launch_verdict,
            "allowed_to_activate": self.allowed_to_activate,
            "summary_spoken": self.summary_spoken,
            "ai_rewrite_source": self.ai_rewrite_source,
            "ai_rewrite_violations": list(self.ai_rewrite_violations),
            "ai_plan_violations": list(self.ai_plan_violations),
            "note": (
                "Offline fixture. Instantly boolean vitals can pass while "
                "Setup Doctor still blocks activate. The model does not decide the gate."
            ),
        }


def run_share_demo() -> ShareDemo:
    """Run the gap once. Safe to call from tests and from the CLI."""
    from setup_doctor.explain.explainer import TemplateExplainer, verify_plan
    from setup_doctor.explain.instantly_rewrite import rewrite_instantly_signals

    report = run_workspace_readiness(
        gap_client(),
        FixtureResolver(gap_records()),
        TemplateExplainer(),
        include_rich_signals=False,
    )
    gate = build_pre_launch_gate(report, domain_filter=DOMAIN)
    row = next(r for r in report.domains if r.domain == DOMAIN)
    findings = list(row.diagnosis.findings) if row.diagnosis else []
    _md, source, rewrite_violations = rewrite_instantly_signals(row.comparisons, _liar_rewrite)
    plan_violations = verify_plan(
        [{"id": "SPF_MISSING", "explanation": "SPF is missing, so the domain is fine."}],
        findings,
    )
    vitals = row.vitals
    warmup = row.comparisons[0].verdict if row.comparisons else "unknown"
    return ShareDemo(
        domain=DOMAIN,
        instantly_all_pass=bool(vitals and vitals.instantly_all_pass),
        finding_ids=sorted(f.id for f in findings),
        vitals_correlation=vitals.correlation if vitals else "unknown",
        warmup_verdict=warmup,
        launch_verdict=str(gate["launch_verdict"]),
        allowed_to_activate=bool(gate["allowed_to_activate"]),
        summary_spoken=str(gate["summary_spoken"]),
        ai_rewrite_source=source,
        ai_rewrite_violations=list(rewrite_violations),
        ai_plan_violations=list(plan_violations),
    )


def render_share_demo(demo: ShareDemo) -> str:
    """Plain-text card for a partner read-through. No JSON required."""
    findings = ", ".join(demo.finding_ids) or "(none)"
    return "\n".join([
        "Setup Doctor × Instantly — offline gap demo",
        f"Domain: {demo.domain}",
        "No live Instantly key. No model API. Frozen DNS plus a recorded Instantly response.",
        "",
        "Instantly account vitals (the boolean Test domain setup shape):",
        "  allPass=true   mx=true   spf=true   dkim=true   dmarc=true",
        "The four records exist, so that check passes.",
        "",
        "What the records actually say:",
        "  SPF ends with +all          → SPF_PLUS_ALL (critical)",
        "  DKIM key is 1024-bit        → DKIM_WEAK_KEY (medium)",
        "  DMARC policy is p=none      → DMARC_POLICY_NONE (low)",
        f"  Findings: {findings}",
        "",
        f"Vitals correlation: {demo.vitals_correlation}",
        f"Warmup vs inbox placement: {demo.warmup_verdict} (warmup 95, inbox 20%)",
        "",
        f"Launch verdict: {demo.launch_verdict}",
        f"allowed_to_activate: {str(demo.allowed_to_activate).lower()}",
        "",
        demo.summary_spoken,
        "",
        "AI check (scripted model, not a live call):",
        "  It called the mailbox healthy and invented warmup 100 / inbox 99%.",
        f"  Instantly rewrite: {demo.ai_rewrite_source}",
        "  It also tried to add a finding SPF_MISSING.",
        "  DNS plan rejected: "
        + ("yes" if demo.ai_plan_violations else "no"),
        "  The gate and the finding list did not change.",
        "",
    ])
