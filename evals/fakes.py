"""Scripted stand-ins for an LLM, one per failure mode we want the guardrail to handle.

Each takes the prompt string (like a real completer) and returns text. They parse
the findings JSON out of the prompt so they behave like a model that was shown
the same input.
"""
from __future__ import annotations

import json
import re

_JSON_RE = re.compile(r"Findings \(JSON\):\n(.*)\Z", re.S)


def _findings(prompt: str) -> list[dict]:
    return json.loads(_JSON_RE.search(prompt).group(1))


def _faithful_lines(findings: list[dict], skip_first_severe: bool = False) -> list[str]:
    lines, skipped = [], False
    for i, f in enumerate(findings, 1):
        if skip_first_severe and not skipped and f["severity"] in ("critical", "high"):
            skipped = True
            continue
        lines.append(f"{i}. [{f['id']}] {f['title']}. Fix: {f['fix']}")
    return lines


def faithful(prompt: str) -> str:
    """Rewrites every finding, cites ids, copies record text only from fixes."""
    return "Here is your plan:\n" + "\n".join(_faithful_lines(_findings(prompt)))


def hallucinated_finding(prompt: str) -> str:
    """Adds a problem that no check found."""
    return faithful(prompt) + "\n99. [SPF_DOMAIN_SPOOFED] Your domain is being spoofed right now."


def hallucinated_record(prompt: str) -> str:
    """Suggests a DNS record the system never produced."""
    return faithful(prompt) + "\nAlso publish `v=spf1 include:totally-made-up.test -all` for safety."


def drops_severe_finding(prompt: str) -> str:
    """Silently omits the first critical/high finding."""
    return "Here is your plan:\n" + "\n".join(_faithful_lines(_findings(prompt), skip_first_severe=True))


def misstates_numbers(prompt: str) -> str:
    """Cites real ids and real records but changes a number. KNOWN GAP: the verifier
    checks ids and records, not numeric claims, so this is not caught."""
    text = faithful(prompt)
    return re.sub(r"needs (\d+) DNS lookups", lambda m: f"needs {int(m.group(1)) + 3} DNS lookups", text)


def raises(prompt: str) -> str:
    raise RuntimeError("simulated API outage")


def empty(prompt: str) -> str:
    return ""


# Strings the hallucinating fakes inject. The eval searches delivered text for these
# independently of the verifier, so a broken verifier cannot hide its own leaks.
PLANTED_MARKERS = {
    "hallucinated_finding": "SPF_DOMAIN_SPOOFED",
    "hallucinated_record": "totally-made-up.test",
}

BEHAVIORS = {
    "faithful": faithful,
    "hallucinated_finding": hallucinated_finding,
    "hallucinated_record": hallucinated_record,
    "drops_severe_finding": drops_severe_finding,
    "misstates_numbers": misstates_numbers,
    "raises": raises,
    "empty": empty,
}
