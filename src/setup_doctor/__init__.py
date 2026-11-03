"""Setup Doctor — DNS diagnosis for cold-email auth.

Public API stays stable. Internals live under layered packages:
  core / dns / checks / explain / pipeline / integrations / surfaces
"""
from setup_doctor.checks import run_checks
from setup_doctor.core import SCHEMA_VERSION, DiagnosisResult, DiagnosisSignals, Finding
from setup_doctor.dns import FixtureResolver, LiveResolver, ResolverError
from setup_doctor.explain import LLMExplainer, TemplateExplainer, verify_grounding
from setup_doctor.pipeline import build_graph, diagnose, diagnose_result

__all__ = [
    "ResolverError",
    "Finding",
    "DiagnosisResult",
    "DiagnosisSignals",
    "SCHEMA_VERSION",
    "run_checks",
    "diagnose",
    "diagnose_result",
    "build_graph",
    "verify_grounding",
    "TemplateExplainer",
    "LLMExplainer",
    "FixtureResolver",
    "LiveResolver",
]
