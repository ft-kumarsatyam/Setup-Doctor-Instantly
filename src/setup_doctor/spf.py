"""SPF parsing helpers.

The one subtle piece is the 10-DNS-lookup limit (RFC 7208 section 4.6.4).
Terms that cost a lookup: include, a, mx, ptr, exists, and the redirect
modifier. ip4, ip6 and all are free. Nested includes count recursively, and
the same include appearing twice is charged twice.
"""
from __future__ import annotations

import re

from .resolver import Resolver

_QUALIFIERS = "+-~?"
_ALL_RE = re.compile(r"^[+\-~?]?all$", re.I)
_SPF_RE = re.compile(r"^v=spf1(\s|$)", re.I)
MAX_DEPTH = 10


def find_spf_records(txts: list[str]) -> list[str]:
    return [t.strip() for t in txts if _SPF_RE.match(t.strip())]


def terms(record: str) -> list[str]:
    return record.split()[1:]


def _is_lookup_term(t: str) -> bool:
    t = t.lstrip(_QUALIFIERS).lower()
    if t.startswith(("include:", "exists:", "redirect=")):
        return True
    if t == "ptr" or t.startswith("ptr:"):
        return True
    return any(t == m or t.startswith((m + ":", m + "/")) for m in ("a", "mx"))


def all_qualifier(record: str) -> str | None:
    """Return '+', '-', '~' or '?' for the 'all' term, or None if absent."""
    for t in terms(record):
        if _ALL_RE.match(t):
            return t[0] if t[0] in _QUALIFIERS else "+"
    return None


def has_redirect(record: str) -> bool:
    return any(t.lower().startswith("redirect=") for t in terms(record))


def uses_ptr(record: str) -> bool:
    return any(t.lstrip(_QUALIFIERS).lower().split(":")[0] == "ptr" for t in terms(record))


def count_lookups(domain: str, resolver: Resolver, _path: tuple[str, ...] = ()) -> tuple[int, bool]:
    """Return (lookup_count, loop_detected) for the SPF policy at `domain`."""
    domain = domain.lower().rstrip(".")
    if domain in _path or len(_path) > MAX_DEPTH:
        return 0, True
    records = find_spf_records(resolver.txt(domain))
    if not records:
        return 0, False
    total, loop = 0, False
    for term in terms(records[0]):
        if not _is_lookup_term(term):
            continue
        total += 1
        t = term.lstrip(_QUALIFIERS)
        target = None
        if t.lower().startswith("include:"):
            target = t.split(":", 1)[1]
        elif t.lower().startswith("redirect="):
            target = t.split("=", 1)[1]
        if target:
            sub, sub_loop = count_lookups(target, resolver, _path + (domain,))
            total += sub
            loop = loop or sub_loop
    return total, loop
