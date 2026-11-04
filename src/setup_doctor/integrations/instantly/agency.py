"""White-label agency export from Instantly workspace readiness."""
from __future__ import annotations

from typing import Any

from .launch import compute_launch_decision
from .readiness import WorkspaceReadinessReport, render_readiness_markdown


def render_agency_report(
    report: WorkspaceReadinessReport,
    *,
    client_name: str = "Client",
    agency_name: str = "Agency",
    include_spoken: bool = True,
) -> str:
    """Markdown handoff snapshot — Instantly owns placement; Setup Doctor owns DNS."""
    decision = compute_launch_decision(report)
    lines = [
        f"# {agency_name} → {client_name}: Instantly pre-launch DNS report",
        "",
        "Prepared with **Setup Doctor** (DNS Findings) beside **Instantly** "
        "(warmup / placement / Deliverability Agent). "
        "Setup Doctor is read-only on Instantly — it never pauses accounts or "
        "activates campaigns.",
        "",
        f"**Launch verdict:** `{decision.launch_verdict}`",
        f"**Allowed to activate:** `{decision.allowed_to_activate}`",
        "",
    ]
    if include_spoken and decision.summary_spoken:
        lines += [decision.summary_spoken, ""]
    if decision.blocking_finding_ids:
        lines.append("## Blocking Findings")
        lines.append("")
        for fid in decision.blocking_finding_ids:
            lines.append(f"- `{fid}`")
        lines.append("")
    if decision.instantly_mismatches:
        lines.append("## Instantly mismatches")
        lines.append("")
        for m in decision.instantly_mismatches:
            lines.append(f"- {m}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(render_readiness_markdown(report))
    lines += [
        "",
        "---",
        "",
        "_Missing Instantly scores stay **unknown**, never healthy. "
        "Outage ≠ absence of DNS records._",
        "",
    ]
    return "\n".join(lines)


def agency_report_payload(
    report: WorkspaceReadinessReport,
    *,
    client_name: str = "Client",
    agency_name: str = "Agency",
) -> dict[str, Any]:
    decision = compute_launch_decision(report)
    return {
        "client_name": client_name,
        "agency_name": agency_name,
        "launch_verdict": decision.launch_verdict,
        "allowed_to_activate": decision.allowed_to_activate,
        "markdown": render_agency_report(
            report, client_name=client_name, agency_name=agency_name,
        ),
        "report": report.to_dict(),
    }
