"""Launch verdict, pre-launch gate honesty, fix packets."""
from __future__ import annotations

from setup_doctor.core.models import Finding
from setup_doctor.core.result import DiagnosisResult
from setup_doctor.explain.fix_packets import build_fix_packet, verify_fix_packet
from setup_doctor.integrations.instantly.compare import AccountComparison
from setup_doctor.integrations.instantly.launch import (
    build_pre_launch_gate,
    compute_launch_decision,
    verify_pre_launch_gate_honesty,
)
from setup_doctor.integrations.instantly.readiness import (
    DomainReadiness,
    VitalsCorrelation,
    WorkspaceReadinessReport,
)


def _finding(fid: str, severity: str = "critical") -> Finding:
    return Finding(
        id=fid,
        severity=severity,
        title=f"{fid} title",
        why="why",
        fix="Publish `v=spf1 include:_spf.google.com -all` at apex.",
        evidence={"record": "v=spf1 include:_spf.google.com -all"},
    )


def _diag(*findings: Finding) -> DiagnosisResult:
    return DiagnosisResult(
        domain="ex.test",
        findings=list(findings),
        explanation="",
        explanation_source="template",
        report="report",
    )


def test_critical_finding_blocks_launch():
    report = WorkspaceReadinessReport(
        domains=[DomainReadiness(
            domain="ex.test",
            diagnosis=_diag(_finding("SPF_MISSING")),
            error=None,
            comparisons=[AccountComparison(
                email="a@ex.test",
                warmup_score=90,
                inbox_percent=90,
                health_score=90,
                spam_percent=5,
                verdict="aligned",
                note="ok",
                test_ids=[],
            )],
            vitals=VitalsCorrelation(
                domain="ex.test",
                instantly_all_pass=True,
                instantly_mx=True,
                instantly_spf=True,
                instantly_dkim=True,
                instantly_dmarc=True,
                correlation="disagree",
                note="disagree",
            ),
        )],
    )
    d = compute_launch_decision(report)
    assert d.launch_verdict == "blocked"
    assert d.allowed_to_activate is False
    assert "SPF_MISSING" in d.blocking_finding_ids


def test_missing_instantly_never_ready():
    report = WorkspaceReadinessReport(
        domains=[DomainReadiness(
            domain="ex.test",
            diagnosis=_diag(),
            error=None,
            comparisons=[],
            vitals=None,
        )],
    )
    d = compute_launch_decision(report)
    assert d.launch_verdict == "unknown"
    assert d.allowed_to_activate is False


def test_ready_when_clean_and_instantly_checked():
    report = WorkspaceReadinessReport(
        domains=[DomainReadiness(
            domain="ex.test",
            diagnosis=_diag(),
            error=None,
            comparisons=[AccountComparison(
                email="a@ex.test",
                warmup_score=90,
                inbox_percent=90,
                health_score=90,
                spam_percent=5,
                verdict="aligned",
                note="ok",
                test_ids=[],
            )],
        )],
    )
    d = compute_launch_decision(report)
    assert d.launch_verdict == "ready"
    assert d.allowed_to_activate is True


def test_gate_honesty_rejects_invented_allow():
    bad = {
        "allowed_to_activate": True,
        "launch_verdict": "blocked",
        "blocking_finding_ids": ["SPF_MISSING"],
    }
    assert verify_pre_launch_gate_honesty(bad)
    good = build_pre_launch_gate(WorkspaceReadinessReport(domains=[
        DomainReadiness(
            domain="ex.test",
            diagnosis=_diag(_finding("SPF_MISSING")),
            error=None,
            comparisons=[AccountComparison(
                email="a@ex.test",
                warmup_score=1,
                inbox_percent=1,
                health_score=1,
                spam_percent=90,
                verdict="mismatch",
                note="bad",
                test_ids=[],
            )],
        ),
    ]))
    assert good["allowed_to_activate"] is False
    assert verify_pre_launch_gate_honesty(good) == []


def test_cloudflare_fix_packet_grounds_records():
    findings = [_finding("SPF_PLUS_ALL", "critical")]
    packet = build_fix_packet("mess.test", findings, provider="cloudflare")
    assert packet.provider == "cloudflare"
    assert packet.finding_ids == ["SPF_PLUS_ALL"]
    assert verify_fix_packet(packet, findings) == []
    invented = build_fix_packet("mess.test", findings, provider="cloudflare")
    invented.steps[0]["record"] = "v=spf1 invent:evil.test -all"
    assert verify_fix_packet(invented, findings)
