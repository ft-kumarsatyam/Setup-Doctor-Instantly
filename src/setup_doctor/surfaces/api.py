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
from pydantic import BaseModel, Field

from setup_doctor.checks import ALL_DNS_PACKS, DEFAULT_DKIM_SELECTORS, DEFAULT_PACKS, resolve_selectors
from setup_doctor.core.observability import log_diagnosis
from setup_doctor.core.result import SCHEMA_VERSION, DiagnosisSignals
from setup_doctor.dns.resolver import LiveResolver, Resolver, ResolverError
from setup_doctor.explain import LLMExplainer, TemplateExplainer, anthropic_completer
from setup_doctor.integrations.instantly import (
    InstantlyClient,
    InstantlyError,
    compare_warmup_to_placement,
    comparisons_as_dicts,
    render_readiness_markdown,
    run_workspace_readiness,
)
from setup_doctor.integrations.reputation import check_reputation
from setup_doctor.pipeline import diagnose_result
from setup_doctor.surfaces.auth import ApiKeyAuth
from setup_doctor.surfaces.instantly_ctx import (
    HEADER_INSTANTLY_API_KEY,
    TenantVault,
    make_request_instantly_factory,
)

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


class InstantlyCompareRequest(BaseModel):
    domain: str | None = Field(default=None, max_length=MAX_DOMAIN_LEN + 32)


class InstantlyReadyRequest(BaseModel):
    ctd_hosts: list[str] = Field(default_factory=list)
    include_rich_signals: bool = True
    use_llm: bool = False


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
        raise ValueError("domain is required")
    s = raw.strip()
    if not s or len(s) > MAX_DOMAIN_LEN:
        raise ValueError("domain must be a hostname of at most 253 characters")
    lower = s.lower()
    if any(c in lower for c in ("/", "\\", "?", "#", "@", " ", "\t", "\n", "\r")):
        raise ValueError("domain must not contain a path, query, or userinfo")
    if "://" in lower or lower.startswith(("http:", "https:", "ftp:")):
        raise ValueError("domain must not include a URL scheme")
    if lower.startswith("[") or "%" in lower:
        raise ValueError("domain must not be an IP address")
    if lower.endswith("."):
        lower = lower[:-1]
    if ":" in lower:
        raise ValueError("domain must not include a port")
    try:
        ipaddress.ip_address(lower)
        raise ValueError("domain must not be an IP address")
    except ValueError as exc:
        if "must not be an IP" in str(exc):
            raise
    if lower in _BLOCKED_EXACT or any(lower.endswith(suf) for suf in _BLOCKED_SUFFIXES):
        raise ValueError("domain must not be a localhost or internal name")
    if lower.count(".") == 0:
        raise ValueError("domain must be a fully-qualified hostname")
    if not _HOSTNAME_RE.match(lower):
        raise ValueError("domain is not a valid hostname")
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
    app.state.instantly_vault = instantly_vault

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
            "mcp": "/mcp streamable HTTP when SETUP_DOCTOR_MOUNT_MCP=1",
        }

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
                detail="Rate limit exceeded. Try again in a minute.",
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
            f"{body.use_llm}|{body.include_reputation}|{body.include_instantly}"
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
            )
            payload = future.result(timeout=timeout)
        except FuturesTimeout as exc:
            future.cancel()
            _log_http(504, started, domain=domain)
            raise HTTPException(
                status_code=504,
                detail="DNS checks timed out. No diagnosis was produced.",
            ) from exc
        except ResolverError as exc:
            _log_http(502, started, domain=domain)
            raise HTTPException(
                status_code=502,
                detail=(
                    "Could not complete DNS checks (resolver error). "
                    "No diagnosis was produced — an outage is not the same as missing records."
                ),
            ) from exc
        except InstantlyError as exc:
            _log_http(502, started, domain=domain)
            raise HTTPException(
                status_code=502,
                detail=f"Instantly API request failed (HTTP {exc.status}). No Instantly signals attached.",
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
        return {
            "schema_version": SCHEMA_VERSION,
            "report": report.to_dict(),
            "markdown": render_readiness_markdown(report),
        }

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
    """Mount streamable HTTP MCP at /mcp (optional dependency)."""
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

    mcp = build_fastmcp(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    # Creating the ASGI app initializes the session manager (needed for lifespan).
    inner = mcp.streamable_http_app()
    mcp_holder["session_manager"] = mcp.session_manager

    class _McpGateMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if not request.url.path.startswith("/mcp"):
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

    app.add_middleware(_McpGateMiddleware)
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
