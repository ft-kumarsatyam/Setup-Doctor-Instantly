"""Deterministic Instantly launch verdict + pre-launch gate.

Never maps missing Instantly data → ready. LLM must not invent allowed_to_activate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from setup_doctor.core.models import Finding
from setup_doctor.core.result import SCHEMA_VERSION

from .readiness import WorkspaceReadinessReport

LAUNCH_VERDICTS = frozenset({"blocked", "caution", "ready", "unknown"})


@dataclass
class LaunchDecision:
    launch_verdict: str
    launch_score: int | None = None  # always null until calibrated
    blocking_finding_ids: list[str] = field(default_factory=list)
    caution_finding_ids: list[str] = field(default_factory=list)
    instantly_mismatches: list[str] = field(default_factory=list)
    vitals_disagreements: list[str] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)
    instantly_checked: bool = False
    domain_errors: list[str] = field(default_factory=list)
    summary_spoken: str = ""

    @property
    def allowed_to_activate(self) -> bool:
        return self.launch_verdict == "ready"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allowed_to_activate"] = self.allowed_to_activate
        return d


def _collect_findings(report: WorkspaceReadinessReport) -> list[Finding]:
    out: list[Finding] = []
    for row in report.domains:
        if row.diagnosis:
            out.extend(row.diagnosis.findings)
    return out


def compute_launch_decision(report: WorkspaceReadinessReport) -> LaunchDecision:
    """Derive launch_verdict solely from Findings + Instantly signal verdicts."""
    findings = _collect_findings(report)
    blocking = sorted({f.id for f in findings if f.severity == "critical"})
    caution_ids = sorted({
        f.id for f in findings if f.severity in ("high", "medium")
    })
    mismatches: list[str] = []
    disagreements: list[str] = []
    domain_errors: list[str] = []
    instantly_checked = False

    for row in report.domains:
        if row.error:
            domain_errors.append(f"{row.domain}: {row.error}")
        for c in row.comparisons:
            instantly_checked = True
            if c.verdict == "mismatch":
                mismatches.append(f"{c.email}: {c.note}")
            elif c.verdict == "aligned":
                pass
            # unknown verdict does not count as checked-healthy
        if row.vitals:
            instantly_checked = True
            if row.vitals.correlation == "disagree":
                disagreements.append(f"{row.domain}: {row.vitals.note}")
        if row.diagnosis and row.diagnosis.signals and row.diagnosis.signals.instantly:
            instantly_checked = True

    not_checked = list(report.not_checked)

    verdict = _finalize_verdict(
        blocking=blocking,
        caution_ids=caution_ids,
        findings=findings,
        mismatches=mismatches,
        disagreements=disagreements,
        domain_errors=domain_errors,
        instantly_checked=instantly_checked,
    )

    decision = LaunchDecision(
        launch_verdict=verdict,
        launch_score=None,
        blocking_finding_ids=blocking,
        caution_finding_ids=caution_ids,
        instantly_mismatches=mismatches,
        vitals_disagreements=disagreements,
        not_checked=not_checked,
        instantly_checked=instantly_checked,
        domain_errors=domain_errors,
    )
    decision.summary_spoken = render_summary_spoken(decision, report)
    return decision


def _finalize_verdict(
    *,
    blocking: list[str],
    caution_ids: list[str],
    findings: list[Finding],
    mismatches: list[str],
    disagreements: list[str],
    domain_errors: list[str],
    instantly_checked: bool,
) -> str:
    if blocking:
        return "blocked"
    if caution_ids or mismatches or disagreements:
        return "caution"
    if domain_errors:
        return "unknown"
    if not instantly_checked:
        return "unknown"
    # Instantly checked, no critical/high/medium, no mismatch/disagree
    _ = findings  # low/info findings do not block ready
    return "ready"


def render_summary_spoken(
    decision: LaunchDecision,
    report: WorkspaceReadinessReport,
) -> str:
    """2–4 sentence speakable summary grounded in Findings + Instantly notes."""
    n_domains = len(report.domains)
    if decision.launch_verdict == "blocked":
        ids = ", ".join(decision.blocking_finding_ids) or "critical Findings"
        return (
            f"Launch is blocked for this Instantly workspace ({n_domains} domain(s)). "
            f"Critical Setup Doctor Findings: {ids}. "
            "Fix DNS before activating campaigns. "
            "Missing Instantly data is never treated as healthy."
        )
    if decision.launch_verdict == "caution":
        parts = []
        if decision.caution_finding_ids:
            parts.append(
                "high/medium Findings " + ", ".join(decision.caution_finding_ids[:5])
            )
        if decision.instantly_mismatches:
            parts.append(
                f"{len(decision.instantly_mismatches)} Instantly warmup/placement mismatch(es)"
            )
        if decision.vitals_disagreements:
            parts.append(
                f"{len(decision.vitals_disagreements)} vitals disagreement(s)"
            )
        detail = "; ".join(parts) if parts else "caution signals"
        return (
            f"Launch looks cautionary across {n_domains} domain(s): {detail}. "
            "Resolve Setup Doctor Findings and Instantly mismatches before activate. "
            "Do not treat unknown Instantly scores as healthy."
        )
    if decision.launch_verdict == "unknown":
        reason = "Instantly signals were not fully checked"
        if decision.domain_errors:
            reason = "one or more domains failed diagnosis"
        if decision.not_checked:
            reason += f" (not checked: {', '.join(decision.not_checked[:5])})"
        return (
            f"Launch readiness is unknown for {n_domains} domain(s): {reason}. "
            "Setup Doctor will not report ready without Instantly checks. "
            "Re-run with Instantly credentials and fix any resolver errors first."
        )
    return (
        f"Launch looks ready for {n_domains} Instantly domain(s): "
        "no critical/high/medium auth Findings and no Instantly mismatches. "
        "Confirm Instantly placement still looks good, then activate via Instantly — "
        "Setup Doctor stays read-only."
    )


def attach_launch_decision(report: WorkspaceReadinessReport) -> LaunchDecision:
    """Compute decision and stamp additive fields onto the report object."""
    decision = compute_launch_decision(report)
    report.launch_verdict = decision.launch_verdict
    report.launch_score = decision.launch_score
    report.blocking_finding_ids = list(decision.blocking_finding_ids)
    report.instantly_mismatches = list(decision.instantly_mismatches)
    report.summary_spoken = decision.summary_spoken
    return decision


def build_pre_launch_gate(
    report: WorkspaceReadinessReport,
    *,
    domain_filter: str | None = None,
) -> dict[str, Any]:
    """MCP/API contract for pre_launch_gate."""
    filtered = report
    if domain_filter:
        want = domain_filter.strip().lower().rstrip(".")
        rows = [r for r in report.domains if r.domain == want]
        filtered = WorkspaceReadinessReport(
            domains=rows,
            deliverability_agent=report.deliverability_agent,
            placement_insights=report.placement_insights,
            blacklist_reports=report.blacklist_reports,
            not_checked=list(report.not_checked),
        )
    decision = compute_launch_decision(filtered)
    from .readiness import render_readiness_markdown

    md = render_readiness_markdown(filtered)
    md = (
        f"**Launch verdict: `{decision.launch_verdict}`** — "
        f"allowed_to_activate={decision.allowed_to_activate}\n\n"
        f"{decision.summary_spoken}\n\n"
        + md
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "allowed_to_activate": decision.allowed_to_activate,
        "launch_verdict": decision.launch_verdict,
        "launch_score": decision.launch_score,
        "blocking_finding_ids": decision.blocking_finding_ids,
        "caution_finding_ids": decision.caution_finding_ids,
        "instantly_mismatches": decision.instantly_mismatches,
        "vitals_disagreements": decision.vitals_disagreements,
        "not_checked": decision.not_checked,
        "summary_spoken": decision.summary_spoken,
        "markdown": md,
        "report": filtered.to_dict(),
    }


def verify_pre_launch_gate_honesty(payload: dict[str, Any]) -> list[str]:
    """Guardrail: reject inventing allowed_to_activate=true with critical Findings."""
    violations: list[str] = []
    allowed = bool(payload.get("allowed_to_activate"))
    verdict = payload.get("launch_verdict")
    blocking = list(payload.get("blocking_finding_ids") or [])
    if allowed and verdict != "ready":
        violations.append(
            f"allowed_to_activate true requires launch_verdict=ready (got {verdict!r})"
        )
    if allowed and blocking:
        violations.append(
            "allowed_to_activate true while blocking_finding_ids non-empty: "
            + ", ".join(blocking)
        )
    if verdict == "blocked" and allowed:
        violations.append("blocked verdict cannot allow activate")
    if verdict == "ready" and not allowed:
        violations.append("ready verdict must set allowed_to_activate true")
    return violations
