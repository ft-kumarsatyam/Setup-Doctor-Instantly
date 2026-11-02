"""Explanation layer plus the grounding guardrail.

The LLM never decides what is wrong. It only rewrites verified Findings into
a prioritized plan. verify_grounding() then checks the text against the
Findings and rejects anything invented, so a hallucination can never reach the
user: the graph falls back to the deterministic TemplateExplainer instead.
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
Rewrite the findings below as a short, prioritized plan in plain English.

Rules:
- Use ONLY the findings provided. Do not add problems, numbers, or DNS records that are not in them.
- Refer to each finding by its id in square brackets, like [SPF_MISSING].
- Every critical and high severity finding must appear.
- Put any DNS record text in backticks, and only copy record text that appears in a finding's fix or evidence.
- Order by severity, most severe first.

Findings (JSON):
{findings}
"""


class LLMExplainer:
    """`complete` is any callable prompt -> text, so it is trivial to fake in tests."""

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


def verify_grounding(text: str, findings: list[Finding]) -> list[str]:
    """Return a list of violations; empty means the text is grounded.

    1. Every [ID] cited must be a real finding.
    2. Every critical/high finding must be cited.
    3. Every backticked DNS record (v=spf1 / v=DMARC1 / v=DKIM1) must appear
       in some finding's fix or evidence.
    """
    ids = {f.id for f in findings}
    cited = set(_ID_RE.findall(text))
    violations = [f"unknown finding id [{c}]" for c in sorted(cited - ids)]
    violations += [
        f"missing {f.severity} finding [{f.id}]"
        for f in findings
        if f.severity in ("critical", "high") and f.id not in cited
    ]
    allowed = " ".join(
        [f.fix for f in findings] + [v for f in findings for v in f.evidence.values()]
    ).lower()
    for code in _CODE_RE.findall(text):
        if _RECORD_RE.search(code) and code.lower() not in allowed:
            violations.append(f"record not grounded in findings: {code}")
    return violations
