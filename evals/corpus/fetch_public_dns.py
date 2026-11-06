"""Snapshot public DNS into a frozen corpus. Not run in CI.

Usage (from repo root, needs network):

    python evals/corpus/fetch_public_dns.py

Writes evals/corpus/_raw_snapshot.json. Lookups go through DNS-over-HTTPS
(Cloudflare, then Google) because some networks block UDP/53. A failed lookup
aborts that domain — an outage is not stored as "no record". The SPF
include/redirect/a/mx closure is stored so later offline checks see the same
tree the resolver saw.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from setup_doctor.checks.engine import DEFAULT_DKIM_SELECTORS  # noqa: E402
from setup_doctor.dns import spf  # noqa: E402
from setup_doctor.dns.resolver import ResolverError  # noqa: E402

# Public organizations only. The list is a sample frame, not a ranking.
DOMAINS = [
    "google.com",
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "cloudflare.com",
    "github.com",
    "stripe.com",
    "fastmail.com",
    "proton.me",
    "zoho.com",
    "wikipedia.org",
    "python.org",
    "ietf.org",
    "iana.org",
    "example.com",
    "example.org",
    "whitehouse.gov",
    "nasa.gov",
    "cisa.gov",
    "irs.gov",
    "state.gov",
    "cdc.gov",
    "nih.gov",
    "gsa.gov",
    "mozilla.org",
    "eff.org",
    "debian.org",
    "apache.org",
    "kernel.org",
    "w3.org",
    "bbc.co.uk",
    "nytimes.com",
    "shopify.com",
    "salesforce.com",
    "mailgun.com",
    "sendgrid.com",
    "instantly.ai",
    "internet.nl",
    "nic.cz",
    "who.int",
]

MAX_NAMES = 100
OUT = Path(__file__).resolve().parent / "_raw_snapshot.json"
_TXT_CHUNKS = re.compile(r'"([^"]*)"')
_DOH = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)


class DohResolver:
    """Minimal TXT/MX/A client. Status 3 or an empty answer is absence.
    Anything else (HTTP error, non-zero status) is an outage."""

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    def _answers(self, name: str, rtype: str) -> list[dict]:
        last = "no DoH endpoint answered"
        q = urllib.parse.urlencode({"name": name, "type": rtype})
        for base in _DOH:
            req = urllib.request.Request(
                f"{base}?{q}",
                headers={"accept": "application/dns-json", "user-agent": "setup-doctor-corpus/1"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                continue
            status = data.get("Status")
            if status == 3:
                return []
            if status != 0:
                last = f"rcode {status}"
                continue
            return list(data.get("Answer") or [])
        raise ResolverError(f"{rtype} lookup for {name} failed: {last}")

    def txt(self, name: str) -> list[str]:
        out = []
        for ans in self._answers(name, "TXT"):
            if ans.get("type") != 16:
                continue
            raw = ans.get("data") or ""
            chunks = _TXT_CHUNKS.findall(raw)
            out.append("".join(chunks) if chunks else raw.strip('"'))
        return out

    def mx(self, name: str) -> list[str]:
        hosts = []
        for ans in self._answers(name, "MX"):
            if ans.get("type") != 15:
                continue
            parts = str(ans.get("data") or "").split()
            if len(parts) >= 2:
                host = parts[-1].rstrip(".")
                # RFC 7505 null MX is "0 .". Keep a dot so the snapshot shows it.
                hosts.append(host if host else ".")
        return hosts

    def a(self, name: str) -> list[str]:
        return [
            str(ans.get("data"))
            for ans in self._answers(name, "A")
            if ans.get("type") == 1 and ans.get("data")
        ]


def _blank() -> dict:
    return {"TXT": [], "MX": [], "A": []}


def _walk_spf(resolver: DohResolver, records: dict, domain: str, path: tuple[str, ...]) -> None:
    """Follow include/redirect the same way count_lookups does (path depth, not a unique cap).

    A partial tree would look like void lookups offline. If the closure will not
    fit, the domain is skipped entirely.
    """
    domain = domain.lower().rstrip(".")
    if domain in path or len(path) > spf.MAX_DEPTH:
        return
    _ensure(resolver, records, domain)
    found = spf.find_spf_records(records[domain]["TXT"])
    if not found:
        return
    for term in spf.terms(found[0]):
        parsed = spf._mechanism_name_and_target(term, domain)  # same names the checker queries
        if parsed is None:
            continue
        kind, target = parsed
        target = target.lower().rstrip(".")
        _ensure(resolver, records, target)
        if kind in ("include", "redirect"):
            _walk_spf(resolver, records, target, path + (domain,))


def _ensure(resolver: DohResolver, records: dict, name: str) -> None:
    name = name.lower().rstrip(".")
    if name in records:
        return
    if len(records) > MAX_NAMES:
        raise RuntimeError(f"SPF closure exceeded {MAX_NAMES} names")
    slot = _blank()
    try:
        slot["TXT"] = resolver.txt(name)
        slot["MX"] = resolver.mx(name)
        slot["A"] = resolver.a(name)
    except ResolverError as exc:
        raise RuntimeError(str(exc)) from exc
    records[name] = slot


def snapshot_domain(domain: str) -> dict:
    resolver = DohResolver(timeout=12.0)
    records: dict[str, dict[str, list[str]]] = {}
    _ensure(resolver, records, domain)
    _ensure(resolver, records, f"_dmarc.{domain}")
    for sel in DEFAULT_DKIM_SELECTORS:
        _ensure(resolver, records, f"{sel}._domainkey.{domain}")
    _walk_spf(resolver, records, domain, ())
    # Drop empty names. FixtureResolver treats a missing name as [].
    compact = {
        name: {k: v for k, v in slot.items() if v}
        for name, slot in records.items()
        if any(slot.values())
    }
    return {"domain": domain, "records": compact}


def main() -> int:
    rows = []
    skipped = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(snapshot_domain, d): d for d in DOMAINS}
        for fut in as_completed(futs):
            domain = futs[fut]
            try:
                rows.append(fut.result())
                print(f"ok {domain}", flush=True)
            except Exception as exc:  # network, closure cap, or DNS outage
                skipped.append({"domain": domain, "error": f"{type(exc).__name__}: {exc}"})
                print(f"skip {domain}: {exc}", flush=True)
    rows.sort(key=lambda r: r["domain"])
    payload = {
        "fetched_purpose": "raw public DNS snapshot; labels are applied in a later step",
        "cases": rows,
        "skipped": skipped,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT} cases={len(rows)} skipped={len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
