"""One structured log line per diagnosis.

Domains are never logged in plaintext by default. A short SHA-256 prefix is
always included for correlation; set SETUP_DOCTOR_LOG_DOMAIN=1 to also emit
the bare hostname (ops opt-in only).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Iterable

log = logging.getLogger("setup_doctor.diagnosis")

SOURCES = frozenset({"template", "model_verified", "template_fallback"})


def domain_hash(domain: str) -> str:
    return hashlib.sha256(domain.strip().lower().encode("utf-8")).hexdigest()[:16]


def log_diagnosis(
    *,
    explanation_source: str,
    findings_count: int,
    duration_ms: int,
    rejection_reasons: Iterable[str] | None = None,
    domain: str | None = None,
    cached: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a single JSON log line. Safe to call from CLI, graph, or API."""
    if explanation_source not in SOURCES and explanation_source != "unavailable":
        explanation_source = "unavailable"
    payload: dict[str, Any] = {
        "event": "diagnosis",
        "explanation_source": explanation_source,
        "findings_count": int(findings_count),
        "duration_ms": int(duration_ms),
        "rejection_reasons": list(rejection_reasons or []),
        "cached": bool(cached),
    }
    if domain:
        payload["domain_hash"] = domain_hash(domain)
        if os.environ.get("SETUP_DOCTOR_LOG_DOMAIN", "").strip() == "1":
            payload["domain"] = domain.strip().lower().rstrip(".")
    if extra:
        # Drop any accidental domain key from callers unless opt-in already set.
        safe_extra = {k: v for k, v in extra.items() if k != "domain" or "domain" in payload}
        payload.update(safe_extra)
    log.info("%s", json.dumps(payload, sort_keys=True, default=str))
