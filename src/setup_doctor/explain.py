"""Explanation layer plus the grounding guardrail.

The LLM never decides what is wrong. It only rewrites verified Findings into
a prioritized plan. The model must return JSON; verify_plan() checks id set
equality and grounds DNS/numeric claims in explanation strings only. Validated
plans are rendered deterministically from finding title/fix plus the model's
short explanation. Rejected drafts fall back to TemplateExplainer.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Protocol

from .models import Finding

_ID_RE = re.compile(r"\[([A-Z][A-Z0-9_]+)\]")
_CODE_RE = re.compile(r"`([^`]+)`")
_RECORD_RE = re.compile(r"v=(spf1|dmarc1|dkim1)", re.I)
_NUM_RE = re.compile(r"\d+")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
# Allow-listed claim shapes only — not arbitrary digits in prose or fix advice.
_NUMERIC_CLAIM_RES = [
    re.compile(r"needs (\d+) DNS lookups", re.I),
    re.compile(r"limit is (\d+)", re.I),
    re.compile(r"pct\s*=\s*(\d+)", re.I),
    re.compile(r"only (\d+)%", re.I),
    re.compile(r"(\d+)% of mail", re.I),
]


class Explainer(Protocol):
    def explain(self, findings: list[Finding]) -> str: ...


class TemplateExplainer:
    """Deterministic, always grounded. Used directly and as the fallback."""

    def explain(self, findings: list[Finding]) -> str:
        if not findings:
            return "No issues found in the SPF, DKIM, DMARC and MX checks."
        lines = ["Fix in this order:", ""]
        for i, f in enumerate(findings, 1):
            lines += [
                f"{i}. **[{f.id}]** ({f.severity}) {f.title}",
                f"   - Why it matters: {f.why}",
                f"   - Fix: {f.fix}",
                "",
            ]
        return "\n".join(lines).rstrip()


PROMPT = """You are explaining DNS email-authentication findings to a sender setting up cold email.

Return ONLY a JSON array (no markdown fences, no prose outside the JSON). Each element is:
  {{"id": "<finding id>", "explanation": "<short plain-English why this matters>"}}

Rules:
- Include every finding id from the input exactly once. Do not invent ids.
- Order by severity, most severe first (you may choose order among equals).
- explanation may rephrase the finding; do not add problems, numbers, or DNS records
  that are not in the findings. Put DNS record text in backticks only when copying
  from a finding's fix or evidence.

Findings (JSON):
{findings}
"""


class LLMExplainer:
    """`complete` is any callable prompt -> text, so it is trivial to fake in tests.

    Returns the raw model text (expected to be a JSON plan). Parsing, grounding,
    and deterministic rendering happen in the graph via parse_model_plan /
    verify_plan / render_plan.
    """

    def __init__(self, complete: Callable[[str], str]):
        self._complete = complete

    def explain(self, findings: list[Finding]) -> str:
        payload = json.dumps([f.to_dict() for f in findings], indent=2)
        return self._complete(PROMPT.format(findings=payload))


def anthropic_completer(model: str | None = None, max_tokens: int = 1200) -> Callable[[str], str]:
    """Adapter for the Anthropic SDK. Needs ANTHROPIC_API_KEY and a model name
    (argument or SETUP_DOCTOR_MODEL). NOT exercised by the test suite, which
    uses fakes -- run it once with your own key before relying on it."""
    import anthropic  # optional dependency

    model = model or os.environ.get("SETUP_DOCTOR_MODEL")
    if not model:
        raise RuntimeError("Set SETUP_DOCTOR_MODEL (or pass model=) to the model id you want to use.")
    client = anthropic.Anthropic()

    def complete(prompt: str) -> str:
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    return complete


def parse_model_plan(text: str) -> tuple[list[dict[str, str]] | None, list[str]]:
    """Parse model output into a plan. Returns (items, violations).

    items is None when the text is not a usable plan; violations is non-empty then.
    """
    s = _FENCE_RE.sub("", text.strip()).strip()
    if not s:
        return None, ["empty explanation"]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None, ["malformed JSON"]
    if not isinstance(data, list):
        return None, ["malformed JSON: expected a list"]
    items: list[dict[str, str]] = []
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            return None, [f"malformed JSON: item {i} is not an object"]
        if "id" not in row or "explanation" not in row:
            return None, [f"malformed JSON: item {i} missing id or explanation"]
        if not isinstance(row["id"], str) or not isinstance(row["explanation"], str):
            return None, [f"malformed JSON: item {i} id/explanation must be strings"]
        items.append({"id": row["id"], "explanation": row["explanation"]})
    return items, []


def _allowed_numbers(findings: list[Finding]) -> set[int]:
    """Integers that appear in finding titles or evidence (ground truth only)."""
    allowed: set[int] = set()
    for f in findings:
        for s in (f.title, *f.evidence.values()):
            for m in _NUM_RE.findall(s):
                allowed.add(int(m))
    return allowed


def _ground_dns_and_numbers(text: str, findings: list[Finding]) -> list[str]:
    """DNS-record and numeric claim checks against finding fix/evidence/title."""
    violations: list[str] = []
    allowed = " ".join(
        [f.fix for f in findings] + [v for f in findings for v in f.evidence.values()]
    ).lower()
    for code in _CODE_RE.findall(text):
        if _RECORD_RE.search(code) and code.lower() not in allowed:
            violations.append(f"record not grounded in findings: {code}")
    allowed_nums = _allowed_numbers(findings)
    for pat in _NUMERIC_CLAIM_RES:
        for m in pat.finditer(text):
            n = int(m.group(1))
            if n not in allowed_nums:
                violations.append(f"numeric claim not grounded: {m.group(0)}")
    return violations


def verify_plan(items: list[dict[str, str]], findings: list[Finding]) -> list[str]:
    """Ground a parsed model plan. Empty list means grounded.

    1. Returned ids must equal the finding id set (no extras, no omissions, no dupes).
    2. DNS records and allow-listed numeric claims in explanation strings must
       appear in finding fix/evidence (DNS) or title/evidence (numbers).
    """
    ids = {f.id for f in findings}
    returned = [it["id"] for it in items]
    returned_set = set(returned)
    violations: list[str] = []
    if len(returned) != len(returned_set):
        violations.append("duplicate finding ids in model output")
    violations += [f"unknown finding id [{c}]" for c in sorted(returned_set - ids)]
    for missing in sorted(ids - returned_set):
        violations.append(f"missing finding id [{missing}]")
    corpus = "\n".join(it["explanation"] for it in items)
    violations += _ground_dns_and_numbers(corpus, findings)
    return violations


def render_plan(items: list[dict[str, str]], findings: list[Finding]) -> str:
    """Deterministic user-facing text: model supplies explanation only; title/fix from findings."""
    by_id = {f.id: f for f in findings}
    lines = ["Fix in this order:", ""]
    for i, item in enumerate(items, 1):
        f = by_id[item["id"]]
        lines += [
            f"{i}. **[{f.id}]** ({f.severity}) {f.title}",
            f"   - Why it matters: {item['explanation'].strip()}",
            f"   - Fix: {f.fix}",
            "",
        ]
    return "\n".join(lines).rstrip()


def verify_grounding(text: str, findings: list[Finding]) -> list[str]:
    """Return violations for delivered (rendered) prose; empty means grounded.

    Used for template output and post-render self-checks. Model drafts are
    checked with parse_model_plan + verify_plan before render.
    """
    ids = {f.id for f in findings}
    cited = set(_ID_RE.findall(text))
    violations = [f"unknown finding id [{c}]" for c in sorted(cited - ids)]
    violations += [
        f"missing {f.severity} finding [{f.id}]"
        for f in findings
        if f.severity in ("critical", "high") and f.id not in cited
    ]
    violations += _ground_dns_and_numbers(text, findings)
    return violations
