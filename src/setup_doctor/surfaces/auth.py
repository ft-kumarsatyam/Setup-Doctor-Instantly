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
        # People often paste the whole env value `key:tenant` — accept that too.
        candidates = [token]
        if ":" in token:
            candidates.append(token.split(":", 1)[0].strip())
        if not token:
            raise PermissionError(
                "Setup Doctor API key required. Open Advanced on the checker, "
                "or send header X-API-Key. Ask your host for the key they set in "
                "SETUP_DOCTOR_API_KEYS (there is no public signup)."
            )
        for candidate in candidates:
            if candidate and candidate in self._keys:
                return Tenant(
                    api_key_id=_fingerprint(candidate),
                    tenant_id=self._keys[candidate],
                )
        raise PermissionError(
            "That Setup Doctor API key is not recognized. "
            "Use only the key part (example: loom-demo), not your Instantly key. "
            "Ask your host to confirm SETUP_DOCTOR_API_KEYS on this server."
        )
