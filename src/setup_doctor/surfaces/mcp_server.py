"""MCP server exposing Setup Doctor tools to agents.

Tools call the same diagnose_result / Instantly paths as CLI — no parallel
DNS logic. Optional dependency: pip install -e '.[mcp]'

Transports:
  stdio (default):  python -m setup_doctor.surfaces.mcp_server
  streamable-http:  python -m setup_doctor.surfaces.mcp_server --transport streamable-http
  Also mountable on the FastAPI app at /mcp (see surfaces.api.create_app).

Hosted auth: SETUP_DOCTOR_API_KEYS via X-API-Key / Authorization Bearer.
Instantly key: X-Instantly-Api-Key header → InstantlyClient(api_key=…); else env.
"""
from __future__ import annotations

import argparse
import contextlib
import contextvars
import json
import os
import sys
from typing import Any, Callable

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
from setup_doctor.surfaces.instantly_ctx import (
    InstantlyFactory,
    make_request_instantly_factory,
    resolve_instantly_client,
)

# Per-request Instantly credentials for HTTP MCP (stdio leaves these unset).
_instantly_header_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "setup_doctor_instantly_header", default=None
)
_instantly_factory_var: contextvars.ContextVar[InstantlyFactory | None] = contextvars.ContextVar(
    "setup_doctor_instantly_factory", default=None
)


def set_request_instantly_context(
    header_value: str | None,
    *,
    factory: InstantlyFactory | None = None,
) -> tuple[contextvars.Token[str | None], contextvars.Token[InstantlyFactory | None]]:
    """Bind Instantly header/factory for the current request (HTTP MCP middleware)."""
    return (
        _instantly_header_var.set(header_value),
        _instantly_factory_var.set(factory),
    )


def reset_request_instantly_context(
    tokens: tuple[contextvars.Token[str | None], contextvars.Token[InstantlyFactory | None]],
) -> None:
    _instantly_header_var.reset(tokens[0])
    _instantly_factory_var.reset(tokens[1])


def _client_from_context(arguments: dict[str, Any] | None = None) -> InstantlyClient:
    """Resolve InstantlyClient for a tool call (header → factory/env)."""
    args = arguments or {}
    explicit = args.get("instantly_api_key")
    if isinstance(explicit, str) and explicit.strip():
        # Documented for local JSONL only; HTTP should prefer the header.
        return InstantlyClient(api_key=explicit.strip())
    return resolve_instantly_client(
        header_value=_instantly_header_var.get(),
        factory=_instantly_factory_var.get(),
    )


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
            client = _client_from_context(arguments)
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
        client = _client_from_context(arguments)
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
        client = _client_from_context(arguments)
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


def build_fastmcp(
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    stateless_http: bool = True,
    streamable_http_path: str = "/",
    transport_security: Any | None = None,
):
    """Build a FastMCP server with Setup Doctor tools registered."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    security = transport_security
    if security is None:
        # Hosted / Docker: disable localhost-only DNS-rebinding allowlist.
        # API-key auth is the gate; reverse proxies set Host headers.
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    mcp = FastMCP(
        "setup-doctor",
        host=host,
        port=port,
        stateless_http=stateless_http,
        streamable_http_path=streamable_http_path,
        transport_security=security,
    )

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

    return mcp


def create_mcp_http_app(
    *,
    auth_authenticate: Callable[[str | None, str | None], Any] | None = None,
    instantly_factory: InstantlyFactory | None = None,
    host: str = "0.0.0.0",
    port: int = 8000,
):
    """Starlette app for streamable HTTP MCP with optional API-key + Instantly header middleware.

    ``auth_authenticate(x_api_key, authorization)`` should raise PermissionError on failure
    and return Tenant | None on success (same contract as ApiKeyAuth.authenticate).
    When None, auth is open (local/dev).
    """
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Mount

    mcp = build_fastmcp(host=host, port=port, streamable_http_path="/")
    inner = mcp.streamable_http_app()

    class _GateMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if auth_authenticate is not None:
                try:
                    auth_authenticate(
                        request.headers.get("X-API-Key"),
                        request.headers.get("Authorization"),
                    )
                except PermissionError as exc:
                    return JSONResponse({"detail": str(exc)}, status_code=401)
            header_key = request.headers.get("X-Instantly-Api-Key")
            tokens = set_request_instantly_context(
                header_key,
                factory=instantly_factory or make_request_instantly_factory(
                    header_value=header_key,
                ),
            )
            try:
                return await call_next(request)
            finally:
                reset_request_instantly_context(tokens)

    # Lifespan: run StreamableHTTP session manager when present.
    session_manager = mcp.session_manager

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with session_manager.run():
            yield

    app = Starlette(routes=[Mount("/", app=inner)], lifespan=lifespan)
    app.add_middleware(_GateMiddleware)
    app.state.mcp = mcp
    app.state.session_manager = session_manager
    return app


def _run_with_mcp_sdk(transport: str = "stdio", host: str = "0.0.0.0", port: int = 8000) -> int:
    if transport == "stdio":
        mcp = build_fastmcp(host=host, port=port)
        mcp.run(transport="stdio")
        return 0

    if transport in ("streamable-http", "sse"):
        from setup_doctor.surfaces.auth import ApiKeyAuth

        auth = ApiKeyAuth()

        def _authenticate(x_api_key: str | None, authorization: str | None):
            return auth.authenticate(x_api_key, authorization)

        if transport == "sse":
            # Prefer streamable-http; SSE kept for older clients.
            mcp = build_fastmcp(host=host, port=port, streamable_http_path="/mcp")
            mcp.run(transport="sse")
            return 0

        import uvicorn

        app = create_mcp_http_app(
            auth_authenticate=_authenticate if auth.required else None,
            host=host,
            port=port,
        )
        uvicorn.run(app, host=host, port=port)
        return 0

    raise ValueError(f"Unknown transport: {transport}")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setup Doctor MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=os.environ.get("SETUP_DOCTOR_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("SETUP_DOCTOR_MCP_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SETUP_DOCTOR_MCP_PORT", "8000")),
    )
    args = parser.parse_args(argv)
    try:
        return _run_with_mcp_sdk(transport=args.transport, host=args.host, port=args.port)
    except ImportError:
        if args.transport != "stdio":
            print(
                "mcp package required for HTTP transports. Install with: pip install -e '.[mcp]'",
                file=sys.stderr,
            )
            return 1
        print(
            "mcp package not installed; using JSONL fallback. "
            "Install with: pip install -e '.[mcp]'",
            file=sys.stderr,
        )
        return _run_jsonl_fallback()


if __name__ == "__main__":
    sys.exit(main())
