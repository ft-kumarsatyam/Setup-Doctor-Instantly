"""Compatibility shim — fixtures live in evals.detection.fixtures."""
from evals.detection.fixtures import (  # noqa: F401
    ADVISORY_CASES,
    CASES,
    DKIM_P_1024,
    DKIM_P_2048,
    GOOD_DKIM,
    GOOD_DMARC,
    GOOGLE_SPF,
    WEAK_DKIM,
    advisory_case,
    case,
    make,
)

__all__ = [
    "ADVISORY_CASES",
    "CASES",
    "DKIM_P_1024",
    "DKIM_P_2048",
    "GOOD_DKIM",
    "GOOD_DMARC",
    "GOOGLE_SPF",
    "WEAK_DKIM",
    "advisory_case",
    "case",
    "make",
]
