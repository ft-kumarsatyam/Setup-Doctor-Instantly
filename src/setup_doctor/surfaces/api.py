"""Product HTTP API for Setup Doctor.

POST /diagnose {"domain": "..."} -> versioned DiagnosisResult fields + report.
POST /bulk     {"domains": [...]} -> aggregated bulk report (sync).

Security posture (SSRF / internal probing):
- Hostnames are validated strictly (no IPs, schemes, paths, localhost, or
  internal-looking suffixes).
- DNS work uses the injected Resolver (LiveResolver by default) with a hard
  timeout; ResolverError becomes HTTP 502 with no fabricated findings.
- Optional API keys via SETUP_DOCTOR_API_KEYS; per-IP (and per-tenant) rate limits.
- Short response cache reduces abuse.

Privacy: request bodies and domain names are not logged by default — only
aggregate counts (status, findings count, duration, cache hit).
"""
from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from setup_doctor.checks import ALL_DNS_PACKS, DEFAULT_DKIM_SELECTORS, DEFAULT_PACKS, resolve_selectors
from setup_doctor.core.observability import log_diagnosis
from setup_doctor.core.result import SCHEMA_VERSION, DiagnosisSignals
from setup_doctor.dns.resolver import LiveResolver, Resolver, ResolverError
from setup_doctor.explain import (
    FIX_PACKET_PROVIDERS,
    LLMExplainer,
    TemplateExplainer,
    anthropic_completer,
    build_fix_packet,
    playbook_snippet,
    verify_fix_packet,
)
from setup_doctor.integrations.instantly import (
    InstantlyClient,
    InstantlyError,
    agency_report_payload,
    build_pre_launch_gate,
    compare_warmup_to_placement,
    comparisons_as_dicts,
    render_agency_workspaces_markdown,
    render_readiness_markdown,
    run_all_workspaces_readiness,
    run_workspace_readiness,
)
from setup_doctor.integrations.reputation import check_reputation
from setup_doctor.integrations.whois_age import lookup_domain_age
from setup_doctor.pipeline import diagnose_result
from setup_doctor.surfaces.auth import ApiKeyAuth
from setup_doctor.surfaces.connect_page import CONNECT_PAGE_HTML
from setup_doctor.surfaces.hooks import extract_domains, parse_json_body, verify_signature
from setup_doctor.surfaces.instantly_ctx import (
    HEADER_INSTANTLY_API_KEY,
    TenantVault,
    make_request_instantly_factory,
)
from setup_doctor.surfaces.notify import notify_slack
from setup_doctor.surfaces.vault import EncryptedTenantVault, default_vault_from_env
from setup_doctor.surfaces.web_check import render_web_check_html

MAX_DOMAIN_LEN = 253
MOUNT_MCP_ENV = "SETUP_DOCTOR_MOUNT_MCP"
DNS_TIMEOUT_SEC = 8.0
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SEC = 60.0
CACHE_TTL_SEC = 60.0
CACHE_MAX_ENTRIES = 256
BULK_MAX_DOMAINS = 50

_BLOCKED_EXACT = frozenset({
    "localhost", "localhost.", "broadcasthost",
})
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".internal", ".intranet", ".corp", ".home",
    ".lan", ".localdomain", ".priv", ".private",
)
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$",
    re.I,
)


class DiagnoseRequest(BaseModel):
    domain: str = Field(..., min_length=1, max_length=MAX_DOMAIN_LEN + 32)
    dkim_selectors: list[str] = Field(default_factory=list)
    esp_packs: list[str] = Field(default_factory=list)
    include_advisory: bool = False
    use_llm: bool = False
    include_reputation: bool = False
    include_instantly: bool = False
    include_domain_age: bool = False
    fix_packet_provider: str | None = None


class DiagnoseResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    domain: str
    findings: list[dict[str, Any]]
    report: str
    explanation: str = ""
    explanation_source: str = "template"
    used_fallback: bool = False
    violations: list[str] = Field(default_factory=list)
    signals: dict[str, Any] | None = None
    cached: bool = False
    fix_packet: dict[str, Any] | None = None
    domain_age: dict[str, Any] | None = None


class InstantlyCompareRequest(BaseModel):
    domain: str | None = Field(default=None, max_length=MAX_DOMAIN_LEN + 32)


class InstantlyReadyRequest(BaseModel):
    ctd_hosts: list[str] = Field(default_factory=list)
    include_rich_signals: bool = True
    use_llm: bool = False
    client_name: str | None = None
    agency_name: str | None = None
    agency_export: bool = False
    all_workspaces: bool = False


class PreLaunchGateRequest(BaseModel):
    domain: str | None = Field(default=None, max_length=MAX_DOMAIN_LEN + 32)
    ctd_hosts: list[str] = Field(default_factory=list)
    include_rich_signals: bool = True


class FixPacketRequest(BaseModel):
    domain: str = Field(..., min_length=1, max_length=MAX_DOMAIN_LEN + 32)
    provider: str = "cloudflare"
    dkim_selectors: list[str] = Field(default_factory=list)
    esp_packs: list[str] = Field(default_factory=list)


class ConnectInstantlyRequest(BaseModel):
    instantly_api_key: str = Field(..., min_length=8, max_length=512)


class BulkRequest(BaseModel):
    domains: list[str] = Field(..., min_length=1, max_length=BULK_MAX_DOMAINS)
    include_advisory: bool = False
    use_llm: bool = False
    include_instantly: bool = False


class BulkResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    count: int
    ok: int
    errors: int
    rows: list[dict[str, Any]]


InstantlyFactory = Callable[[], InstantlyClient]


def validate_hostname(raw: str) -> str:
    """Normalize and accept only public-looking DNS hostnames."""
    if raw is None:
        raise ValueError("Enter a sending domain (for example send.yourcompany.com).")
    s = raw.strip()
    if not s or len(s) > MAX_DOMAIN_LEN:
        raise ValueError(
            "Enter a hostname up to 253 characters — no spaces "
            "(example: send.yourcompany.com)."
        )
    lower = s.lower()
    if any(c in lower for c in ("/", "\\", "?", "#", "@", " ", "\t", "\n", "\r")):
        raise ValueError(
            "Use only the hostname — not a full URL or email. "
            "Example: send.yourcompany.com"
        )
    if "://" in lower or lower.startswith(("http:", "https:", "ftp:")):
        raise ValueError(
            "Drop https:// — paste just the domain (example: send.yourcompany.com)."
        )
    if lower.startswith("[") or "%" in lower:
        raise ValueError("Paste a domain name, not an IP address.")
    if lower.endswith("."):
        lower = lower[:-1]
    if ":" in lower:
        raise ValueError("Remove the port (use send.yourcompany.com, not host:443).")
    try:
        ipaddress.ip_address(lower)
        raise ValueError("Paste a domain name, not an IP address.")
    except ValueError as exc:
        if "not an IP" in str(exc):
            raise
    if lower in _BLOCKED_EXACT or any(lower.endswith(suf) for suf in _BLOCKED_SUFFIXES):
        raise ValueError(
            "That looks like a local/internal name. Use a public sending domain."
        )
    if lower.count(".") == 0:
        raise ValueError(
            "Use a full domain with a dot (example: send.yourcompany.com)."
        )
    if not _HOSTNAME_RE.match(lower):
        raise ValueError(
            "That doesn't look like a valid hostname. "
            "Example: send.yourcompany.com"
        )
    return lower


@dataclass
class _RateLimiter:
    limit: int = RATE_LIMIT_REQUESTS
    window: float = RATE_LIMIT_WINDOW_SEC
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:
                stale = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
                for k in stale[:5000]:
                    self._hits.pop(k, None)
            return True


@dataclass
class _ResponseCache:
    ttl: float = CACHE_TTL_SEC
    max_entries: int = CACHE_MAX_ENTRIES
    _store: dict[str, tuple[float, DiagnoseResponse]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, key: str) -> DiagnoseResponse | None:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires, value = item
            if expires < now:
                self._store.pop(key, None)
                return None
            return value.model_copy(update={"cached": True})

    def set(self, key: str, value: DiagnoseResponse) -> None:
        with self._lock:
            if len(self._store) >= self.max_entries:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest_key, None)
            self._store[key] = (time.monotonic() + self.ttl, value)


ResolverFactory = Callable[[], Resolver]


def _make_explainer(use_llm: bool):
    if not use_llm:
        return TemplateExplainer()
    allow = os.environ.get("SETUP_DOCTOR_API_LLM", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if not allow:
        raise HTTPException(
            status_code=400,
            detail="LLM explanations are disabled on this API (set SETUP_DOCTOR_API_LLM=true).",
        )
    try:
        return LLMExplainer(anthropic_completer())
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM explainer unavailable: {type(exc).__name__}",
        ) from exc


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def create_app(
    resolver_factory: ResolverFactory | None = None,
    *,
    rate_limiter: _RateLimiter | None = None,
    cache: _ResponseCache | None = None,
    dns_timeout: float = DNS_TIMEOUT_SEC,
    auth: ApiKeyAuth | None = None,
    instantly_factory: InstantlyFactory | None = None,
    instantly_vault: TenantVault | None = None,
    mount_mcp: bool | None = None,
) -> FastAPI:
    """Build the API app. Tests inject a FixtureResolver via resolver_factory.

    When ``mount_mcp`` is true (or SETUP_DOCTOR_MOUNT_MCP is set), streamable HTTP
    MCP is mounted at ``/mcp`` using the same API-key auth and Instantly header rules.
    """
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sd-dns")
    want_mcp = _env_flag(MOUNT_MCP_ENV) if mount_mcp is None else mount_mcp
    mcp_holder: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if want_mcp and "session_manager" in mcp_holder:
            async with mcp_holder["session_manager"].run():
                yield
        else:
            yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title="Setup Doctor",
        version="0.2.0",
        description=(
            "Deterministic SPF/DKIM/DMARC/MX diagnosis. Optional LLM rewrite is "
            "verified; findings are never invented by the model. "
            f"Response schema_version={SCHEMA_VERSION}."
        ),
        lifespan=lifespan,
    )
    app.state.resolver_factory = resolver_factory or (lambda: LiveResolver())
    app.state.rate_limiter = rate_limiter or _RateLimiter()
    app.state.cache = cache or _ResponseCache()
    app.state.dns_timeout = dns_timeout
    app.state.executor = executor
    app.state.auth = auth if auth is not None else ApiKeyAuth()
    app.state.instantly_factory = instantly_factory or (lambda: InstantlyClient())
    vault_obj: EncryptedTenantVault | None = None
    if instantly_vault is not None:
        app.state.instantly_vault = instantly_vault
    else:
        vault_obj = default_vault_from_env()
        app.state.instantly_vault = vault_obj.as_lookup() if vault_obj else None
    app.state.vault = vault_obj
    app.state.webhook_results: dict[str, Any] = {}
    app.state.webhook_secret = os.environ.get("SETUP_DOCTOR_INSTANTLY_HOOK_SECRET", "").strip()

    def _require_auth(
        x_api_key: str | None,
        authorization: str | None,
    ):
        try:
            return app.state.auth.authenticate(x_api_key, authorization)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def _instantly_for_request(
        tenant,
        x_instantly_api_key: str | None,
    ) -> InstantlyFactory:
        return make_request_instantly_factory(
            header_value=x_instantly_api_key,
            tenant=tenant,
            vault=app.state.instantly_vault,
            base_factory=app.state.instantly_factory,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "schema_version": SCHEMA_VERSION}

    @app.get("/schema")
    def schema_info() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnose": {
                "findings": "list of Finding dicts (deterministic)",
                "report": "markdown report",
                "explanation_source": "template | model_verified | template_fallback",
                "signals": "optional instantly/reputation side reports",
                "include_instantly": "attach domain-scoped Instantly warmup/placement signals",
            },
            "instantly": {
                "POST /instantly/compare": "warmup vs placement (optional domain filter)",
                "GET /instantly/compare": "same as POST",
                "POST /instantly/ready": "workspace readiness + vitals/CTD signals",
                "header": f"{HEADER_INSTANTLY_API_KEY} overrides INSTANTLY_API_KEY for this request",
            },
            "auth": "X-API-Key or Authorization: Bearer when SETUP_DOCTOR_API_KEYS is set",
            "mcp": "/mcp streamable HTTP when SETUP_DOCTOR_MOUNT_MCP=1 (use https://HOST/mcp)",
            "pre_launch_gate": "POST /instantly/pre-launch-gate — allowed_to_activate iff launch_verdict=ready",
            "fix_packets": f"providers: {', '.join(FIX_PACKET_PROVIDERS)}",
            "web": "GET / — public checker UI (same /diagnose engine)",
            "connect_docs": "GET /connect — Instantly dual-MCP one-pager",
            "hooks": "POST /hooks/instantly — HMAC SETUP_DOCTOR_INSTANTLY_HOOK_SECRET",
            "connect": "POST /connect/instantly — store encrypted Instantly key per tenant (SETUP_DOCTOR_VAULT_KEY)",
            "all_workspaces": "POST /instantly/ready {all_workspaces:true} — workspace-group admin + x-as-workspace",
            "auth_required": app.state.auth.required,
        }

    @app.post("/connect/instantly")
    def connect_instantly(
        body: ConnectInstantlyRequest,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        vault: EncryptedTenantVault | None = app.state.vault
        if vault is None or not vault.configured:
            raise HTTPException(
                status_code=503,
                detail="Vault disabled. Set SETUP_DOCTOR_VAULT_KEY (and optional SETUP_DOCTOR_VAULT_PATH).",
            )
        if tenant is None:
            raise HTTPException(
                status_code=401,
                detail="API key with tenant required to connect Instantly (set SETUP_DOCTOR_API_KEYS=key:tenant).",
            )
        try:
            fp = vault.put(tenant.tenant_id, body.instantly_api_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "connected": True,
            "tenant_id": tenant.tenant_id,
            "fingerprint": fp,
            "note": "Instantly key stored encrypted at rest. Raw key is never logged.",
        }

    @app.get("/connect/instantly")
    def connect_instantly_status(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        vault: EncryptedTenantVault | None = app.state.vault
        if vault is None:
            return {"connected": False, "vault_configured": False}
        tid = tenant.tenant_id if tenant else "default"
        return {"tenant_id": tid, **vault.status(tid)}

    @app.delete("/connect/instantly")
    def disconnect_instantly(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        vault: EncryptedTenantVault | None = app.state.vault
        if vault is None or not vault.configured:
            raise HTTPException(status_code=503, detail="Vault disabled.")
        if tenant is None:
            raise HTTPException(status_code=401, detail="API key with tenant required.")
        removed = vault.delete(tenant.tenant_id)
        return {"connected": False, "removed": removed, "tenant_id": tenant.tenant_id}

    @app.get("/", response_class=HTMLResponse)
    def web_checker() -> HTMLResponse:
        return HTMLResponse(
            content=render_web_check_html(auth_required=app.state.auth.required),
        )

    @app.get("/connect", response_class=HTMLResponse)
    def connect_docs() -> HTMLResponse:
        return HTMLResponse(content=CONNECT_PAGE_HTML)

    @app.post("/diagnose", response_model=DiagnoseResponse)
    def diagnose_endpoint(
        body: DiagnoseRequest,
        request: Request,
        response: Response,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
        x_instantly_api_key: str | None = Header(default=None, alias=HEADER_INSTANTLY_API_KEY),
    ) -> DiagnoseResponse:
        started = time.monotonic()
        tenant = _require_auth(x_api_key, authorization)
        request_instantly = _instantly_for_request(tenant, x_instantly_api_key)
        client_ip = (request.client.host if request.client else "unknown")
        rate_key = f"{tenant.tenant_id}:{client_ip}" if tenant else client_ip

        try:
            domain = validate_hostname(body.domain)
        except ValueError as exc:
            _log_http(400, started, domain=None)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        limiter: _RateLimiter = app.state.rate_limiter
        if not limiter.allow(rate_key):
            _log_http(429, started, domain=domain)
            raise HTTPException(
                status_code=429,
                detail=(
                    "You're checking too quickly. Wait about a minute, then try again."
                ),
            )

        try:
            selectors = resolve_selectors(
                explicit=tuple(body.dkim_selectors),
                packs=tuple(body.esp_packs),
                defaults=DEFAULT_DKIM_SELECTORS,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        packs = ALL_DNS_PACKS if body.include_advisory else DEFAULT_PACKS
        esp_packs = list(body.esp_packs)
        if body.include_instantly and "instantly" not in esp_packs:
            esp_packs = ["instantly", *esp_packs]
            try:
                selectors = resolve_selectors(
                    explicit=tuple(body.dkim_selectors),
                    packs=tuple(esp_packs),
                    defaults=DEFAULT_DKIM_SELECTORS,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        cache_key = (
            f"{domain}|{','.join(selectors)}|{sorted(packs)}|"
            f"{body.use_llm}|{body.include_reputation}|{body.include_instantly}|"
            f"{body.include_domain_age}|{body.fix_packet_provider}"
        )
        cached_hit = app.state.cache.get(cache_key)
        if cached_hit is not None:
            log_diagnosis(
                explanation_source=cached_hit.explanation_source,
                findings_count=len(cached_hit.findings),
                duration_ms=int((time.monotonic() - started) * 1000),
                rejection_reasons=[],
                domain=domain,
                cached=True,
                extra={"http_status": 200},
            )
            response.headers["X-Cache"] = "HIT"
            return cached_hit

        explainer = _make_explainer(body.use_llm)
        resolver = app.state.resolver_factory()
        timeout = app.state.dns_timeout * (2 if body.include_instantly else 1)
        try:
            future = app.state.executor.submit(
                _run_diagnose,
                domain,
                resolver,
                explainer,
                selectors,
                packs,
                body.include_reputation,
                body.include_instantly,
                request_instantly,
                body.include_domain_age,
                body.fix_packet_provider,
            )
            payload = future.result(timeout=timeout)
        except FuturesTimeout as exc:
            future.cancel()
            _log_http(504, started, domain=domain)
            raise HTTPException(
                status_code=504,
                detail=(
                    "DNS lookup took too long — no Findings were produced. "
                    "Try again in a moment. A timeout is not the same as missing records."
                ),
            ) from exc
        except ResolverError as exc:
            _log_http(502, started, domain=domain)
            raise HTTPException(
                status_code=502,
                detail=(
                    "We couldn't reach DNS for this domain right now — no Findings "
                    "were produced. An outage is not the same as missing SPF/DKIM/"
                    "DMARC records. Retry shortly."
                ),
            ) from exc
        except InstantlyError as exc:
            _log_http(502, started, domain=domain)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Instantly API returned HTTP {exc.status}, so Instantly signals "
                    "weren't attached. DNS Findings (if any) still need a successful "
                    "check — retry, or uncheck Instantly signals and check DNS only."
                ),
            ) from exc
        except ValueError as exc:
            _log_http(404, started, domain=domain)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HTTPException:
            raise

        app.state.cache.set(cache_key, payload)
        response.headers["X-Cache"] = "MISS"
        if tenant:
            response.headers["X-Tenant"] = tenant.tenant_id
        return payload

    def _instantly_compare(
        domain: str | None,
        instantly_factory: InstantlyFactory,
    ) -> dict[str, Any]:
        filtered = None
        if domain:
            try:
                filtered = validate_hostname(domain)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            client = instantly_factory()
            reports = compare_warmup_to_placement(client, domain=filtered)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InstantlyError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Instantly API request failed (HTTP {exc.status}).",
            ) from exc
        return {
            "schema_version": SCHEMA_VERSION,
            "accounts": comparisons_as_dicts(reports),
        }

    @app.post("/instantly/compare")
    def instantly_compare_endpoint(
        body: InstantlyCompareRequest | None = None,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
        x_instantly_api_key: str | None = Header(default=None, alias=HEADER_INSTANTLY_API_KEY),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        body = body or InstantlyCompareRequest()
        return _instantly_compare(
            body.domain,
            _instantly_for_request(tenant, x_instantly_api_key),
        )

    @app.get("/instantly/compare")
    def instantly_compare_get(
        domain: str | None = None,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
        x_instantly_api_key: str | None = Header(default=None, alias=HEADER_INSTANTLY_API_KEY),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        return _instantly_compare(
            domain,
            _instantly_for_request(tenant, x_instantly_api_key),
        )

    @app.post("/instantly/ready")
    def instantly_ready_endpoint(
        body: InstantlyReadyRequest | None = None,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
        x_instantly_api_key: str | None = Header(default=None, alias=HEADER_INSTANTLY_API_KEY),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        body = body or InstantlyReadyRequest()
        explainer = _make_explainer(body.use_llm)
        resolver = app.state.resolver_factory()
        try:
            client = _instantly_for_request(tenant, x_instantly_api_key)()
            if body.all_workspaces:
                agency = run_all_workspaces_readiness(
                    client,
                    resolver,
                    explainer,
                    ctd_hosts=list(body.ctd_hosts),
                    include_rich_signals=body.include_rich_signals,
                )
                return {
                    "schema_version": SCHEMA_VERSION,
                    "all_workspaces": True,
                    "agency": agency.to_dict(),
                    "markdown": render_agency_workspaces_markdown(agency),
                }
            report = run_workspace_readiness(
                client,
                resolver,
                explainer,
                ctd_hosts=list(body.ctd_hosts),
                include_rich_signals=body.include_rich_signals,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InstantlyError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Instantly API request failed (HTTP {exc.status}).",
            ) from exc
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "report": report.to_dict(),
            "markdown": render_readiness_markdown(report),
            "launch_verdict": report.launch_verdict,
            "summary_spoken": report.summary_spoken,
        }
        if body.agency_export:
            payload["agency"] = agency_report_payload(
                report,
                client_name=body.client_name or "Client",
                agency_name=body.agency_name or "Agency",
            )
        return payload

    @app.post("/instantly/pre-launch-gate")
    def pre_launch_gate_endpoint(
        body: PreLaunchGateRequest | None = None,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
        x_instantly_api_key: str | None = Header(default=None, alias=HEADER_INSTANTLY_API_KEY),
    ) -> dict[str, Any]:
        tenant = _require_auth(x_api_key, authorization)
        body = body or PreLaunchGateRequest()
        try:
            client = _instantly_for_request(tenant, x_instantly_api_key)()
            report = run_workspace_readiness(
                client,
                app.state.resolver_factory(),
                TemplateExplainer(),
                ctd_hosts=list(body.ctd_hosts),
                include_rich_signals=body.include_rich_signals,
            )
            domain = validate_hostname(body.domain) if body.domain else None
            return build_pre_launch_gate(report, domain_filter=domain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InstantlyError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Instantly API request failed (HTTP {exc.status}).",
            ) from exc

    @app.post("/fix-packet")
    def fix_packet_endpoint(
        body: FixPacketRequest,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_auth(x_api_key, authorization)
        try:
            domain = validate_hostname(body.domain)
            selectors = resolve_selectors(
                explicit=tuple(body.dkim_selectors),
                packs=tuple(body.esp_packs),
                defaults=DEFAULT_DKIM_SELECTORS,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        resolver = app.state.resolver_factory()
        result = diagnose_result(
            domain, resolver, TemplateExplainer(), selectors, packs=DEFAULT_PACKS,
        )
        try:
            packet = build_fix_packet(
                domain, result.findings, provider=body.provider,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        violations = verify_fix_packet(packet, result.findings)
        return {
            "schema_version": SCHEMA_VERSION,
            "fix_packet": packet.to_dict(),
            "markdown": packet.to_markdown(),
            "playbook": playbook_snippet(body.provider),
            "violations": violations,
            "findings": [f.to_dict() for f in result.findings],
        }

    @app.post("/hooks/instantly")
    async def instantly_hook(
        request: Request,
        x_setup_doctor_signature: str | None = Header(
            default=None, alias="X-Setup-Doctor-Signature",
        ),
    ) -> dict[str, Any]:
        secret = app.state.webhook_secret
        raw = await request.body()
        if not secret:
            raise HTTPException(
                status_code=503,
                detail="Webhook disabled (set SETUP_DOCTOR_INSTANTLY_HOOK_SECRET).",
            )
        if not verify_signature(secret, raw, x_setup_doctor_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        try:
            payload = parse_json_body(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        domains = extract_domains(payload)
        if not domains:
            raise HTTPException(status_code=400, detail="No domains found in payload")
        limiter: _RateLimiter = app.state.rate_limiter
        if not limiter.allow("hook:instantly"):
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")
        resolver = app.state.resolver_factory()
        explainer = TemplateExplainer()
        rows: list[dict[str, Any]] = []
        for raw_domain in domains[:BULK_MAX_DOMAINS]:
            try:
                domain = validate_hostname(raw_domain)
            except ValueError as exc:
                rows.append({"domain": raw_domain, "ok": False, "error": str(exc)})
                continue
            try:
                result = diagnose_result(
                    domain, resolver, explainer, DEFAULT_DKIM_SELECTORS, packs=DEFAULT_PACKS,
                )
                row = {"domain": domain, "ok": True, "result": result.to_dict()}
                app.state.webhook_results[domain] = row
                rows.append(row)
            except ResolverError:
                rows.append({
                    "domain": domain,
                    "ok": False,
                    "error": "resolver error (not absence)",
                })
            except ValueError as exc:
                rows.append({"domain": domain, "ok": False, "error": str(exc)})
        ok_n = sum(1 for r in rows if r.get("ok"))
        slack = notify_slack(
            f"Setup Doctor Instantly hook: {ok_n}/{len(rows)} domain(s) diagnosed "
            f"(idempotent_key={payload.get('idempotency_key') or payload.get('id') or 'n/a'})."
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "idempotent_key": payload.get("idempotency_key") or payload.get("id"),
            "count": len(rows),
            "rows": rows,
            "slack": slack,
            "note": "Findings from Setup Doctor only; Instantly failure does not invent DNS.",
        }

    @app.get("/hooks/instantly/last/{domain}")
    def instantly_hook_last(
        domain: str,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_auth(x_api_key, authorization)
        try:
            host = validate_hostname(domain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = app.state.webhook_results.get(host)
        if not row:
            raise HTTPException(status_code=404, detail="No stored webhook result")
        return row

    @app.post("/bulk", response_model=BulkResponse)
    def bulk_endpoint(
        body: BulkRequest,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> BulkResponse:
        tenant = _require_auth(x_api_key, authorization)
        client_ip = (request.client.host if request.client else "unknown")
        rate_key = f"bulk:{tenant.tenant_id if tenant else client_ip}"
        if not app.state.rate_limiter.allow(rate_key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")

        packs = ALL_DNS_PACKS if body.include_advisory else DEFAULT_PACKS
        explainer = _make_explainer(body.use_llm)
        resolver = app.state.resolver_factory()
        rows: list[dict[str, Any]] = []
        ok = errors = 0
        for raw in body.domains:
            try:
                domain = validate_hostname(raw)
            except ValueError as exc:
                errors += 1
                rows.append({"domain": raw, "ok": False, "error": str(exc), "result": None})
                continue
            try:
                result = diagnose_result(
                    domain, resolver, explainer, DEFAULT_DKIM_SELECTORS, packs=packs,
                )
                ok += 1
                rows.append({"domain": domain, "ok": True, "error": None, "result": result.to_dict()})
            except ResolverError:
                errors += 1
                rows.append({
                    "domain": domain,
                    "ok": False,
                    "error": "resolver error (not absence)",
                    "result": None,
                })
            except ValueError as exc:
                errors += 1
                rows.append({"domain": domain, "ok": False, "error": str(exc), "result": None})
        return BulkResponse(
            schema_version=SCHEMA_VERSION,
            count=len(rows),
            ok=ok,
            errors=errors,
            rows=rows,
        )

    if want_mcp:
        _mount_mcp_on_app(app, mcp_holder)

    return app


def _mount_mcp_on_app(app: FastAPI, mcp_holder: dict[str, Any]) -> None:
    """Mount streamable HTTP MCP at /mcp (optional dependency).

    Fixes Fly/proxy issues that break Cursor/Claude MCP clients:
    - Rewrite ``/mcp`` → ``/mcp/`` in-process (no 307)
    - Trust ``X-Forwarded-Proto`` so any Location headers stay HTTPS
    - Rewrite accidental ``http://`` Location redirects to ``https://``
    """
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        from setup_doctor.surfaces.mcp_server import (
            build_fastmcp,
            reset_request_instantly_context,
            set_request_instantly_context,
        )
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "MCP HTTP mount requires the mcp extra: pip install -e '.[mcp]'"
        ) from exc

    try:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    except ImportError:  # pragma: no cover
        ProxyHeadersMiddleware = None  # type: ignore[misc, assignment]

    mcp = build_fastmcp(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    # Creating the ASGI app initializes the session manager (needed for lifespan).
    inner = mcp.streamable_http_app()
    mcp_holder["session_manager"] = mcp.session_manager

    class _McpPathAndHttpsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Avoid Starlette Mount's 307 /mcp → /mcp/ (often emitted as http:// behind Fly).
            if request.scope.get("path") == "/mcp":
                request.scope["path"] = "/mcp/"
            response = await call_next(request)
            location = response.headers.get("location")
            if location and location.startswith("http://"):
                forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
                if forwarded == "https" or request.url.scheme == "https":
                    response.headers["location"] = "https://" + location[len("http://"):]
            return response

    class _McpGateMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.scope.get("path") or ""
            if not path.startswith("/mcp"):
                return await call_next(request)
            try:
                tenant = app.state.auth.authenticate(
                    request.headers.get("X-API-Key"),
                    request.headers.get("Authorization"),
                )
            except PermissionError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=401)
            header_key = request.headers.get(HEADER_INSTANTLY_API_KEY)
            factory = make_request_instantly_factory(
                header_value=header_key,
                tenant=tenant,
                vault=app.state.instantly_vault,
                base_factory=app.state.instantly_factory,
            )
            tokens = set_request_instantly_context(header_key, factory=factory)
            try:
                return await call_next(request)
            finally:
                reset_request_instantly_context(tokens)

    # Middleware order: last added runs first.
    app.add_middleware(_McpGateMiddleware)
    app.add_middleware(_McpPathAndHttpsMiddleware)
    if ProxyHeadersMiddleware is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.mount("/mcp", inner)
    app.state.mcp = mcp



def _run_diagnose(
    domain: str,
    resolver: Resolver,
    explainer,
    selectors: tuple[str, ...],
    packs: frozenset[str],
    include_reputation: bool,
    include_instantly: bool = False,
    instantly_factory: InstantlyFactory | None = None,
    include_domain_age: bool = False,
    fix_packet_provider: str | None = None,
) -> DiagnoseResponse:
    if isinstance(resolver, LiveResolver) and not resolver.domain_exists(domain):
        raise ValueError(
            f"{domain} does not exist in DNS (NXDOMAIN). "
            "Check the spelling; no diagnosis was produced."
        )
    not_checked: list[str] = []
    reputation = None
    instantly = None
    if include_reputation:
        reputation = check_reputation(domain)
    else:
        not_checked.append("reputation")
    if include_instantly:
        factory = instantly_factory or (lambda: InstantlyClient())
        client = factory()
        instantly = comparisons_as_dicts(
            compare_warmup_to_placement(client, domain=domain)
        )
    else:
        not_checked.append("instantly")
    signals = DiagnosisSignals(
        instantly=instantly,
        reputation=reputation,
        not_checked=not_checked,
    )
    result = diagnose_result(
        domain, resolver, explainer, selectors, packs=packs, signals=signals,
    )
    fix_packet = None
    if fix_packet_provider:
        packet = build_fix_packet(
            domain, result.findings, provider=fix_packet_provider,
        )
        violations = verify_fix_packet(packet, result.findings)
        if violations:
            # Still return packet but surface violations; never invent records.
            fix_packet = {**packet.to_dict(), "violations": violations}
        else:
            fix_packet = packet.to_dict()
    domain_age = None
    if include_domain_age:
        domain_age = lookup_domain_age(domain).to_dict()
    return DiagnoseResponse(
        schema_version=result.schema_version,
        domain=result.domain,
        findings=[f.to_dict() for f in result.findings],
        report=result.report,
        explanation=result.explanation,
        explanation_source=result.explanation_source,
        used_fallback=result.used_fallback,
        violations=list(result.violations),
        signals=result.signals.to_dict() if result.signals else None,
        cached=False,
        fix_packet=fix_packet,
        domain_age=domain_age,
    )


def _log_http(status: int, started: float, *, domain: str | None) -> None:
    duration_ms = int((time.monotonic() - started) * 1000)
    log_diagnosis(
        explanation_source="unavailable",
        findings_count=0,
        duration_ms=duration_ms,
        rejection_reasons=[],
        domain=domain,
        cached=False,
        extra={"http_status": status},
    )


app = create_app()
