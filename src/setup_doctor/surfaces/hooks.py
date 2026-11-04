"""Signed Instantly provisioning webhook helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


def sign_payload(secret: str, body: bytes, *, timestamp: str | None = None) -> str:
    ts = timestamp or str(int(time.time()))
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secret: str, body: bytes, header: str | None, *, max_age_sec: int = 300) -> bool:
    if not secret or not header:
        return False
    parts = dict(
        p.split("=", 1) for p in header.split(",") if "=" in p
    )
    ts = parts.get("t")
    sig = parts.get("v1")
    if not ts or not sig:
        return False
    try:
        age = abs(time.time() - float(ts))
    except ValueError:
        return False
    if age > max_age_sec:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def extract_domains(payload: dict[str, Any]) -> list[str]:
    """Pull sender domains from Instantly-ish webhook payloads."""
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        d = raw.strip().lower().rstrip(".")
        if "@" in d:
            d = d.split("@", 1)[1]
        if d and d not in seen:
            seen.add(d)
            out.append(d)

    for key in ("domains", "domain_list"):
        val = payload.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict) and item.get("domain"):
                    add(str(item["domain"]))
    domain = payload.get("domain")
    if isinstance(domain, str):
        add(domain)
    email = payload.get("email")
    if isinstance(email, str) and "@" in email:
        add(email)
    account = payload.get("account")
    if isinstance(account, dict):
        if isinstance(account.get("email"), str):
            add(account["email"])
        if isinstance(account.get("domain"), str):
            add(account["domain"])
    return out


def parse_json_body(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8") or "{}")
    if not isinstance(data, dict):
        raise ValueError("webhook body must be a JSON object")
    return data
