"""MCP stdio server exposing Setup Doctor tools to agents.

Tools call the same diagnose_result / Instantly paths as CLI — no parallel
DNS logic. Optional dependency: pip install -e '.[mcp]'

    python -m setup_doctor.mcp_server
"""
from __future__ import annotations

import json
import sys
from typing import Any

from setup_doctor.checks import ALL_DNS_PACKS, DEFAULT_DKIM_SELECTORS, DEFAULT_PACKS, resolve_selectors
from setup_doctor.core.result import SCHEMA_VERSION, DiagnosisSignals
from setup_doctor.dns.resolver import LiveResolver, ResolverError
from setup_doctor.explain import TemplateExplainer
from setup_doctor.integrations.instantly import (
    InstantlyClient,
    InstantlyError,
    compare_warmup_to_placement,
    comparisons_as_dicts,
    render_readiness_markdown,
    run_workspace_readiness,
)
from setup_doctor.pipeline import diagnose_result


def tool_diagnose(arguments: dict[str, Any]) -> dict[str, Any]:
    domain = (arguments.get("domain") or "").strip()
    if not domain:
        return {"error": "domain is required"}
    include_advisory = bool(arguments.get("include_advisory", False))
    include_instantly = bool(arguments.get("include_instantly", False))
    esp_packs = list(arguments.get("esp_packs") or ())
    if include_instantly and "instantly" not in esp_packs:
        esp_packs = ["instantly", *esp_packs]
    try:
        selectors = resolve_selectors(
            explicit=tuple(arguments.get("dkim_selectors") or ()),
            packs=tuple(esp_packs),
            defaults=DEFAULT_DKIM_SELECTORS,
        )
    except ValueError as exc:
        return {"error": "bad_request", "message": str(exc)}
    packs = ALL_DNS_PACKS if include_advisory else DEFAULT_PACKS
    resolver = LiveResolver()
    signals = None
    if include_instantly:
        try:
            client = InstantlyClient()
            instantly = comparisons_as_dicts(
                compare_warmup_to_placement(client, domain=domain)
            )
            signals = DiagnosisSignals(
                instantly=instantly,
                reputation=None,
                not_checked=["reputation"],
            )
        except ValueError as exc:
            return {"error": "config", "message": str(exc)}
        except InstantlyError as exc:
            return {"error": "instantly_http", "status": exc.status, "message": str(exc)}
    try:
        if not resolver.domain_exists(domain):
            return {
                "error": "NXDOMAIN",
                "message": f"{domain} does not exist in DNS; no diagnosis produced.",
            }
        result = diagnose_result(
            domain, resolver, TemplateExplainer(), selectors, packs=packs, signals=signals,
        )
        return result.to_dict()
    except ResolverError as exc:
        return {
            "error": "resolver_error",
            "message": str(exc),
            "note": "Outage is not the same as missing records.",
        }
    except ValueError as exc:
        return {"error": "bad_request", "message": str(exc)}


def tool_compare_instantly(arguments: dict[str, Any]) -> dict[str, Any]:
    domain = (arguments.get("domain") or "").strip() or None
    try:
        client = InstantlyClient()
        reports = compare_warmup_to_placement(client, domain=domain)
        return {
            "schema_version": SCHEMA_VERSION,
            "accounts": comparisons_as_dicts(reports),
        }
    except ValueError as exc:
        return {"error": "config", "message": str(exc)}
    except InstantlyError as exc:
        return {"error": "instantly_http", "status": exc.status, "message": str(exc)}


def tool_instantly_ready(arguments: dict[str, Any]) -> dict[str, Any]:
    ctd_hosts = list(arguments.get("ctd_hosts") or [])
    include_rich = bool(arguments.get("include_rich_signals", True))
    try:
        client = InstantlyClient()
        report = run_workspace_readiness(
            client,
            LiveResolver(),
            TemplateExplainer(),
            ctd_hosts=ctd_hosts,
            include_rich_signals=include_rich,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "report": report.to_dict(),
            "markdown": render_readiness_markdown(report),
        }
    except ValueError as exc:
        return {"error": "config", "message": str(exc)}
    except InstantlyError as exc:
        return {"error": "instantly_http", "status": exc.status, "message": str(exc)}
    except ResolverError as exc:
        return {
            "error": "resolver_error",
            "message": str(exc),
            "note": "Outage is not the same as missing records.",
        }


TOOLS = {
    "diagnose": {
        "description": (
            "Run Setup Doctor DNS diagnosis (SPF/DKIM/DMARC/MX). "
            "Returns versioned DiagnosisResult. Findings are deterministic; "
            "do not invent DNS state beyond the returned findings. "
            "Set include_instantly to attach domain-scoped Instantly signals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "dkim_selectors": {"type": "array", "items": {"type": "string"}},
                "esp_packs": {"type": "array", "items": {"type": "string"}},
                "include_advisory": {"type": "boolean"},
                "include_instantly": {"type": "boolean"},
            },
            "required": ["domain"],
        },
        "handler": tool_diagnose,
    },
    "compare_instantly": {
        "description": (
            "Compare Instantly warmup scores to inbox placement. "
            "Optional domain filters to that sender domain. "
            "Missing data is unknown — never treat as healthy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
            },
        },
        "handler": tool_compare_instantly,
    },
    "instantly_ready": {
        "description": (
            "Workspace readiness: diagnose Instantly sender domains, correlate "
            "Instantly vitals, attach warmup/placement and optional CTD. "
            "Read-only; Instantly vitals never invent Findings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ctd_hosts": {"type": "array", "items": {"type": "string"}},
                "include_rich_signals": {"type": "boolean"},
            },
        },
        "handler": tool_instantly_ready,
    },
}


def _run_with_mcp_sdk() -> int:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("setup-doctor")

    @mcp.tool()
    def diagnose(
        domain: str,
        dkim_selectors: list[str] | None = None,
        esp_packs: list[str] | None = None,
        include_advisory: bool = False,
        include_instantly: bool = False,
    ) -> str:
        """Diagnose SPF/DKIM/DMARC/MX for a domain. Returns JSON DiagnosisResult."""
        return json.dumps(
            tool_diagnose({
                "domain": domain,
                "dkim_selectors": dkim_selectors or [],
                "esp_packs": esp_packs or [],
                "include_advisory": include_advisory,
                "include_instantly": include_instantly,
            }),
            indent=2,
        )

    @mcp.tool()
    def compare_instantly(domain: str | None = None) -> str:
        """Instantly warmup vs placement (unknown when data missing)."""
        return json.dumps(
            tool_compare_instantly({"domain": domain} if domain else {}),
            indent=2,
        )

    @mcp.tool()
    def instantly_ready(
        ctd_hosts: list[str] | None = None,
        include_rich_signals: bool = True,
    ) -> str:
        """Instantly workspace readiness with Setup Doctor Findings."""
        return json.dumps(
            tool_instantly_ready({
                "ctd_hosts": ctd_hosts or [],
                "include_rich_signals": include_rich_signals,
            }),
            indent=2,
        )

    mcp.run(transport="stdio")
    return 0


def _run_jsonl_fallback() -> int:
    """Minimal JSON-lines protocol when mcp SDK is not installed.

    Client sends: {"id":1,"method":"tools/list"} or
                  {"id":2,"method":"tools/call","params":{"name":"diagnose","arguments":{...}}}
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"error": "invalid JSON"}), flush=True)
            continue
        rid = req.get("id")
        method = req.get("method")
        if method == "tools/list":
            tools = [
                {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                for n, t in TOOLS.items()
            ]
            print(json.dumps({"id": rid, "result": {"tools": tools}}), flush=True)
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            tool = TOOLS.get(name)
            if not tool:
                print(json.dumps({"id": rid, "error": f"unknown tool {name}"}), flush=True)
                continue
            result = tool["handler"](arguments)
            print(json.dumps({"id": rid, "result": result}), flush=True)
        else:
            print(json.dumps({"id": rid, "error": f"unknown method {method}"}), flush=True)
    return 0


def main() -> int:
    try:
        return _run_with_mcp_sdk()
    except ImportError:
        print(
            "mcp package not installed; using JSONL fallback. "
            "Install with: pip install -e '.[mcp]'",
            file=sys.stderr,
        )
        return _run_jsonl_fallback()


if __name__ == "__main__":
    sys.exit(main())
