import json

import pytest

from evals.fakes import BEHAVIORS, PLANTED_MARKERS
from evals.fixtures import CASES
from setup_doctor import FixtureResolver, LLMExplainer, TemplateExplainer, diagnose, run_checks, verify_grounding
from setup_doctor.explain import PROMPT

WORST = next(c for c in CASES if c["name"] == "worst_case_combo")
CLEAN = next(c for c in CASES if c["name"] == "clean")


def findings_for(case):
    return run_checks(case["domain"], FixtureResolver(case["records"]))


def test_template_explainer_always_passes_its_own_verifier():
    for c in CASES:
        fs = findings_for(c)
        assert verify_grounding(TemplateExplainer().explain(fs), fs) == []


def test_verifier_rejects_unknown_finding_id():
    fs = findings_for(WORST)
    text = TemplateExplainer().explain(fs) + "\n[MADE_UP_ID] nonsense"
    assert any("unknown finding id" in v for v in verify_grounding(text, fs))


def test_verifier_rejects_ungrounded_record_but_accepts_record_from_fix():
    fs = findings_for(next(c for c in CASES if c["name"] == "spf_missing"))
    ok = TemplateExplainer().explain(fs)  # contains the suggested records from the fix text
    assert verify_grounding(ok, fs) == []
    bad = ok + "\nUse `v=spf1 include:evil.test -all`"
    assert any("not grounded" in v for v in verify_grounding(bad, fs))


def test_verifier_requires_every_severe_finding():
    fs = findings_for(WORST)
    severe = [f for f in fs if f.severity in ("critical", "high")]
    assert severe
    text = "\n".join(f"[{f.id}] x" for f in fs if f is not severe[0])
    assert any(severe[0].id in v for v in verify_grounding(text, fs))


@pytest.mark.parametrize("name", ["hallucinated_finding", "hallucinated_record", "raises", "empty"])
def test_graph_falls_back_and_never_delivers_planted_hallucination(name):
    state = diagnose(WORST["domain"], FixtureResolver(WORST["records"]), LLMExplainer(BEHAVIORS[name]))
    assert state["used_fallback"] is True
    assert PLANTED_MARKERS.get(name, "\0") not in state["explanation"]
    assert verify_grounding(state["explanation"], state["findings"]) == []
    assert "deterministic template" in state["report"]


def test_graph_accepts_faithful_model_output():
    state = diagnose(WORST["domain"], FixtureResolver(WORST["records"]), LLMExplainer(BEHAVIORS["faithful"]))
    assert state["used_fallback"] is False
    assert "model draft, verified" in state["report"]


def test_report_does_not_claim_a_model_when_only_the_template_ran():
    state = diagnose(WORST["domain"], FixtureResolver(WORST["records"]))  # default TemplateExplainer
    assert "no model used" in state["report"] and "model draft" not in state["report"]
    clean = diagnose(CLEAN["domain"], FixtureResolver(CLEAN["records"]), LLMExplainer(BEHAVIORS["faithful"]))
    assert "no model used" in clean["report"]  # model never called on a clean domain


def test_model_is_not_called_when_there_is_nothing_to_explain():
    calls = []

    def spy(prompt):
        calls.append(prompt)
        return "x"

    state = diagnose(CLEAN["domain"], FixtureResolver(CLEAN["records"]), LLMExplainer(spy))
    assert calls == [] and state["findings"] == []


def test_prompt_contains_only_findings_not_raw_dns():
    seen = []

    def spy(prompt):
        seen.append(prompt)
        return BEHAVIORS["faithful"](prompt)

    diagnose(WORST["domain"], FixtureResolver(WORST["records"]), LLMExplainer(spy))
    payload = json.loads(seen[0].split("Findings (JSON):\n", 1)[1])
    assert {p["id"] for p in payload} == {f.id for f in findings_for(WORST)}


def test_numeric_misstatement_is_rejected():
    """Lookup-count lies must fail grounding and never reach the user."""
    c = next(c for c in CASES if c["name"] == "spf_11_lookups")
    state = diagnose(c["domain"], FixtureResolver(c["records"]), LLMExplainer(BEHAVIORS["misstates_numbers"]))
    assert state["used_fallback"] is True
    assert "needs 14 DNS lookups" not in state["explanation"]
    assert verify_grounding(state["explanation"], state["findings"]) == []


def test_faithful_and_template_pass_numeric_grounding_for_all_fixtures():
    for c in CASES:
        fs = findings_for(c)
        if not fs:
            continue
        assert verify_grounding(TemplateExplainer().explain(fs), fs) == []
        draft = BEHAVIORS["faithful"](
            PROMPT.format(findings=json.dumps([f.to_dict() for f in fs], indent=2))
        )
        assert verify_grounding(draft, fs) == []
