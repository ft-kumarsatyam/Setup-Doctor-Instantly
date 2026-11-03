"""Bulk domain diagnosis for agencies.

Reads a list of domains (CSV or plain lines), runs diagnose per domain, and
aggregates. Per-domain ResolverError becomes an error row — never fabricated
missing-SPF findings.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Iterable

from setup_doctor.core.result import DiagnosisResult
from setup_doctor.dns.resolver import Resolver, ResolverError
from setup_doctor.explain import Explainer, TemplateExplainer
from setup_doctor.pipeline import diagnose


@dataclass
class BulkRow:
    domain: str
    ok: bool
    result: DiagnosisResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "ok": self.ok,
            "error": self.error,
            "result": self.result.to_dict() if self.result else None,
        }


@dataclass
class BulkReport:
    rows: list[BulkRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.rows),
            "ok": sum(1 for r in self.rows if r.ok),
            "errors": sum(1 for r in self.rows if not r.ok),
            "rows": [r.to_dict() for r in self.rows],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Bulk Setup Doctor report",
            "",
            f"Domains: {len(self.rows)} · ok: {sum(1 for r in self.rows if r.ok)} · "
            f"errors: {sum(1 for r in self.rows if not r.ok)}",
            "",
            "| Domain | Status | Findings | Source |",
            "|---|---|---:|---|",
        ]
        for r in self.rows:
            if not r.ok:
                lines.append(f"| `{r.domain}` | error | — | {r.error} |")
            else:
                assert r.result is not None
                lines.append(
                    f"| `{r.domain}` | ok | {len(r.result.findings)} | "
                    f"{r.result.explanation_source} |"
                )
        lines.append("")
        return "\n".join(lines)


def parse_domain_list(text: str) -> list[str]:
    """Parse CSV (domain column or first column) or one domain per line."""
    text = text.strip()
    if not text:
        return []
    sample = text.splitlines()[0]
    if "," in sample or sample.lower().strip() in ("domain", "domains"):
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames:
            fields = [f.strip().lower() for f in reader.fieldnames]
            key = None
            for candidate in ("domain", "domains", "host", "hostname"):
                if candidate in fields:
                    key = reader.fieldnames[fields.index(candidate)]
                    break
            if key is None:
                key = reader.fieldnames[0]
            out = []
            for row in reader:
                val = (row.get(key) or "").strip()
                if val and val.lower() not in ("domain", "domains"):
                    out.append(val.lower().rstrip("."))
            return out
    return [
        line.strip().lower().rstrip(".")
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def run_bulk(
    domains: Iterable[str],
    resolver: Resolver,
    explainer: Explainer | None = None,
    *,
    dkim_selectors: tuple[str, ...],
    signals_factory=None,
) -> BulkReport:
    explainer = explainer or TemplateExplainer()
    report = BulkReport()
    for raw in domains:
        domain = raw.strip().lower().rstrip(".")
        if not domain:
            continue
        try:
            state = diagnose(domain, resolver, explainer, dkim_selectors)
            signals = signals_factory(domain) if signals_factory else None
            result = DiagnosisResult.from_state(state, signals=signals)
            report.rows.append(BulkRow(domain=domain, ok=True, result=result))
        except ResolverError as exc:
            report.rows.append(
                BulkRow(
                    domain=domain,
                    ok=False,
                    error=f"resolver error (not absence): {type(exc).__name__}",
                )
            )
    return report
