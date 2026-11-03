"""DNS access behind a tiny interface.

Checks never touch the network directly. They take a Resolver, so the same
code runs against live DNS in production (LiveResolver) and against frozen
records in tests and evals (FixtureResolver). That is what makes the eval
suite reproducible.
"""
from __future__ import annotations

from typing import Protocol


class Resolver(Protocol):
    def txt(self, name: str) -> list[str]: ...
    def mx(self, name: str) -> list[str]: ...
    def a(self, name: str) -> list[str]: ...


class FixtureResolver:
    """records = {"example.test": {"TXT": [...], "MX": [...], "A": ["192.0.2.1"]}}"""

    def __init__(self, records: dict[str, dict[str, list[str]]]):
        self._records = {k.lower().rstrip("."): v for k, v in records.items()}

    def txt(self, name: str) -> list[str]:
        return list(self._records.get(name.lower().rstrip("."), {}).get("TXT", []))

    def mx(self, name: str) -> list[str]:
        return list(self._records.get(name.lower().rstrip("."), {}).get("MX", []))

    def a(self, name: str) -> list[str]:
        return list(self._records.get(name.lower().rstrip("."), {}).get("A", []))


class ResolverError(RuntimeError):
    """DNS could not be answered (timeout, no nameservers, network down).

    Deliberately distinct from 'the record does not exist'. A diagnostic tool that
    treats an outage as 'no SPF, no DMARC, no MX' would confidently misdiagnose.
    """


class LiveResolver:
    """Real DNS via dnspython. NXDOMAIN / no-answer mean 'absent' and return [];
    anything else (timeout, SERVFAIL, no network) raises ResolverError."""

    def __init__(self, timeout: float = 4.0):
        import dns.exception
        import dns.resolver  # imported lazily so fixtures work without network deps

        self._dns_nxdomain = dns.resolver.NXDOMAIN
        self._absent = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)
        self._resolver = dns.resolver.Resolver()
        self._resolver.lifetime = timeout
        self._resolver.timeout = timeout

    def _query(self, name: str, rtype: str):
        try:
            return self._resolver.resolve(name, rtype)
        except self._absent:
            return []
        except Exception as exc:  # Timeout, NoNameservers, YXDOMAIN, socket errors...
            raise ResolverError(f"{rtype} lookup for {name} failed: {type(exc).__name__}") from exc

    def domain_exists(self, name: str) -> bool:
        """False only for a definite NXDOMAIN at the name itself. NoAnswer means the name
        exists but has no SOA (normal for subdomains). Outages raise ResolverError."""
        try:
            self._resolver.resolve(name, "SOA")
            return True
        except self._dns_nxdomain:
            return False
        except self._absent:
            return True
        except Exception as exc:
            raise ResolverError(f"SOA lookup for {name} failed: {type(exc).__name__}") from exc

    def txt(self, name: str) -> list[str]:
        out = []
        for rdata in self._query(name, "TXT"):
            # TXT rdata is split into <=255-byte chunks; rejoin them.
            out.append(b"".join(rdata.strings).decode("utf-8", "replace"))
        return out

    def mx(self, name: str) -> list[str]:
        return [str(r.exchange).rstrip(".") for r in self._query(name, "MX")]

    def a(self, name: str) -> list[str]:
        return [r.address for r in self._query(name, "A")]
