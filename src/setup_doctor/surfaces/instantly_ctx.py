"""Resolve InstantlyClient for surfaces without inventing signals.

Resolution order (hosted + API/MCP HTTP):
  1. Explicit api_key argument
  2. Request header X-Instantly-Api-Key
  3. Tenant vault lookup (optional; none until connect vault ships)
  4. Injected factory (tests / app default → often env)
  5. Process env INSTANTLY_API_KEY via InstantlyClient()
  6. ValueError → surfaces map to config error (never fake Instantly data)

Never log raw Instantly keys — use fingerprint helpers only.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from setup_doctor.integrations.instantly import InstantlyClient
from setup_doctor.surfaces.auth import Tenant, _fingerprint

HEADER_INSTANTLY_API_KEY = "X-Instantly-Api-Key"

InstantlyFactory = Callable[[], InstantlyClient]
TenantVault = Callable[[str], str | None]


def fingerprint_instantly_key(key: str) -> str:
    """Non-secret id for logs (same shape as Setup Doctor API key fingerprints)."""
    return _fingerprint(key)


def extract_instantly_header(headers: Mapping[str, str] | None) -> str | None:
    """Pull Instantly API key from a header map (case-insensitive)."""
    if not headers:
        return None
    wanted = HEADER_INSTANTLY_API_KEY.lower()
    for name, value in headers.items():
        if name.lower() == wanted:
            text = (value or "").strip()
            return text or None
    return None


def resolve_instantly_api_key(
    *,
    explicit: str | None = None,
    header_value: str | None = None,
    tenant: Tenant | None = None,
    vault: TenantVault | None = None,
) -> str | None:
    """Return an Instantly API key from request/tenant sources, or None."""
    if explicit is not None and explicit.strip():
        return explicit.strip()
    if header_value is not None and header_value.strip():
        return header_value.strip()
    if tenant is not None and vault is not None:
        stored = vault(tenant.tenant_id)
        if stored is not None and stored.strip():
            return stored.strip()
    return None


def resolve_instantly_client(
    *,
    explicit: str | None = None,
    header_value: str | None = None,
    tenant: Tenant | None = None,
    vault: TenantVault | None = None,
    env_fallback: bool = True,
    base_url: str | None = None,
    transport: Any | None = None,
    factory: InstantlyFactory | None = None,
) -> InstantlyClient:
    """Build InstantlyClient from the resolution order."""
    key = resolve_instantly_api_key(
        explicit=explicit,
        header_value=header_value,
        tenant=tenant,
        vault=vault,
    )
    if key is not None:
        return InstantlyClient(api_key=key, base_url=base_url, transport=transport)
    if factory is not None:
        return factory()
    if env_fallback:
        return InstantlyClient(base_url=base_url, transport=transport)
    raise ValueError(
        "Instantly API key not configured. Pass X-Instantly-Api-Key, "
        "connect a tenant key, or set INSTANTLY_API_KEY."
    )


def make_request_instantly_factory(
    *,
    header_value: str | None,
    tenant: Tenant | None = None,
    vault: TenantVault | None = None,
    base_factory: InstantlyFactory | None = None,
) -> InstantlyFactory:
    """Return a zero-arg factory closed over request Instantly credentials."""

    def _factory() -> InstantlyClient:
        return resolve_instantly_client(
            header_value=header_value,
            tenant=tenant,
            vault=vault,
            factory=base_factory,
        )

    return _factory
