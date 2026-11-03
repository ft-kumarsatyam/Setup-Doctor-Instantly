"""Check registry: named packs of deterministic finding producers.

Surfaces (CLI/API/MCP/skills) call run_checks / registry.run — never reimplement
SPF/DKIM logic. New packs register here and must ship fixture + mutant coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import Finding, prioritize
from .resolver import Resolver

CheckFn = Callable[[str, Resolver], list[Finding]]
DkimCheckFn = Callable[[str, Resolver, tuple[str, ...]], list[Finding]]


@dataclass(frozen=True)
class CheckSpec:
    """One deterministic check unit."""

    id: str                 # stable pack/check name, e.g. "spf", "bimi"
    pack: str               # pack group: dns_auth | deliverability
    description: str
    # Either plain (domain, resolver) or dkim-style (domain, resolver, selectors)
    kind: str = "plain"     # plain | dkim


class CheckRegistry:
    """Ordered registry of check callables."""

    def __init__(self) -> None:
        self._plain: list[tuple[CheckSpec, CheckFn]] = []
        self._dkim: tuple[CheckSpec, DkimCheckFn] | None = None

    def register_plain(self, spec: CheckSpec, fn: CheckFn) -> None:
        if spec.kind != "plain":
            raise ValueError(f"{spec.id}: kind must be plain")
        self._plain.append((spec, fn))

    def register_dkim(self, spec: CheckSpec, fn: DkimCheckFn) -> None:
        if spec.kind != "dkim":
            raise ValueError(f"{spec.id}: kind must be dkim")
        self._dkim = (spec, fn)

    def specs(self) -> list[CheckSpec]:
        out = [s for s, _ in self._plain]
        if self._dkim:
            out.append(self._dkim[0])
        return out

    def run(
        self,
        domain: str,
        resolver: Resolver,
        *,
        dkim_selectors: tuple[str, ...],
        packs: frozenset[str] | None = None,
    ) -> list[Finding]:
        """Run registered checks. packs filters by CheckSpec.pack when set."""
        domain = domain.strip().lower().rstrip(".")
        findings: list[Finding] = []
        for spec, fn in self._plain:
            if packs is not None and spec.pack not in packs:
                continue
            findings.extend(fn(domain, resolver))
        if self._dkim is not None:
            spec, fn = self._dkim
            if packs is None or spec.pack in packs:
                findings.extend(fn(domain, resolver, dkim_selectors))
        return prioritize(findings)


def build_default_registry() -> CheckRegistry:
    """Wire the shipping DNS-auth checks. Imported lazily to avoid cycles."""
    from . import checks as c

    reg = CheckRegistry()
    reg.register_plain(
        CheckSpec("spf", "dns_auth", "SPF record health"),
        c.check_spf,
    )
    reg.register_dkim(
        CheckSpec("dkim", "dns_auth", "DKIM key presence and strength", kind="dkim"),
        c.check_dkim,
    )
    reg.register_plain(
        CheckSpec("dmarc", "dns_auth", "DMARC policy and reporting"),
        c.check_dmarc,
    )
    reg.register_plain(
        CheckSpec("mx", "dns_auth", "MX presence for receiving mail"),
        c.check_mx,
    )
    # Advisory packs are opt-in so synthetic detection fixtures stay stable.
    reg.register_plain(
        CheckSpec("bimi", "dns_auth_advisory", "BIMI record (advisory)"),
        c.check_bimi,
    )
    reg.register_plain(
        CheckSpec("mta_sts", "dns_auth_advisory", "MTA-STS policy DNS (advisory)"),
        c.check_mta_sts,
    )
    reg.register_plain(
        CheckSpec("tls_rpt", "dns_auth_advisory", "TLS-RPT reporting (advisory)"),
        c.check_tls_rpt,
    )
    return reg


# Core cold-email auth packs used when callers do not opt into advisory checks.
DEFAULT_PACKS = frozenset({"dns_auth"})
ALL_DNS_PACKS = frozenset({"dns_auth", "dns_auth_advisory"})

_DEFAULT: CheckRegistry | None = None


def get_default_registry() -> CheckRegistry:
    """Lazy singleton so checks.py can finish loading before we import it."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = build_default_registry()
    return _DEFAULT
