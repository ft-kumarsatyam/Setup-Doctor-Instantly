"""LangGraph workflow.

    check -> explain -> verify --(grounded)--> render
                          \\--(violations)--> fallback -> render

check:    deterministic DNS checks produce Findings (ground truth)
explain:  an Explainer (LLM or template) drafts the plan; errors are caught
verify:   verify_grounding() compares the draft against the Findings
fallback: if the draft was empty, errored, or ungrounded, use the template
render:   assemble the final report and record which path was taken
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .checks import DEFAULT_DKIM_SELECTORS, run_checks
from .explain import Explainer, TemplateExplainer, verify_grounding
from .models import Finding
from .report import render_markdown
from .resolver import Resolver


class State(TypedDict, total=False):
    domain: str
    findings: list[Finding]
    draft: str
    explanation: str
    violations: list[str]
    used_fallback: bool
    report: str


def build_graph(resolver: Resolver, explainer: Explainer,
                dkim_selectors: tuple[str, ...] = DEFAULT_DKIM_SELECTORS):
    template = TemplateExplainer()

    def check(state: State) -> State:
        return {"findings": run_checks(state["domain"], resolver, dkim_selectors)}

    def explain(state: State) -> State:
        findings = state["findings"]
        if not findings:  # nothing to explain; skip the model call entirely
            return {"draft": template.explain(findings)}
        try:
            return {"draft": explainer.explain(findings)}
        except Exception as exc:  # model/network failure must not break the run
            return {"draft": "", "violations": [f"explainer raised {type(exc).__name__}"]}

    def verify(state: State) -> State:
        draft = state.get("draft", "")
        if not draft.strip():
            return {"violations": state.get("violations") or ["empty explanation"]}
        return {"violations": verify_grounding(draft, state["findings"])}

    def route(state: State) -> str:
        return "fallback" if state.get("violations") else "render"

    def fallback(state: State) -> State:
        return {"draft": template.explain(state["findings"]), "used_fallback": True}

    uses_model = not isinstance(explainer, TemplateExplainer)

    def render(state: State) -> State:
        used_fallback = state.get("used_fallback", False)
        # With no findings the model is never called, so the template wrote the text.
        model_wrote_it = uses_model and bool(state["findings"]) and not used_fallback
        source = "template_fallback" if used_fallback else "model_verified" if model_wrote_it else "template"
        return {
            "explanation": state["draft"],
            "used_fallback": used_fallback,
            "report": render_markdown(
                state["domain"], state["findings"], state["draft"],
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
    app = build_graph(resolver, explainer or TemplateExplainer(), dkim_selectors)
    return app.invoke({"domain": domain.strip().lower().rstrip(".")})
