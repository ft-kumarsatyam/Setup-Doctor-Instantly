"""API/schema contract checks for DiagnosisResult stability."""
from __future__ import annotations

from evals.fixtures import CASES
from setup_doctor import FixtureResolver, diagnose_result
from setup_doctor.result import SCHEMA_VERSION

REQUIRED_KEYS = {
    "schema_version",
    "domain",
    "findings",
    "explanation",
    "explanation_source",
    "report",
    "plan_items",
    "violations",
    "used_fallback",
    "signals",
}


def eval_schema_contract() -> dict:
    case = next(c for c in CASES if c["name"] == "worst_case_combo")
    result = diagnose_result(
        case["domain"], FixtureResolver(case["records"]),
    )
    payload = result.to_dict()
    missing = sorted(REQUIRED_KEYS - set(payload))
    extra_ok = True
    finding_ids = {f["id"] for f in payload["findings"]}
    expected = set(case["expected"])
    return {
        "schema_version": payload.get("schema_version"),
        "expected_schema_version": SCHEMA_VERSION,
        "missing_keys": missing,
        "finding_ids_match": finding_ids == expected,
        "ok": (
            not missing
            and payload.get("schema_version") == SCHEMA_VERSION
            and finding_ids == expected
            and extra_ok
        ),
    }
