"""Retrieve grounded rewrite examples for the current findings.

Examples are tone only. A stored plan is returned only when every id in it is
already in the query, so an example cannot teach a finding the checks did not
produce. No embeddings: overlap on finding ids is exact.
"""
from __future__ import annotations

from setup_doctor.explain.rag_index import PLANS

Plan = tuple[tuple[str, str], ...]
_MAX_EXAMPLES = 2


def retrieve_examples(
    finding_ids: list[str] | tuple[str, ...] | set[str],
    *,
    plans: tuple[Plan, ...] = PLANS,
    limit: int = _MAX_EXAMPLES,
) -> list[Plan]:
    """Return up to `limit` plans whose ids are a subset of `finding_ids`.

    Larger overlap ranks first. Identical id sets are already one plan.
    """
    query = set(finding_ids)
    if not query or limit <= 0:
        return []
    ranked: list[tuple[int, tuple[str, ...], Plan]] = []
    for plan in plans:
        plan_ids = {finding_id for finding_id, _ in plan}
        if not set(plan_ids).issubset(query):
            continue
        cover = len(plan_ids)
        ranked.append((cover, tuple(sorted(plan_ids)), plan))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [plan for _cover, _ids, plan in ranked[:limit]]


def format_examples(plans: list[Plan]) -> str:
    """Prompt block placed above Findings JSON. Empty when there is nothing to show."""
    if not plans:
        return ""
    lines = [
        "Examples (tone only). Do not copy numbers, DNS records, or finding ids "
        "that are not in the findings below.",
        "",
    ]
    for number, plan in enumerate(plans, 1):
        lines.append(f"Example {number}:")
        for finding_id, explanation in plan:
            lines.append(f"- {finding_id}: {explanation}")
        lines.append("")
    return "\n".join(lines)
