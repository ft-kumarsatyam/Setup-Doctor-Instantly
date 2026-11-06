"""Action card for Instantly's Deliverability Agent.

Setup Doctor does not pause, activate, or send. The card quotes Findings and
whether Instantly has a default agent deployed. Missing agent state stays null.
"""
from __future__ import annotations

from typing import Any

from setup_doctor.core.models import Finding
from setup_doctor.core.result import SCHEMA_VERSION

from .launch import _finalize_verdict, compute_launch_decision

_HOLD = "hold"
_REVIEW = "review"
_CLEAR = "clear"
_UNKNOWN = "unknown"


def _agent_status(blob: dict[str, Any] | None, not_checked: list[str]) -> dict[str, Any]:
    unread = "deliverability_agent" in not_checked
    if blob is None or (unread and "state" not in blob):
        return {
            "deployed": None,
            "id": None,
            "feed_items": None,
            "note": "Deliverability Agent state was not read. That is unknown, not healthy.",
        }
    state = blob.get("state") if isinstance(blob.get("state"), dict) else blob
    agent = state.get("agent") if isinstance(state, dict) else None
    if not isinstance(agent, dict) or not agent.get("id"):
        return {
            "deployed": False,
            "id": None,
            "feed_items": None,
            "note": "No default Deliverability Agent is deployed in this workspace.",
        }
    feed = blob.get("feed")
    return {
        "deployed": True,
        "id": str(agent["id"]),
        "feed_items": len(feed) if isinstance(feed, list) else None,
        "note": "Quoted from Instantly. Setup Doctor does not pause accounts or activate campaigns.",
    }


def build_agent_handoff(
    findings: list[Finding],
    *,
    instantly_checked: bool = False,
    mismatches: list[str] | None = None,
    disagreements: list[str] | None = None,
    domain_errors: list[str] | None = None,
    agent_blob: dict[str, Any] | None = None,
    not_checked: list[str] | None = None,
    launch_verdict: str | None = None,
) -> dict[str, Any]:
    """One payload an agent can follow. Actions are instructions, not API calls."""
    blocking = sorted({f.id for f in findings if f.severity == "critical"})
    caution_ids = sorted({f.id for f in findings if f.severity in ("high", "medium")})
    checked = list(not_checked or [])
    verdict = launch_verdict or _finalize_verdict(
        blocking=blocking,
        caution_ids=caution_ids,
        findings=findings,
        mismatches=list(mismatches or []),
        disagreements=list(disagreements or []),
        domain_errors=list(domain_errors or []),
        instantly_checked=instantly_checked,
    )
    actions: list[dict[str, Any]] = []
    for finding in findings:
        if finding.severity == "critical":
            actions.append({
                "action": "do_not_activate",
                "finding_id": finding.id,
                "severity": finding.severity,
            })
        elif finding.severity in ("high", "medium"):
            actions.append({
                "action": "review_before_launch",
                "finding_id": finding.id,
                "severity": finding.severity,
            })
    if verdict == "blocked":
        act = _HOLD
    elif verdict == "caution":
        act = _REVIEW
    elif verdict == "ready":
        act = _CLEAR
        actions.append({"action": "may_activate", "finding_id": None, "severity": None})
    else:
        act = _UNKNOWN
    agent = _agent_status(agent_blob, checked)
    if act == _HOLD:
        spoken = (
            "Hold activation. Critical Findings: "
            + (", ".join(blocking) or "see actions")
            + ". Do not treat a missing Deliverability Agent as healthy."
        )
    elif act == _REVIEW:
        spoken = (
            "Review before launch. Caution Findings: "
            + (", ".join(caution_ids) or "Instantly signal")
            + "."
        )
    elif act == _CLEAR:
        spoken = "No critical, high, or medium Findings, and Instantly signals do not disagree. Activation is allowed."
    else:
        spoken = "Activation stays unknown. Missing Instantly or DNS data is not a clear launch."
    return {
        "schema_version": SCHEMA_VERSION,
        "agent": "deliverability_handoff",
        "act": act,
        "allowed_to_activate": act == _CLEAR,
        "launch_verdict": verdict,
        "blocking_finding_ids": blocking,
        "caution_finding_ids": caution_ids,
        "actions": actions,
        "instantly_agent": agent,
        "not_checked": checked,
        "summary_spoken": spoken,
        "note": "Read-only. This payload does not pause, activate, or send mail.",
    }


def handoff_from_readiness(report: Any) -> dict[str, Any]:
    """Build the card from a workspace readiness report, including agent state."""
    verdict = report.launch_verdict
    if not verdict:
        verdict = compute_launch_decision(report).launch_verdict
    findings: list[Finding] = []
    mismatches: list[str] = []
    disagreements: list[str] = []
    errors: list[str] = []
    instantly_checked = False
    for row in report.domains:
        if row.error:
            errors.append(f"{row.domain}: {row.error}")
        if row.diagnosis:
            findings.extend(row.diagnosis.findings)
        for comparison in row.comparisons:
            instantly_checked = True
            if comparison.verdict == "mismatch":
                mismatches.append(f"{comparison.email}: {comparison.note}")
        if row.vitals:
            instantly_checked = True
            if row.vitals.correlation == "disagree":
                disagreements.append(f"{row.domain}: {row.vitals.note}")
    blob = report.deliverability_agent if isinstance(report.deliverability_agent, dict) else None
    return build_agent_handoff(
        findings,
        instantly_checked=instantly_checked,
        mismatches=mismatches,
        disagreements=disagreements,
        domain_errors=errors,
        agent_blob=blob,
        not_checked=list(report.not_checked),
        launch_verdict=verdict,
    )


def verify_agent_handoff(payload: dict[str, Any]) -> list[str]:
    """A clear act must not sit on top of a do-not-activate action."""
    violations: list[str] = []
    actions = payload.get("actions") or []
    holds = [
        row.get("finding_id")
        for row in actions
        if isinstance(row, dict) and row.get("action") == "do_not_activate"
    ]
    if payload.get("act") == _CLEAR and holds:
        violations.append("clear act while do_not_activate is present")
    if payload.get("allowed_to_activate") and holds:
        violations.append("allowed_to_activate while do_not_activate is present")
    if payload.get("act") == _CLEAR and payload.get("launch_verdict") not in (None, "ready"):
        violations.append("clear act without launch_verdict ready")
    agent = payload.get("instantly_agent")
    if isinstance(agent, dict) and agent.get("deployed") is True and not agent.get("id"):
        violations.append("deployed agent with no id")
    return violations
