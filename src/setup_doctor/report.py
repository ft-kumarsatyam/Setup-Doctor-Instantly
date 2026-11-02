from __future__ import annotations

from collections import Counter

from .models import Finding

SOURCES = ("template", "model_verified", "template_fallback")


def render_markdown(domain: str, findings: list[Finding], explanation: str,
                    source: str, violations: list[str]) -> str:
    assert source in SOURCES, source
    counts = Counter(f.severity for f in findings)
    summary = ", ".join(f"{counts[s]} {s}" for s in ("critical", "high", "medium", "low", "info") if counts[s])
    lines = [f"# Setup Doctor report: {domain}", ""]
    lines.append(f"**Findings:** {summary or 'none'}")
    lines.append("")
    if findings:
        lines += ["| Severity | ID | Finding |", "|---|---|---|"]
        lines += [f"| {f.severity} | `{f.id}` | {f.title} |" for f in findings]
        lines.append("")
    lines += ["## Plan", "", explanation, ""]
    if source == "template":
        lines.append("_Explanation source: deterministic template (no model used)._")
    elif source == "model_verified":
        lines.append("_Explanation source: model draft, verified (JSON plan ids match findings; "
                     "DNS/numeric claims in explanations grounded; fixes taken from findings)._")
    else:
        lines.append("_Explanation source: deterministic template. The model draft was rejected by the "
                     f"grounding check ({'; '.join(violations)})._")
    lines += ["", "_Checks cover DNS only. They do not measure inbox placement or sender reputation._"]
    return "\n".join(lines)
