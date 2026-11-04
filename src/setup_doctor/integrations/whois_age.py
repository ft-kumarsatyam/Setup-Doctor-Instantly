"""Optional domain-age / WHOIS advisory signal (never a DNS Finding).

Lookup failures ⇒ unknown / not_checked. Opt-in only.
"""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class DomainAgeSignal:
    domain: str
    status: str  # ok | unknown | not_checked
    created_at: str | None = None
    age_days: int | None = None
    note: str = ""
    source: str = "rdap"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_created(events: list[Any]) -> datetime | None:
    for ev in events:
        if not isinstance(ev, dict):
            continue
        action = str(ev.get("eventAction") or "").lower()
        if action in ("registration", "registered", "create", "created"):
            raw = ev.get("eventDate")
            if isinstance(raw, str) and raw:
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
    return None


def lookup_domain_age(
    domain: str,
    *,
    transport=None,
    timeout: float = 8.0,
) -> DomainAgeSignal:
    """RDAP domain age via rdap.org. Failures → unknown (never invent age)."""
    host = domain.strip().lower().rstrip(".")
    if not host or not re.match(r"^[a-z0-9.-]+$", host):
        return DomainAgeSignal(
            domain=domain,
            status="unknown",
            note="Invalid domain for RDAP lookup.",
        )
    url = f"https://rdap.org/domain/{host}"
    try:
        if transport is not None:
            status, raw = transport(url)
        else:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/rdap+json, application/json", "User-Agent": "setup-doctor/0.2"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = int(resp.status)
                raw = resp.read()
        if status != 200:
            return DomainAgeSignal(
                domain=host,
                status="unknown",
                note=f"RDAP HTTP {status}; age not checked.",
            )
        import json
        data = json.loads(raw.decode("utf-8"))
        created = _parse_created(list(data.get("events") or []))
        if created is None:
            return DomainAgeSignal(
                domain=host,
                status="unknown",
                note="RDAP response missing registration eventDate.",
            )
        now = datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(0, int((now - created).total_seconds() // 86400))
        return DomainAgeSignal(
            domain=host,
            status="ok",
            created_at=created.isoformat(),
            age_days=age_days,
            note=f"Domain age ~{age_days} day(s) per RDAP (advisory only).",
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, OSError) as exc:
        return DomainAgeSignal(
            domain=host,
            status="unknown",
            note=f"RDAP lookup failed ({type(exc).__name__}); age unknown.",
        )
