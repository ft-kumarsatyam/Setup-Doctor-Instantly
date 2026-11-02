import pytest

from evals.fixtures import CASES
from setup_doctor import FixtureResolver, run_checks
from setup_doctor.models import SEVERITY_ORDER


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_labeled_fixture(c):
    got = sorted(f.id for f in run_checks(c["domain"], FixtureResolver(c["records"])))
    assert got == c["expected"], c["note"]


def test_findings_are_sorted_most_severe_first():
    c = next(c for c in CASES if c["name"] == "worst_case_combo")
    sev = [SEVERITY_ORDER[f.severity] for f in run_checks(c["domain"], FixtureResolver(c["records"]))]
    assert sev == sorted(sev)


def test_custom_dkim_selector_removes_false_positive():
    r = FixtureResolver({
        "d.test": {"TXT": ["v=spf1 ~all"], "MX": ["mx.d.test"]},
        "_dmarc.d.test": {"TXT": ["v=DMARC1; p=quarantine; rua=mailto:r@d.test"]},
        "weird._domainkey.d.test": {"TXT": ["v=DKIM1; p=abc"]},
    })
    assert [f.id for f in run_checks("d.test", r)] == ["DKIM_NOT_FOUND"]
    assert run_checks("d.test", r, dkim_selectors=("weird",)) == []


def test_domain_input_is_normalised():
    c = next(c for c in CASES if c["name"] == "clean")
    r = FixtureResolver(c["records"])
    assert run_checks("  CLEAN.test. ", r) == []


def test_every_finding_has_actionable_fields():
    c = next(c for c in CASES if c["name"] == "worst_case_combo")
    for f in run_checks(c["domain"], FixtureResolver(c["records"])):
        assert f.title and f.why and f.fix
        assert f.severity in SEVERITY_ORDER


def test_dkim_finding_states_its_own_limitation():
    f = run_checks("ghost.test", FixtureResolver({}))
    dkim = next(x for x in f if x.id == "DKIM_NOT_FOUND")
    assert "false positive" in dkim.evidence["limitation"]
