"""LangGraph workflow.

    check -> explain -> verify --(grounded)--> render
                          \\--(violations)--> fallback -> render

check:    deterministic DNS checks produce Findings (ground truth)
explain:  an Explainer (LLM or template) drafts the plan; errors are caught
verify:   model JSON is parsed and verify_plan()'d; template drafts are trusted
fallback: if the draft was empty, errored, or ungrounded, use the template
render:   assemble the final report (deterministic render_plan for verified JSON)
"""
from __future__ import annotations

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .checks import DEFAULT_DKIM_SELECTORS, run_checks
from .explain import (
    Explainer,
    TemplateExplainer,
    parse_model_plan,
    render_plan,
    verify_plan,
)
from .models import Finding
from .observability import log_diagnosis
from .report import render_markdown
from .resolver import Resolver


class State(TypedDict, total=False):
    domain: str
    findings: list[Finding]
    draft: str
    plan_items: list[dict[str, str]]
    explanation: str
    explanation_source: str
    violations: list[str]
    used_fallback: bool
    report: str


def build_graph(resolver: Resolver, explainer: Explainer,
                dkim_selectors: tuple[str, ...] = DEFAULT_DKIM_SELECTORS):
    template = TemplateExplainer()
    uses_model = not isinstance(explainer, TemplateExplainer)

    def check(state: State) -> State:
        return {"findings": run_checks(state["domain"], resolver, dkim_selectors)}

    def explain(state: State) -> State:
        findings = state["findings"]
        if not findings:  # nothing to explain; skip the model call entirely
            return {"draft": template.explain(findings), "plan_items": []}
        try:
            return {"draft": explainer.explain(findings), "plan_items": []}
        except Exception as exc:  # model/network failure must not break the run
            return {"draft": "", "plan_items": [], "violations": [f"explainer raised {type(exc).__name__}"]}

    def verify(state: State) -> State:
        draft = state.get("draft", "")
        findings = state["findings"]
        if not draft.strip():
            return {"violations": state.get("violations") or ["empty explanation"], "plan_items": []}
        # Template explainer (or no findings) already produced grounded prose.
        if not uses_model or not findings:
            return {"violations": [], "plan_items": []}
        items, parse_violations = parse_model_plan(draft)
        if parse_violations:
            return {"violations": parse_violations, "plan_items": []}
        assert items is not None
        violations = verify_plan(items, findings)
        if violations:
            return {"violations": violations, "plan_items": []}
        return {"violations": [], "plan_items": items}

    def route(state: State) -> str:
        return "fallback" if state.get("violations") else "render"

    def fallback(state: State) -> State:
        return {
            "draft": template.explain(state["findings"]),
            "plan_items": [],
            "used_fallback": True,
        }

    def render(state: State) -> State:
        used_fallback = state.get("used_fallback", False)
        plan_items = state.get("plan_items") or []
        if plan_items and not used_fallback:
            explanation = render_plan(plan_items, state["findings"])
        else:
            explanation = state["draft"]
        # With no findings the model is never called, so the template wrote the text.
        model_wrote_it = uses_model and bool(state["findings"]) and not used_fallback
        source = "template_fallback" if used_fallback else "model_verified" if model_wrote_it else "template"
        return {
            "explanation": explanation,
            "explanation_source": source,
            "used_fallback": used_fallback,
            "report": render_markdown(
                state["domain"], state["findings"], explanation,
                source, state.get("violations", []),
            ),
        }

    g = StateGraph(State)
    g.add_node("check", check)
    g.add_node("explain", explain)
    g.add_node("verify", verify)
    g.add_node("fallback", fallback)
    g.add_node("render", render)
    g.add_edge(START, "check")
    g.add_edge("check", "explain")
    g.add_edge("explain", "verify")
    g.add_conditional_edges("verify", route, {"fallback": "fallback", "render": "render"})
    g.add_edge("fallback", "render")
    g.add_edge("render", END)
    return g.compile()


def diagnose(domain: str, resolver: Resolver, explainer: Explainer | None = None,
             dkim_selectors: tuple[str, ...] = DEFAULT_DKIM_SELECTORS) -> State:
    domain = domain.strip().lower().rstrip(".")
    started = time.monotonic()
    app = build_graph(resolver, explainer or TemplateExplainer(), dkim_selectors)
    state = app.invoke({"domain": domain})
    duration_ms = int((time.monotonic() - started) * 1000)
    log_diagnosis(
        explanation_source=state.get("explanation_source", "unavailable"),
        findings_count=len(state.get("findings") or []),
        duration_ms=duration_ms,
        rejection_reasons=state.get("violations") or [],
        domain=domain,
        cached=False,
    )
    return state
