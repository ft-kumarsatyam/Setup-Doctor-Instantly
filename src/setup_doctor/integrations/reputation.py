"""Reputation / blocklist adapters.

Without a configured provider, checks are reported as not_checked — never as
clean. Findings are not invented from absent data.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass
class ReputationSignal:
    provider: str
    domain: str
    listed: bool | None  # None => unknown / not checked
    lists: list[str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReputationProvider(Protocol):
    name: str

    def check_domain(self, domain: str) -> ReputationSignal: ...


class NullReputationProvider:
    """Default: explicitly not checked."""

    name = "none"

    def check_domain(self, domain: str) -> ReputationSignal:
        return ReputationSignal(
            provider=self.name,
            domain=domain,
            listed=None,
            lists=[],
            note="No reputation provider configured; listing status is unknown (not healthy by default).",
        )


class StaticListProvider:
    """Fixture/dev provider: domains in SETUP_DOCTOR_REPUTATION_LISTED are listed."""

    name = "static_list"

    def __init__(self, listed: frozenset[str]):
        self._listed = {d.lower().rstrip(".") for d in listed}

    def check_domain(self, domain: str) -> ReputationSignal:
        d = domain.lower().rstrip(".")
        if d in self._listed:
            return ReputationSignal(
                provider=self.name,
                domain=d,
                listed=True,
                lists=["static"],
                note="Domain appears on the configured static reputation list.",
            )
        return ReputationSignal(
            provider=self.name,
            domain=d,
            listed=False,
            lists=[],
            note="Domain not on the configured static list (other lists not queried).",
        )


def get_reputation_provider() -> ReputationProvider:
    raw = os.environ.get("SETUP_DOCTOR_REPUTATION_LISTED", "").strip()
    if raw:
        return StaticListProvider(frozenset(x.strip() for x in raw.split(",") if x.strip()))
    provider = os.environ.get("SETUP_DOCTOR_REPUTATION_PROVIDER", "").strip().lower()
    if provider in ("", "none", "null"):
        return NullReputationProvider()
    if provider == "static_list":
        return StaticListProvider(frozenset())
    # Unknown provider name — still do not fabricate clean.
    return NullReputationProvider()


def check_reputation(domain: str, provider: ReputationProvider | None = None) -> list[dict[str, Any]]:
    prov = provider or get_reputation_provider()
    return [prov.check_domain(domain).to_dict()]
