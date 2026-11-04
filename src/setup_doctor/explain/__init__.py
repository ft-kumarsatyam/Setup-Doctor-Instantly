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
from .instantly_rewrite import (
    parse_instantly_rewrite,
    rewrite_instantly_signals,
    verify_instantly_rewrite,
)
from .report import render_markdown

__all__ = [
    "PROMPT",
    "Explainer",
    "LLMExplainer",
    "TemplateExplainer",
    "anthropic_completer",
    "parse_model_plan",
    "parse_instantly_rewrite",
    "render_plan",
    "rewrite_instantly_signals",
    "verify_grounding",
    "verify_instantly_rewrite",
    "verify_plan",
    "render_markdown",
]
