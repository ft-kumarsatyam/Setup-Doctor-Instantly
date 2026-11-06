import json

import pytest
from evals.fakes import BEHAVIORS, PLANTED_MARKERS
from evals.fixtures import CASES

from setup_doctor import FixtureResolver, LLMExplainer, TemplateExplainer, diagnose, run_checks, verify_grounding
from setup_doctor.explain import parse_model_plan, render_plan, render_prompt, verify_plan
from setup_doctor.explain.retrieve import retrieve_examples

WORST = next(c for c in CASES if c["name"] == "worst_case_combo")
CLEAN = next(c for c in CASES if c["name"] == "clean")


def findings_for(case):
    return run_checks(case["domain"], FixtureResolver(case["records"]))


def _faithful_plan(fs):
    return BEHAVIORS["faithful"](
        render_prompt(json.dumps([f.to_dict() for f in fs], indent=2))
    )


def test_template_explainer_always_passes_its_own_verifier():
    for c in CASES:
        fs = findings_for(c)
        assert verify_grounding(TemplateExplainer().explain(fs), fs) == []


def test_verifier_rejects_unknown_finding_id():
    fs = findings_for(WORST)
    items = [{"id": f.id, "explanation": f.why} for f in fs]
    items.append({"id": "MADE_UP_ID", "explanation": "nonsense"})
    assert any("unknown finding id" in v for v in verify_plan(items, fs))


def test_verifier_rejects_ungrounded_record_but_accepts_record_from_fix():
    fs = findings_for(next(c for c in CASES if c["name"] == "spf_missing"))
    ok = [{"id": f.id, "explanation": f.why} for f in fs]
    assert verify_plan(ok, fs) == []
    bad = [{"id": f.id, "explanation": f.why} for f in fs]
    bad[0]["explanation"] += " Use `v=spf1 include:evil.test -all`"
    assert any("not grounded" in v for v in verify_plan(bad, fs))
    # Rendered template prose still passes the delivered-text verifier.
    assert verify_grounding(TemplateExplainer().explain(fs), fs) == []


def test_verifier_requires_every_finding_id():
    fs = findings_for(WORST)
    assert len(fs) > 1
    items = [{"id": f.id, "explanation": f.why} for f in fs[1:]]
    assert any(fs[0].id in v for v in verify_plan(items, fs))


def test_malformed_json_and_duplicate_ids_are_rejected():
    fs = findings_for(WORST)
    items, errs = parse_model_plan('{"id": "x"')
    assert items is None and any("malformed" in e for e in errs)
    dup = [{"id": fs[0].id, "explanation": "a"}, {"id": fs[0].id, "explanation": "b"}]
    # pad with the rest so only the duplicate is wrong
    dup += [{"id": f.id, "explanation": f.why} for f in fs[1:]]
    assert any("duplicate" in v for v in verify_plan(dup, fs))


@pytest.mark.parametrize(
    "name",
    ["hallucinated_finding", "hallucinated_record", "malformed_json", "duplicate_ids", "raises", "empty"],
)
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
    # Model prose cannot alter the fix: rendered text uses finding.fix.
    for f in state["findings"]:
        assert f.fix in state["explanation"]


def test_render_plan_uses_finding_title_and_fix_not_model_fix():
    fs = findings_for(WORST)[:1]
    items = [{"id": fs[0].id, "explanation": "model why only"}]
    text = render_plan(items, fs)
    assert "model why only" in text
    assert fs[0].title in text
    assert fs[0].fix in text
    assert "invented fix" not in text


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
    assert "JSON array" in seen[0]
    assert "Examples (tone only)" in seen[0].split("Findings (JSON):", 1)[0]
    assert "v=spf1" not in seen[0].split("Findings (JSON):", 1)[0].lower()


def test_retriever_keeps_only_subsets_and_prefers_the_larger_overlap():
    plans = (
        (("SPF_MISSING", "no spf"),),
        (("SPF_MISSING", "no spf"), ("MX_MISSING", "no mx")),
        (("MX_MISSING", "no mx"),),
    )
    only = retrieve_examples(["SPF_MISSING"], plans=plans)
    assert only == [(("SPF_MISSING", "no spf"),)]
    both = retrieve_examples(["SPF_MISSING", "MX_MISSING"], plans=plans)
    assert [tuple(i for i, _ in plan) for plan in both][0] == ("SPF_MISSING", "MX_MISSING")
    assert all({i for i, _ in plan} <= {"SPF_MISSING", "MX_MISSING"} for plan in both)
    assert len(both) <= 2


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
        items, errs = parse_model_plan(_faithful_plan(fs))
        assert errs == [] and items is not None
        assert verify_plan(items, fs) == []
