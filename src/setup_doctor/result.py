"""Versioned diagnosis contract shared by CLI, API, MCP, and skills.

Findings remain the only ground truth. Optional signals (Instantly, reputation)
are side-channel reports that never invent health when data is missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Finding

SCHEMA_VERSION = "1.0"


@dataclass
class DiagnosisSignals:
    """Optional non-DNS side reports. Missing data stays explicit."""

    instantly: list[dict[str, Any]] | None = None
    reputation: list[dict[str, Any]] | None = None
    not_checked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instantly": self.instantly,
            "reputation": self.reputation,
            "not_checked": list(self.not_checked),
        }


@dataclass
class DiagnosisResult:
    """Stable product payload. schema_version bumps only on breaking changes."""

    domain: str
    findings: list[Finding]
    explanation: str
    explanation_source: str
    report: str
    schema_version: str = SCHEMA_VERSION
    plan_items: list[dict[str, str]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    used_fallback: bool = False
    signals: DiagnosisSignals | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "findings": [f.to_dict() for f in self.findings],
            "explanation": self.explanation,
            "explanation_source": self.explanation_source,
            "report": self.report,
            "plan_items": list(self.plan_items),
            "violations": list(self.violations),
            "used_fallback": self.used_fallback,
            "signals": self.signals.to_dict() if self.signals else None,
        }

    @classmethod
    def from_state(
        cls,
        state: dict[str, Any],
        *,
        signals: DiagnosisSignals | None = None,
    ) -> DiagnosisResult:
        return cls(
            domain=state["domain"],
            findings=list(state.get("findings") or []),
            explanation=state.get("explanation") or "",
            explanation_source=state.get("explanation_source") or "unavailable",
            report=state.get("report") or "",
            plan_items=list(state.get("plan_items") or []),
            violations=list(state.get("violations") or []),
            used_fallback=bool(state.get("used_fallback", False)),
            signals=signals,
        )
