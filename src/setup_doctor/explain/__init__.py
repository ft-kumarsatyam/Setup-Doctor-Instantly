"""Explanation + grounding. LLM may rewrite Findings; never invent them."""
from .explainer import (
    PROMPT,
    Explainer,
    LLMExplainer,
    TemplateExplainer,
    anthropic_completer,
    parse_model_plan,
    render_plan,
    render_prompt,
    verify_grounding,
    verify_plan,
)
from .fix_packets import (
    PROVIDERS as FIX_PACKET_PROVIDERS,
)
from .fix_packets import (
    FixPacket,
    build_fix_packet,
    playbook_snippet,
    verify_fix_packet,
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
    "FIX_PACKET_PROVIDERS",
    "FixPacket",
    "LLMExplainer",
    "TemplateExplainer",
    "anthropic_completer",
    "build_fix_packet",
    "parse_model_plan",
    "parse_instantly_rewrite",
    "playbook_snippet",
    "render_plan",
    "render_prompt",
    "rewrite_instantly_signals",
    "verify_fix_packet",
    "verify_grounding",
    "verify_instantly_rewrite",
    "verify_plan",
    "render_markdown",
]
