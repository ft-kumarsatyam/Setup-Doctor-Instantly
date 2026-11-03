"""API key auth for the product HTTP surface.

Env:
  SETUP_DOCTOR_API_KEYS — comma-separated keys, optional `key:tenant` form.
  If unset/empty, auth is disabled (local/dev open mode).

Never log raw keys.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Tenant:
    api_key_id: str   # short non-secret fingerprint for logs
    tenant_id: str


def _fingerprint(key: str) -> str:
    return f"k_{key[:4]}…{len(key)}" if len(key) >= 4 else "k_short"


def load_api_keys(raw: str | None = None) -> dict[str, str]:
    """Map api_key -> tenant_id."""
    text = raw if raw is not None else os.environ.get("SETUP_DOCTOR_API_KEYS", "")
    mapping: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, tenant = part.split(":", 1)
            key, tenant = key.strip(), tenant.strip() or "default"
        else:
            key, tenant = part, "default"
        if key:
            mapping[key] = tenant
    return mapping


class ApiKeyAuth:
    """Optional API-key gate. When no keys configured, allow all (dev)."""

    def __init__(self, keys: dict[str, str] | None = None):
        self._keys = keys if keys is not None else load_api_keys()

    @property
    def required(self) -> bool:
        return bool(self._keys)

    def authenticate(self, header_value: str | None, bearer: str | None = None) -> Tenant | None:
        """Return Tenant if ok; None if auth disabled; raise PermissionError if bad."""
        if not self._keys:
            return None
        token = (header_value or "").strip() or (bearer or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token or token not in self._keys:
            raise PermissionError("Invalid or missing API key")
        return Tenant(api_key_id=_fingerprint(token), tenant_id=self._keys[token])
