"""Compatibility shim — guardrail fakes live in evals.guardrails.fakes."""
from evals.guardrails.fakes import *  # noqa: F403
from evals.guardrails.fakes import BEHAVIORS, PLANTED_MARKERS, faithful  # noqa: F401
