"""Core data types.

A Finding is the unit of truth in this system. Every sentence the explainer
produces must trace back to a Finding, and Findings are only ever produced by
deterministic code in checks.py -- never by an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass(frozen=True)
class Finding:
    id: str                      # stable identifier, e.g. SPF_TOO_MANY_LOOKUPS
    severity: str                # critical | high | medium | low | info
    title: str                   # one line, includes concrete evidence
    why: str                     # why it hurts cold-email deliverability
    fix: str                     # concrete remediation, may contain record text
    evidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def sort_key(self) -> tuple[int, str]:
        return (SEVERITY_ORDER[self.severity], self.id)


def prioritize(findings: list[Finding]) -> list[Finding]:
    """Most severe first; ties broken by id so output is deterministic."""
    return sorted(findings, key=lambda f: f.sort_key)
