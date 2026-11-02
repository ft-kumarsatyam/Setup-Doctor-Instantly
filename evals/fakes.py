"""Scripted stand-ins for an LLM, one per failure mode we want the guardrail to handle.

Each takes the prompt string (like a real completer) and returns text. They parse
the findings JSON out of the prompt so they behave like a model that was shown
the same input. The LLM contract is a JSON list of {id, explanation}.
"""
from __future__ import annotations

import json
import re

_JSON_RE = re.compile(r"Findings \(JSON\):\n(.*)\Z", re.S)
_NEEDS_LOOKUPS = re.compile(r"needs (\d+) DNS lookups", re.I)


def _findings(prompt: str) -> list[dict]:
    return json.loads(_JSON_RE.search(prompt).group(1))


def _faithful_items(findings: list[dict], skip_first_severe: bool = False) -> list[dict]:
    items, skipped = [], False
    for f in findings:
        if skip_first_severe and not skipped and f["severity"] in ("critical", "high"):
            skipped = True
            continue
        items.append({"id": f["id"], "explanation": f["why"]})
    return items


def _dumps(items: list[dict]) -> str:
    return json.dumps(items, indent=2)


def faithful(prompt: str) -> str:
    """One object per finding; explanation copied from the finding why."""
    return _dumps(_faithful_items(_findings(prompt)))


def hallucinated_finding(prompt: str) -> str:
    """Adds a problem that no check found."""
    items = _faithful_items(_findings(prompt))
    items.append({
        "id": "SPF_DOMAIN_SPOOFED",
        "explanation": "Your domain is being spoofed right now.",
    })
    return _dumps(items)


def hallucinated_record(prompt: str) -> str:
    """Suggests a DNS record the system never produced."""
    items = _faithful_items(_findings(prompt))
    if items:
        items[0]["explanation"] += (
            " Also publish `v=spf1 include:totally-made-up.test -all` for safety."
        )
    return _dumps(items)


def drops_severe_finding(prompt: str) -> str:
    """Silently omits the first critical/high finding."""
    return _dumps(_faithful_items(_findings(prompt), skip_first_severe=True))


def misstates_numbers(prompt: str) -> str:
    """Cites real ids but puts a wrong lookup count in an explanation."""
    items = []
    for f in _findings(prompt):
        expl = f["why"]
        m = _NEEDS_LOOKUPS.search(f["title"])
        if m:
            wrong = int(m.group(1)) + 3
            expl = f"This record needs {wrong} DNS lookups, which exceeds the limit."
        items.append({"id": f["id"], "explanation": expl})
    return _dumps(items)


def malformed_json(prompt: str) -> str:
    """Returns text that is not valid JSON."""
    return '{"id": "SPF_MISSING", "explanation": "broken"'


def duplicate_ids(prompt: str) -> str:
    """Repeats the first finding id so set equality fails."""
    items = _faithful_items(_findings(prompt))
    if items:
        items.append({"id": items[0]["id"], "explanation": items[0]["explanation"]})
    return _dumps(items)


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
    "malformed_json": malformed_json,
    "duplicate_ids": duplicate_ids,
    "raises": raises,
    "empty": empty,
}
