"""Workspace readiness: Instantly domains + Setup Doctor Findings + vitals/CTD signals.

Read-only. Instantly vitals and CTD never become Findings — they are correlated
as agree | disagree | unknown side-channel signals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from setup_doctor.checks import DEFAULT_DKIM_SELECTORS, resolve_selectors
from setup_doctor.core.models import Finding
from setup_doctor.core.result import DiagnosisResult, DiagnosisSignals
from setup_doctor.dns.resolver import Resolver, ResolverError
from setup_doctor.explain import Explainer, TemplateExplainer
from setup_doctor.pipeline import diagnose_result

from .client import InstantlyClient, InstantlyError
from .compare import (
    AccountComparison,
    compare_warmup_to_placement,
    comparisons_as_dicts,
    email_domain,
    normalize_domain,
    unique_sender_domains,
)

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class VitalsCorrelation:
    domain: str
    instantly_all_pass: bool | None
    instantly_mx: bool | None
    instantly_spf: bool | None
    instantly_dkim: bool | None
    instantly_dmarc: bool | None
    indeterminate: list[str] = field(default_factory=list)
    setup_doctor_has_auth_findings: bool | None = None
    correlation: str = "unknown"  # agree | disagree | unknown
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CtdSignal:
    host: str
    success: bool | None = None
    ssl: bool | None = None
    cname: bool | None = None
    status: str = "unknown"  # ok | fail | unknown | not_checked
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DomainReadiness:
    domain: str
    diagnosis: DiagnosisResult | None
    error: str | None
    comparisons: list[AccountComparison] = field(default_factory=list)
    vitals: VitalsCorrelation | None = None
    ctd: CtdSignal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "error": self.error,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "comparisons": comparisons_as_dicts(self.comparisons),
            "vitals": self.vitals.to_dict() if self.vitals else None,
            "ctd": self.ctd.to_dict() if self.ctd else None,
        }


@dataclass
class WorkspaceReadinessReport:
    domains: list[DomainReadiness] = field(default_factory=list)
    deliverability_agent: dict[str, Any] | None = None
    placement_insights: list[dict[str, Any]] = field(default_factory=list)
    blacklist_reports: list[dict[str, Any]] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)
    # Additive launch gate fields (schema 1.0 compatible; null/empty defaults).
    launch_verdict: str | None = None
    launch_score: int | None = None
    blocking_finding_ids: list[str] = field(default_factory=list)
    instantly_mismatches: list[str] = field(default_factory=list)
    summary_spoken: str | None = None
    esp_packs: list[str] = field(default_factory=list)
    esp_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domains": [d.to_dict() for d in self.domains],
            "deliverability_agent": self.deliverability_agent,
            "placement_insights": list(self.placement_insights),
            "blacklist_reports": list(self.blacklist_reports),
            "not_checked": list(self.not_checked),
            "launch_verdict": self.launch_verdict,
            "launch_score": self.launch_score,
            "blocking_finding_ids": list(self.blocking_finding_ids),
            "instantly_mismatches": list(self.instantly_mismatches),
            "summary_spoken": self.summary_spoken,
            "esp_packs": list(self.esp_packs),
            "esp_note": self.esp_note,
        }


def _auth_finding_ids(findings: list[Finding]) -> set[str]:
    """Finding ids that contradict Instantly 'allPass' for mx/spf/dkim/dmarc."""
    out: set[str] = set()
    for f in findings:
        fid = f.id.upper()
        if any(k in fid for k in ("SPF", "DKIM", "DMARC", "MX")):
            if f.severity in ("critical", "high", "medium"):
                out.add(f.id)
    return out


def correlate_vitals(
    domain: str,
    vitals_row: dict[str, Any] | None,
    findings: list[Finding] | None,
) -> VitalsCorrelation:
    """Compare Instantly boolean vitals to Setup Doctor Findings.

    Instantly bools stay signals. Missing vitals or indeterminate DNS on Instantly
    side => correlation unknown (never invent agree).
    """
    if vitals_row is None:
        return VitalsCorrelation(
            domain=domain,
            instantly_all_pass=None,
            instantly_mx=None,
            instantly_spf=None,
            instantly_dkim=None,
            instantly_dmarc=None,
            correlation="unknown",
            note="No Instantly vitals row for this domain.",
        )

    indeterminate = [str(x) for x in (vitals_row.get("indeterminate") or [])]
    all_pass = vitals_row.get("allPass")
    if all_pass is None:
        all_pass = vitals_row.get("all_pass")
    mx = vitals_row.get("mx")
    spf = vitals_row.get("spf")
    dkim = vitals_row.get("dkim")
    dmarc = vitals_row.get("dmarc")

    if findings is None:
        return VitalsCorrelation(
            domain=domain,
            instantly_all_pass=all_pass if isinstance(all_pass, bool) else None,
            instantly_mx=mx if isinstance(mx, bool) else None,
            instantly_spf=spf if isinstance(spf, bool) else None,
            instantly_dkim=dkim if isinstance(dkim, bool) else None,
            instantly_dmarc=dmarc if isinstance(dmarc, bool) else None,
            indeterminate=indeterminate,
            setup_doctor_has_auth_findings=None,
            correlation="unknown",
            note="Setup Doctor diagnosis missing; cannot correlate.",
        )

    if indeterminate:
        return VitalsCorrelation(
            domain=domain,
            instantly_all_pass=all_pass if isinstance(all_pass, bool) else None,
            instantly_mx=mx if isinstance(mx, bool) else None,
            instantly_spf=spf if isinstance(spf, bool) else None,
            instantly_dkim=dkim if isinstance(dkim, bool) else None,
            instantly_dmarc=dmarc if isinstance(dmarc, bool) else None,
            indeterminate=indeterminate,
            setup_doctor_has_auth_findings=bool(_auth_finding_ids(findings)),
            correlation="unknown",
            note=(
                "Instantly marked some DNS checks indeterminate (resolver failures). "
                "Re-run vitals; not treated as healthy."
            ),
        )

    has_auth = bool(_auth_finding_ids(findings))
    instantly_ok = bool(all_pass) if isinstance(all_pass, bool) else None
    if instantly_ok is None:
        correlation = "unknown"
        note = "Instantly vitals allPass missing; correlation unknown."
    elif instantly_ok and not has_auth:
        correlation = "agree"
        note = "Instantly vitals allPass and Setup Doctor found no auth issues."
    elif (not instantly_ok) and has_auth:
        correlation = "agree"
        note = "Instantly vitals failing and Setup Doctor reports auth Findings."
    elif instantly_ok and has_auth:
        correlation = "disagree"
        note = (
            "Instantly vitals allPass but Setup Doctor has auth Findings "
            "(deep DNS diagnosis disagrees with Instantly boolean check)."
        )
    else:
        # Instantly failing, Setup Doctor clean — disagree the other way
        correlation = "disagree"
        note = (
            "Instantly vitals failing but Setup Doctor found no auth Findings "
            "(check Instantly account linkage or re-run both)."
        )

    return VitalsCorrelation(
        domain=domain,
        instantly_all_pass=instantly_ok,
        instantly_mx=mx if isinstance(mx, bool) else None,
        instantly_spf=spf if isinstance(spf, bool) else None,
        instantly_dkim=dkim if isinstance(dkim, bool) else None,
        instantly_dmarc=dmarc if isinstance(dmarc, bool) else None,
        indeterminate=indeterminate,
        setup_doctor_has_auth_findings=has_auth,
        correlation=correlation,
        note=note,
    )


def _vitals_by_domain(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in ("success_list", "failure_list"):
        for row in payload.get(key) or []:
            if not isinstance(row, dict):
                continue
            d = normalize_domain(str(row.get("domain") or ""))
            if d:
                out[d] = row
    return out


def check_ctd(client: InstantlyClient, host: str | None) -> CtdSignal:
    if not host:
        return CtdSignal(
            host="",
            status="not_checked",
            note="No custom tracking domain host provided.",
        )
    host_n = normalize_domain(host) or host
    try:
        data = client.custom_tracking_domain_status(host_n)
    except InstantlyError as exc:
        return CtdSignal(
            host=host_n,
            status="unknown",
            note=f"Instantly CTD status failed (HTTP {exc.status}).",
        )
    success = data.get("success")
    ssl = data.get("ssl")
    cname = data.get("cname")
    if not isinstance(success, bool):
        return CtdSignal(
            host=host_n,
            success=None,
            ssl=ssl if isinstance(ssl, bool) else None,
            cname=cname if isinstance(cname, bool) else None,
            status="unknown",
            note="CTD response missing boolean success; treated as unknown.",
        )
    if success and ssl is not False and cname is not False:
        status = "ok"
        note = f"Custom tracking domain {host_n} reports success."
    else:
        status = "fail"
        note = (
            f"Custom tracking domain {host_n}: success={success} "
            f"ssl={ssl} cname={cname}."
        )
    return CtdSignal(
        host=host_n,
        success=success,
        ssl=ssl if isinstance(ssl, bool) else None,
        cname=cname if isinstance(cname, bool) else None,
        status=status,
        note=note,
    )


def _worst_severity(findings: list[Finding]) -> int:
    if not findings:
        return 99
    return min(SEVERITY_RANK.get(f.severity, 50) for f in findings)


def run_workspace_readiness(
    client: InstantlyClient,
    resolver: Resolver,
    explainer: Explainer | None = None,
    *,
    ctd_hosts: list[str] | None = None,
    include_rich_signals: bool = True,
    diagnose_fn: Callable[..., DiagnosisResult] | None = None,
) -> WorkspaceReadinessReport:
    """Diagnose every Instantly sender domain and attach Instantly signals."""
    explainer = explainer or TemplateExplainer()
    diagnose_fn = diagnose_fn or diagnose_result
    accounts = client.list_accounts()
    domains = unique_sender_domains(accounts)
    emails = [
        a["email"].strip().lower()
        for a in accounts
        if isinstance(a.get("email"), str) and a["email"].strip()
    ]

    comparisons = compare_warmup_to_placement(client)
    by_domain_cmp: dict[str, list[AccountComparison]] = {}
    for c in comparisons:
        d = email_domain(c.email)
        if d:
            by_domain_cmp.setdefault(d, []).append(c)

    vitals_map: dict[str, dict[str, Any]] = {}
    not_checked: list[str] = []
    try:
        vitals_payload = client.test_account_vitals(emails or None)
        vitals_map = _vitals_by_domain(vitals_payload)
    except InstantlyError:
        not_checked.append("vitals")

    from .esp import esp_limitation_note, esp_packs_for_accounts

    esp_packs = esp_packs_for_accounts(accounts)
    selectors = resolve_selectors(
        packs=esp_packs,
        defaults=DEFAULT_DKIM_SELECTORS,
    )
    esp_note = esp_limitation_note(esp_packs)

    rows: list[DomainReadiness] = []
    for domain in domains:
        diagnosis: DiagnosisResult | None = None
        error: str | None = None
        try:
            signals = DiagnosisSignals(
                instantly=comparisons_as_dicts(by_domain_cmp.get(domain, [])),
                reputation=None,
                not_checked=["reputation"],
            )
            diagnosis = diagnose_fn(
                domain, resolver, explainer, selectors, signals=signals,
            )
        except ResolverError as exc:
            error = f"resolver error (not absence): {type(exc).__name__}: {exc}"
        except ValueError as exc:
            error = str(exc)

        findings = list(diagnosis.findings) if diagnosis else None
        vitals = None
        if "vitals" not in not_checked:
            vitals = correlate_vitals(domain, vitals_map.get(domain), findings)

        rows.append(DomainReadiness(
            domain=domain,
            diagnosis=diagnosis,
            error=error,
            comparisons=list(by_domain_cmp.get(domain, [])),
            vitals=vitals,
            ctd=None,
        ))

    # CTD: one signal per provided host (workspace-level, not per domain).
    ctd_signals: list[CtdSignal] = []
    if ctd_hosts:
        for host in ctd_hosts:
            ctd_signals.append(check_ctd(client, host))
        if rows and ctd_signals:
            # Attach first CTD to each row for visibility; full list in report dict.
            for row in rows:
                row.ctd = ctd_signals[0]
    else:
        not_checked.append("ctd")

    deliverability_agent: dict[str, Any] | None = None
    placement_insights: list[dict[str, Any]] = []
    blacklist_reports: list[dict[str, Any]] = []

    if include_rich_signals:
        try:
            state = client.get_default_deliverability_agent_state()
            deliverability_agent = {"state": state}
            agent = state.get("agent") if isinstance(state, dict) else None
            agent_id = None
            if isinstance(agent, dict):
                agent_id = agent.get("id")
            if agent_id:
                try:
                    feed = client.list_deliverability_agent_feed(str(agent_id))
                    deliverability_agent["feed"] = feed
                except InstantlyError:
                    deliverability_agent["feed"] = None
                    not_checked.append("deliverability_agent_feed")
            else:
                deliverability_agent["feed"] = None
                deliverability_agent["note"] = (
                    "No default AI Deliverability Agent deployed (agent is null)."
                )
        except InstantlyError:
            not_checked.append("deliverability_agent")

        test_ids: list[str] = []
        for c in comparisons:
            test_ids.extend(c.test_ids)
        seen_tid: list[str] = []
        seen_set: set[str] = set()
        for tid in test_ids:
            if tid in seen_set:
                continue
            seen_set.add(tid)
            seen_tid.append(tid)

        for tid in seen_tid:
            try:
                placement_insights.extend(
                    client.inbox_placement_deliverability_insights(tid)
                )
            except InstantlyError:
                not_checked.append("placement_insights")
                break

        try:
            for tid in seen_tid:
                blacklist_reports.extend(
                    client.list_inbox_placement_blacklist_reports(tid)
                )
        except InstantlyError:
            not_checked.append("blacklist_reports")
    else:
        not_checked.extend([
            "deliverability_agent",
            "placement_insights",
            "blacklist_reports",
        ])

    # Sort: domains with errors / critical findings first, then Instantly mismatches.
    def sort_key(row: DomainReadiness) -> tuple[int, int, str]:
        if row.error:
            return (0, 0, row.domain)
        findings = row.diagnosis.findings if row.diagnosis else []
        sev = _worst_severity(findings)
        mismatch = 0 if any(c.verdict == "mismatch" for c in row.comparisons) else 1
        return (1, sev * 10 + mismatch, row.domain)

    rows.sort(key=sort_key)

    report = WorkspaceReadinessReport(
        domains=rows,
        deliverability_agent=deliverability_agent,
        placement_insights=placement_insights,
        blacklist_reports=blacklist_reports,
        not_checked=not_checked,
        esp_packs=list(esp_packs),
        esp_note=esp_note,
    )
    # Stash all CTD signals on deliverability_agent-adjacent: expose via to_dict extension
    if ctd_signals:
        # Attach under a stable key without breaking DomainReadiness
        report.deliverability_agent = report.deliverability_agent or {}
        if isinstance(report.deliverability_agent, dict):
            report.deliverability_agent = {
                **report.deliverability_agent,
                "ctd_hosts": [c.to_dict() for c in ctd_signals],
            }
    from .launch import attach_launch_decision

    attach_launch_decision(report)
    return report


def render_readiness_markdown(report: WorkspaceReadinessReport) -> str:
    lines = [
        "# Instantly workspace readiness",
        "",
        "Setup Doctor DNS Findings plus Instantly warmup/placement, vitals correlation, "
        "and optional CTD. Missing Instantly data is **unknown**, never treated as healthy. "
        "Instantly vitals never invent Findings.",
        "",
    ]
    if report.launch_verdict:
        lines.append(f"**Launch verdict:** `{report.launch_verdict}`")
        if report.summary_spoken:
            lines.append("")
            lines.append(report.summary_spoken)
        lines.append("")
    if report.esp_packs:
        lines.append(f"ESP selector packs: `{', '.join(report.esp_packs)}`")
        if report.esp_note:
            lines.append(f"_{report.esp_note}_")
        lines.append("")
    if report.not_checked:
        lines.append(f"Not checked: {', '.join(report.not_checked)}")
        lines.append("")
    agent = report.deliverability_agent
    if isinstance(agent, dict) and (agent.get("state") or agent.get("note") or agent.get("feed")):
        lines += [
            "> If Instantly's AI Deliverability Agent recommends pause, quote that "
            "recommendation; Setup Doctor explains DNS depth and does **not** auto-pause.",
            "",
        ]

    if not report.domains:
        lines += ["No sending-account domains found in the Instantly workspace.", ""]
        return "\n".join(lines)

    lines += [
        "| Domain | Diagnosis | Instantly mismatches | Vitals correlation |",
        "|---|---|---:|---|",
    ]
    for row in report.domains:
        if row.error:
            diag = f"error: {row.error}"
            findings_n = "—"
        else:
            n = len(row.diagnosis.findings) if row.diagnosis else 0
            findings_n = str(n)
            diag = f"{n} finding(s)"
        mismatches = sum(1 for c in row.comparisons if c.verdict == "mismatch")
        corr = row.vitals.correlation if row.vitals else "unknown"
        lines.append(
            f"| `{row.domain}` | {diag} | {mismatches} | {corr} |"
        )
        _ = findings_n

    lines.append("")
    for row in report.domains:
        lines += [f"## `{row.domain}`", ""]
        if row.error:
            lines += [row.error, ""]
            continue
        assert row.diagnosis is not None
        if row.diagnosis.findings:
            lines.append("### Setup Doctor findings")
            lines.append("")
            for f in row.diagnosis.findings:
                lines.append(f"- **[{f.id}]** ({f.severity}) {f.title}")
            lines.append("")
        else:
            lines += ["No Setup Doctor auth Findings.", ""]
        if row.vitals:
            lines += [
                "### Instantly vitals correlation",
                "",
                f"- Correlation: **{row.vitals.correlation}**",
                f"- {row.vitals.note}",
                "",
            ]
        if row.comparisons:
            lines.append("### Warmup vs placement")
            lines.append("")
            for c in row.comparisons:
                lines.append(f"- `{c.email}`: **{c.verdict}** — {c.note}")
            lines.append("")
        if row.ctd and row.ctd.status != "not_checked":
            lines += [
                "### Custom tracking domain",
                "",
                f"- `{row.ctd.host}`: **{row.ctd.status}** — {row.ctd.note}",
                "",
            ]

    agent = report.deliverability_agent
    if isinstance(agent, dict):
        lines += ["## Instantly AI Deliverability Agent", ""]
        if agent.get("note"):
            lines.append(str(agent["note"]))
        elif agent.get("state") is not None:
            feed = agent.get("feed")
            if feed is None:
                lines.append("Agent state retrieved; feed not available or empty.")
            else:
                lines.append(f"Feed items: {len(feed) if isinstance(feed, list) else 'unknown'}.")
        lines.append("")

    if report.placement_insights:
        lines += [
            "## Placement deliverability insights",
            "",
            f"{len(report.placement_insights)} insight row(s) from Instantly "
            "(see JSON for full detail).",
            "",
        ]
    if report.blacklist_reports:
        lines += [
            "## Blacklist / SpamAssassin reports",
            "",
            f"{len(report.blacklist_reports)} report(s) listed (see JSON for full detail).",
            "",
        ]

    return "\n".join(lines).rstrip() + "\n"
