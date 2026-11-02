import pytest
from evals.fixtures import CASES, DKIM_P_1024, DKIM_P_2048

from setup_doctor import FixtureResolver, run_checks
from setup_doctor.checks import dkim_rsa_key_bits
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


def test_dkim_rsa_key_bits_from_p_value():
    assert dkim_rsa_key_bits(DKIM_P_1024) == 1024
    assert dkim_rsa_key_bits(DKIM_P_2048) == 2048
    assert dkim_rsa_key_bits("not-valid-base64!!!") is None
    assert dkim_rsa_key_bits("YQ==") is None  # decodes but is not SPKI


def test_dkim_weak_key_finding_is_actionable():
    c = next(c for c in CASES if c["name"] == "dkim_weak_1024")
    f = next(x for x in run_checks(c["domain"], FixtureResolver(c["records"])) if x.id == "DKIM_WEAK_KEY")
    assert f.evidence["bits"] == "1024"
    assert "2048" in f.fix


def test_dmarc_sp_none_and_strict_alignment_findings():
    sp = next(c for c in CASES if c["name"] == "dmarc_sp_none_under_reject")
    ids = [f.id for f in run_checks(sp["domain"], FixtureResolver(sp["records"]))]
    assert ids == ["DMARC_SP_NONE"]
    st = next(c for c in CASES if c["name"] == "dmarc_strict_alignment")
    f = run_checks(st["domain"], FixtureResolver(st["records"]))[0]
    assert f.id == "DMARC_STRICT_ALIGNMENT"
    assert "adkim=s" in f.title and "aspf=s" in f.title
