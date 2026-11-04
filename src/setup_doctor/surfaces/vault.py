"""Encrypted-at-rest Instantly API key vault per Setup Doctor tenant.

Env:
  SETUP_DOCTOR_VAULT_KEY — required master secret for encrypt/decrypt
  SETUP_DOCTOR_VAULT_PATH — optional JSON file path (default: in-memory only)

Never logs raw Instantly keys. Stdlib only (PBKDF2 + HMAC-SHA256 + keystream).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from setup_doctor.surfaces.auth import _fingerprint

_VAULT_VERSION = 1
_SALT_LEN = 16
_NONCE_LEN = 16


def _derive_stream(master: str, salt: bytes, nonce: bytes, length: int) -> bytes:
    seed = hashlib.pbkdf2_hmac(
        "sha256",
        master.encode("utf-8"),
        salt + nonce,
        iterations=120_000,
        dklen=32,
    )
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            seed,
            nonce + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def seal(master: str, plaintext: str) -> str:
    """Return URL-safe token: version.salt.nonce.ciphertext.mac (all b64)."""
    raw = plaintext.encode("utf-8")
    salt = secrets.token_bytes(_SALT_LEN)
    nonce = secrets.token_bytes(_NONCE_LEN)
    stream = _derive_stream(master, salt, nonce, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
    mac = hmac.new(
        hashlib.pbkdf2_hmac("sha256", master.encode("utf-8"), salt, 120_000, dklen=32),
        nonce + cipher,
        hashlib.sha256,
    ).digest()
    parts = [
        str(_VAULT_VERSION),
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(nonce).decode(),
        base64.urlsafe_b64encode(cipher).decode(),
        base64.urlsafe_b64encode(mac).decode(),
    ]
    return ".".join(parts)


def unseal(master: str, token: str) -> str:
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != str(_VAULT_VERSION):
        raise ValueError("Invalid vault token")
    salt = base64.urlsafe_b64decode(parts[1])
    nonce = base64.urlsafe_b64decode(parts[2])
    cipher = base64.urlsafe_b64decode(parts[3])
    mac = base64.urlsafe_b64decode(parts[4])
    expected = hmac.new(
        hashlib.pbkdf2_hmac("sha256", master.encode("utf-8"), salt, 120_000, dklen=32),
        nonce + cipher,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Vault MAC mismatch")
    stream = _derive_stream(master, salt, nonce, len(cipher))
    raw = bytes(a ^ b for a, b in zip(cipher, stream, strict=True))
    return raw.decode("utf-8")


class EncryptedTenantVault:
    """Map tenant_id -> sealed Instantly API key."""

    def __init__(
        self,
        master_key: str | None = None,
        *,
        path: str | Path | None = None,
    ):
        self._master = (master_key if master_key is not None else os.environ.get("SETUP_DOCTOR_VAULT_KEY", "")).strip()
        env_path = os.environ.get("SETUP_DOCTOR_VAULT_PATH", "").strip()
        self._path = Path(path) if path is not None else (Path(env_path) if env_path else None)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        if self._path and self._path.is_file():
            self._load()

    @property
    def configured(self) -> bool:
        return bool(self._master)

    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text())
        if isinstance(raw, dict):
            self._data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        tmp.replace(self._path)

    def put(self, tenant_id: str, instantly_api_key: str) -> str:
        if not self._master:
            raise ValueError(
                "Vault disabled. Set SETUP_DOCTOR_VAULT_KEY to store Instantly keys."
            )
        key = instantly_api_key.strip()
        if not key:
            raise ValueError("Instantly API key is required")
        tid = tenant_id.strip() or "default"
        sealed = seal(self._master, key)
        fp = _fingerprint(key)
        with self._lock:
            self._data[tid] = {"sealed": sealed, "fingerprint": fp}
            self._persist()
        return fp

    def get(self, tenant_id: str) -> str | None:
        if not self._master:
            return None
        tid = tenant_id.strip() or "default"
        with self._lock:
            row = self._data.get(tid)
        if not row or not isinstance(row.get("sealed"), str):
            return None
        try:
            return unseal(self._master, row["sealed"])
        except ValueError:
            return None

    def delete(self, tenant_id: str) -> bool:
        tid = tenant_id.strip() or "default"
        with self._lock:
            existed = tid in self._data
            self._data.pop(tid, None)
            if existed:
                self._persist()
            return existed

    def status(self, tenant_id: str) -> dict[str, Any]:
        tid = tenant_id.strip() or "default"
        with self._lock:
            row = self._data.get(tid)
        if not row:
            return {"connected": False, "fingerprint": None, "vault_configured": self.configured}
        return {
            "connected": True,
            "fingerprint": row.get("fingerprint"),
            "vault_configured": self.configured,
        }

    def as_lookup(self):
        """Callable compatible with TenantVault protocol."""

        def _lookup(tenant_id: str) -> str | None:
            return self.get(tenant_id)

        return _lookup


def default_vault_from_env() -> EncryptedTenantVault | None:
    """Return a vault when SETUP_DOCTOR_VAULT_KEY is set; else None."""
    if not os.environ.get("SETUP_DOCTOR_VAULT_KEY", "").strip():
        return None
    return EncryptedTenantVault()
