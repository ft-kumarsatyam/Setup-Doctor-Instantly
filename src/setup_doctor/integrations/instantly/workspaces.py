"""Agency multi-workspace readiness (workspace-group admin key).

Uses Instantly ``GET /workspace-group-members`` + ``x-as-workspace`` header.
Scopes: workspaces:read (current) + workspace-group access. On failure ⇒
``unknown`` / ``not_checked`` — never invent sub-workspaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from setup_doctor.dns.resolver import Resolver, ResolverError
from setup_doctor.explain import Explainer, TemplateExplainer
from setup_doctor.pipeline import diagnose_result

from .client import InstantlyClient, InstantlyError
from .launch import compute_launch_decision
from .readiness import WorkspaceReadinessReport, run_workspace_readiness


@dataclass
class WorkspaceReadyRow:
    workspace_id: str | None
    workspace_name: str | None
    ok: bool
    error: str | None = None
    launch_verdict: str | None = None
    allowed_to_activate: bool | None = None
    report: WorkspaceReadinessReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "ok": self.ok,
            "error": self.error,
            "launch_verdict": self.launch_verdict,
            "allowed_to_activate": self.allowed_to_activate,
            "report": self.report.to_dict() if self.report else None,
        }


@dataclass
class AgencyReadinessReport:
    admin_workspace: dict[str, Any] | None = None
    workspaces: list[WorkspaceReadyRow] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)
    note: str = (
        "Agency multi-workspace uses Instantly workspace-group members + "
        "x-as-workspace. Missing group access ⇒ not_checked, never invented."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admin_workspace": self.admin_workspace,
            "workspaces": [w.to_dict() for w in self.workspaces],
            "not_checked": list(self.not_checked),
            "note": self.note,
            "blocked_count": sum(
                1 for w in self.workspaces if w.launch_verdict == "blocked"
            ),
            "ready_count": sum(
                1 for w in self.workspaces if w.launch_verdict == "ready"
            ),
            "unknown_count": sum(
                1 for w in self.workspaces
                if w.launch_verdict in (None, "unknown") or not w.ok
            ),
        }


def render_agency_workspaces_markdown(report: AgencyReadinessReport) -> str:
    lines = [
        "# Agency Instantly workspaces readiness",
        "",
        report.note,
        "",
    ]
    if report.not_checked:
        lines += [f"Not checked: {', '.join(report.not_checked)}", ""]
    if report.admin_workspace:
        name = report.admin_workspace.get("name") or report.admin_workspace.get("id")
        lines += [f"Admin workspace: **{name}**", ""]
    if not report.workspaces:
        lines += ["No sub-workspaces found (or workspace-group not available).", ""]
        return "\n".join(lines)
    lines += [
        "| Workspace | Verdict | Allowed |",
        "|---|---|---|",
    ]
    for row in report.workspaces:
        label = row.workspace_name or row.workspace_id or "?"
        if not row.ok:
            lines.append(f"| `{label}` | error | — |")
        else:
            lines.append(
                f"| `{label}` | `{row.launch_verdict}` | `{row.allowed_to_activate}` |"
            )
    lines.append("")
    return "\n".join(lines)


def run_all_workspaces_readiness(
    client: InstantlyClient,
    resolver: Resolver,
    explainer: Explainer | None = None,
    *,
    ctd_hosts: list[str] | None = None,
    include_rich_signals: bool = True,
    include_admin_workspace: bool = True,
    diagnose_fn: Callable[..., Any] | None = None,
) -> AgencyReadinessReport:
    """Iterate admin + sub-workspaces; each gets a WorkspaceReadinessReport."""
    explainer = explainer or TemplateExplainer()
    diagnose_fn = diagnose_fn or diagnose_result
    out = AgencyReadinessReport()

    try:
        out.admin_workspace = client.get_current_workspace()
    except InstantlyError as exc:
        out.not_checked.append("admin_workspace")
        out.admin_workspace = {
            "error": f"HTTP {exc.status}",
            "note": "workspaces:read scope may be missing",
        }

    sub_ids: list[str] = []
    try:
        sub_ids = client.sub_workspace_ids()
    except InstantlyError as exc:
        out.not_checked.append("workspace_group_members")
        out.note = (
            f"{out.note} Listing sub-workspaces failed (HTTP {exc.status}). "
            "Confirm agency workspace-group admin key."
        )

    targets: list[tuple[str | None, str | None]] = []
    if include_admin_workspace:
        admin_id = None
        admin_name = None
        if isinstance(out.admin_workspace, dict):
            admin_id = out.admin_workspace.get("id")
            admin_name = out.admin_workspace.get("name")
            if isinstance(admin_id, str):
                admin_id = admin_id.strip() or None
            else:
                admin_id = None
            if not isinstance(admin_name, str):
                admin_name = None
        # Admin key without x-as-workspace = current workspace
        targets.append((None, admin_name or "admin/current"))

    for wid in sub_ids:
        targets.append((wid, wid))

    if not targets:
        return out

    for workspace_id, label in targets:
        scoped = client.with_workspace(workspace_id) if workspace_id else client
        try:
            report = run_workspace_readiness(
                scoped,
                resolver,
                explainer,
                ctd_hosts=ctd_hosts,
                include_rich_signals=include_rich_signals,
                diagnose_fn=diagnose_fn,
            )
            decision = compute_launch_decision(report)
            name = label
            if workspace_id is None and isinstance(out.admin_workspace, dict):
                name = out.admin_workspace.get("name") or label
            out.workspaces.append(WorkspaceReadyRow(
                workspace_id=workspace_id or (
                    out.admin_workspace.get("id")
                    if isinstance(out.admin_workspace, dict) else None
                ),
                workspace_name=str(name) if name else None,
                ok=True,
                launch_verdict=decision.launch_verdict,
                allowed_to_activate=decision.allowed_to_activate,
                report=report,
            ))
        except InstantlyError as exc:
            out.workspaces.append(WorkspaceReadyRow(
                workspace_id=workspace_id,
                workspace_name=label,
                ok=False,
                error=f"Instantly HTTP {exc.status}",
            ))
        except ResolverError as exc:
            out.workspaces.append(WorkspaceReadyRow(
                workspace_id=workspace_id,
                workspace_name=label,
                ok=False,
                error=f"resolver error (not absence): {exc}",
            ))
        except ValueError as exc:
            out.workspaces.append(WorkspaceReadyRow(
                workspace_id=workspace_id,
                workspace_name=label,
                ok=False,
                error=str(exc),
            ))
    return out
