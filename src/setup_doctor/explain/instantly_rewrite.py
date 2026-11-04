"""Optional LLM rewrite of Instantly signal tables for GTM engineers.

Never invent Instantly scores, verdicts, emails, or test ids. On any grounding
failure, fall back to the deterministic template markdown.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from setup_doctor.integrations.instantly.compare import (
    AccountComparison,
    render_comparison_markdown,
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_VERDICT_RE = re.compile(r"\b(aligned|mismatch|unknown)\b", re.I)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

INSTANTLY_PROMPT = """You rewrite Instantly warmup vs inbox-placement signals for GTM engineers.

Return ONLY a JSON array (no markdown fences). Each element:
  {{"email": "<exact email from input>", "summary": "<1-3 sentences>"}}

Rules:
- Include every email from the input exactly once. Do not invent emails.
- Quote verdict exactly as given (aligned | mismatch | unknown).
- Do not invent numeric scores, inbox %, spam %, health scores, or test ids.
- Numbers you mention must appear in that account's input fields.
- unknown means data is missing — never soften to healthy or fine.
- Do not invent DNS Findings; Instantly signals are not DNS checks.

Accounts (JSON):
{accounts}
"""


def _allowed_numbers(row: AccountComparison) -> set[str]:
    allowed: set[str] = set()
    for v in (row.warmup_score, row.health_score, row.inbox_percent, row.spam_percent):
        if v is not None:
            allowed.add(f"{v:g}")
            allowed.add(str(int(v)) if float(v).is_integer() else f"{v:g}")
    return allowed


def parse_instantly_rewrite(text: str) -> tuple[list[dict[str, str]] | None, list[str]]:
    s = _FENCE_RE.sub("", text.strip()).strip()
    if not s:
        return None, ["empty Instantly rewrite"]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None, ["malformed JSON Instantly rewrite"]
    if not isinstance(data, list):
        return None, ["Instantly rewrite must be a JSON list"]
    items: list[dict[str, str]] = []
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            return None, [f"Instantly rewrite item {i} is not an object"]
        email = row.get("email")
        summary = row.get("summary")
        if not isinstance(email, str) or not isinstance(summary, str):
            return None, [f"Instantly rewrite item {i} missing email/summary strings"]
        items.append({"email": email.strip().lower(), "summary": summary})
    return items, []


def verify_instantly_rewrite(
    items: list[dict[str, str]],
    comparisons: list[AccountComparison],
) -> list[str]:
    """Reject invented emails, verdicts, or numeric Instantly claims."""
    by_email = {c.email.strip().lower(): c for c in comparisons}
    expected = set(by_email)
    returned = [it["email"].strip().lower() for it in items]
    returned_set = set(returned)
    violations: list[str] = []
    if len(returned) != len(returned_set):
        violations.append("duplicate Instantly emails in model output")
    for extra in sorted(returned_set - expected):
        violations.append(f"unknown Instantly email [{extra}]")
    for missing in sorted(expected - returned_set):
        violations.append(f"missing Instantly email [{missing}]")

    for it in items:
        email = it["email"].strip().lower()
        row = by_email.get(email)
        if row is None:
            continue
        summary = it["summary"]
        for em in _EMAIL_RE.findall(summary):
            if em.lower() != email and em.lower() not in expected:
                violations.append(f"invented Instantly email in summary: {em}")
        for m in _VERDICT_RE.finditer(summary):
            if m.group(1).lower() != row.verdict:
                violations.append(
                    f"invented Instantly verdict for {email}: "
                    f"{m.group(1)} (engine={row.verdict})"
                )
        allowed = _allowed_numbers(row)
        for num in _NUM_RE.findall(summary):
            if num in allowed:
                continue
            try:
                f = float(num)
            except ValueError:
                violations.append(f"numeric Instantly claim not grounded: {num}")
                continue
            matched = False
            for a in allowed:
                try:
                    if float(a) == f:
                        matched = True
                        break
                except ValueError:
                    continue
            if not matched:
                violations.append(f"numeric Instantly claim not grounded: {num}")
        # Reject "healthy" softening of unknown
        if row.verdict == "unknown" and re.search(r"\bhealthy\b", summary, re.I):
            violations.append(f"softened unknown Instantly verdict to healthy for {email}")
    return violations


def render_instantly_rewrite(
    items: list[dict[str, str]],
    comparisons: list[AccountComparison],
) -> str:
    by_email = {c.email.strip().lower(): c for c in comparisons}
    lines = [
        "# Instantly warmup vs inbox placement (GTM summary)",
        "",
        "Model rewrite of Instantly signals. Engine verdicts remain authoritative; "
        "**unknown** means data missing — never healthy.",
        "",
    ]
    for it in items:
        email = it["email"].strip().lower()
        row = by_email[email]
        lines += [
            f"### `{email}` — **{row.verdict}**",
            "",
            it["summary"].strip(),
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def rewrite_instantly_signals(
    comparisons: list[AccountComparison],
    complete: Callable[[str], str] | None,
) -> tuple[str, str, list[str]]:
    """Return (markdown, source, violations).

    source is model_verified | template_fallback | template.
    """
    if not comparisons:
        return render_comparison_markdown(comparisons), "template", []
    if complete is None:
        return render_comparison_markdown(comparisons), "template", []

    payload = json.dumps([c.to_dict() for c in comparisons], indent=2)
    try:
        draft = complete(INSTANTLY_PROMPT.format(accounts=payload))
    except Exception as exc:
        return (
            render_comparison_markdown(comparisons),
            "template_fallback",
            [f"instantly explainer raised {type(exc).__name__}"],
        )

    items, parse_violations = parse_instantly_rewrite(draft)
    if parse_violations or items is None:
        return (
            render_comparison_markdown(comparisons),
            "template_fallback",
            parse_violations,
        )
    violations = verify_instantly_rewrite(items, comparisons)
    if violations:
        return (
            render_comparison_markdown(comparisons),
            "template_fallback",
            violations,
        )
    return render_instantly_rewrite(items, comparisons), "model_verified", []
