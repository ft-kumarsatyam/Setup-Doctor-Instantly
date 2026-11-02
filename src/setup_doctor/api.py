"""Thin FastAPI surface for the free-tool use case.

POST /diagnose {"domain": "..."} -> findings JSON + rendered report.

Security posture (SSRF / internal probing):
- Hostnames are validated strictly (no IPs, schemes, paths, localhost, or
  internal-looking suffixes).
- DNS work uses the injected Resolver (LiveResolver by default) with a hard
  timeout; ResolverError becomes HTTP 502 with no fabricated findings.
- Per-IP rate limiting and a short response cache reduce abuse.

Privacy: request bodies and domain names are not logged by default — only
aggregate counts (status, findings count, duration, cache hit).
"""
from __future__ import annotations

import ipaddress
import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .explain import TemplateExplainer
from .graph import diagnose
from .resolver import LiveResolver, Resolver, ResolverError

log = logging.getLogger("setup_doctor.api")

MAX_DOMAIN_LEN = 253
DNS_TIMEOUT_SEC = 8.0
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SEC = 60.0
CACHE_TTL_SEC = 60.0
CACHE_MAX_ENTRIES = 256

# Hostnames that must never be accepted (SSRF / internal recon).
_BLOCKED_EXACT = frozenset({
    "localhost", "localhost.", "broadcasthost",
})
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".internal", ".intranet", ".corp", ".home",
    ".lan", ".localdomain", ".priv", ".private",
)
# Single label with no dot is almost always a local/short name, not a public DNS name.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$",
    re.I,
)


class DiagnoseRequest(BaseModel):
    domain: str = Field(..., min_length=1, max_length=MAX_DOMAIN_LEN + 32)


class DiagnoseResponse(BaseModel):
    domain: str
    findings: list[dict[str, Any]]
    report: str
    cached: bool = False


def validate_hostname(raw: str) -> str:
    """Normalize and accept only public-looking DNS hostnames.

    Rejects schemes, paths, ports, userinfo, IPs (v4/v6), localhost, and
    common internal suffixes. Raises ValueError with a safe, generic reason.
    """
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
    # Strip a single trailing dot (FQDN form), then reject ports.
    if lower.endswith("."):
        lower = lower[:-1]
    if ":" in lower:
        # Could be host:port or IPv6. IPv6 without brackets already rejected loosely;
        # host:port is not a bare hostname for this API.
        raise ValueError("domain must not include a port")
    try:
        ipaddress.ip_address(lower)
        raise ValueError("domain must not be an IP address")
    except ValueError as exc:
        if "must not be an IP" in str(exc):
            raise
        # Not an IP — continue.
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
            # Bound memory: drop idle keys occasionally.
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
                # Drop an arbitrary expired or oldest-ish entry.
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest_key, None)
            self._store[key] = (time.monotonic() + self.ttl, value)


ResolverFactory = Callable[[], Resolver]


def create_app(
    resolver_factory: ResolverFactory | None = None,
    *,
    rate_limiter: _RateLimiter | None = None,
    cache: _ResponseCache | None = None,
    dns_timeout: float = DNS_TIMEOUT_SEC,
) -> FastAPI:
    """Build the API app. Tests inject a FixtureResolver via resolver_factory."""
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sd-dns")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Setup Doctor", version="0.1.0", lifespan=lifespan)
    app.state.resolver_factory = resolver_factory or (lambda: LiveResolver())
    app.state.rate_limiter = rate_limiter or _RateLimiter()
    app.state.cache = cache or _ResponseCache()
    app.state.dns_timeout = dns_timeout
    app.state.executor = executor

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/diagnose", response_model=DiagnoseResponse)
    def diagnose_endpoint(body: DiagnoseRequest, request: Request, response: Response) -> DiagnoseResponse:
        started = time.monotonic()
        client_ip = (request.client.host if request.client else "unknown")

        try:
            domain = validate_hostname(body.domain)
        except ValueError as exc:
            _log_diag(400, 0, started, cached=False)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        limiter: _RateLimiter = app.state.rate_limiter
        if not limiter.allow(client_ip):
            _log_diag(429, 0, started, cached=False)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again in a minute.",
            )

        cached_hit = app.state.cache.get(domain)
        if cached_hit is not None:
            _log_diag(200, len(cached_hit.findings), started, cached=True)
            response.headers["X-Cache"] = "HIT"
            return cached_hit

        resolver = app.state.resolver_factory()
        try:
            future = app.state.executor.submit(
                _run_diagnose, domain, resolver,
            )
            state = future.result(timeout=app.state.dns_timeout)
        except FuturesTimeout as exc:
            future.cancel()
            _log_diag(504, 0, started, cached=False)
            raise HTTPException(
                status_code=504,
                detail="DNS checks timed out. No diagnosis was produced.",
            ) from exc
        except ResolverError as exc:
            _log_diag(502, 0, started, cached=False)
            raise HTTPException(
                status_code=502,
                detail=(
                    "Could not complete DNS checks (resolver error). "
                    "No diagnosis was produced — an outage is not the same as missing records."
                ),
            ) from exc
        except ValueError as exc:
            # e.g. NXDOMAIN refused by helper
            _log_diag(404, 0, started, cached=False)
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        payload = DiagnoseResponse(
            domain=domain,
            findings=[f.to_dict() for f in state["findings"]],
            report=state["report"],
            cached=False,
        )
        app.state.cache.set(domain, payload)
        _log_diag(200, len(payload.findings), started, cached=False)
        response.headers["X-Cache"] = "MISS"
        return payload

    return app


def _run_diagnose(domain: str, resolver: Resolver) -> dict:
    if isinstance(resolver, LiveResolver) and not resolver.domain_exists(domain):
        raise ValueError(
            f"{domain} does not exist in DNS (NXDOMAIN). "
            "Check the spelling; no diagnosis was produced."
        )
    return diagnose(domain, resolver, TemplateExplainer())


def _log_diag(status: int, findings: int, started: float, *, cached: bool) -> None:
    # Aggregate only — no domain names or request bodies.
    duration_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "diagnose status=%s findings=%s duration_ms=%s cached=%s",
        status, findings, duration_ms, cached,
    )


# Default app for `uvicorn setup_doctor.api:app`
app = create_app()
