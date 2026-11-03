"""Explanation + grounding. LLM may rewrite Findings; never invent them."""
from .explainer import (
    PROMPT,
    Explainer,
    LLMExplainer,
    TemplateExplainer,
    anthropic_completer,
    parse_model_plan,
    render_plan,
    verify_grounding,
    verify_plan,
)
from .report import render_markdown

__all__ = [
    "PROMPT",
    "Explainer",
    "LLMExplainer",
    "TemplateExplainer",
    "anthropic_completer",
    "parse_model_plan",
    "render_plan",
    "verify_grounding",
    "verify_plan",
    "render_markdown",
]
