import json
import logging

from evals.fakes import BEHAVIORS
from evals.fixtures import CASES

from setup_doctor import FixtureResolver, LLMExplainer, diagnose
from setup_doctor.observability import domain_hash, log_diagnosis

CLEAN = next(c for c in CASES if c["name"] == "clean")
MESS = next(c for c in CASES if c["name"] == "worst_case_combo")
SPF11 = next(c for c in CASES if c["name"] == "spf_11_lookups")


def _last_diagnosis_payload(caplog) -> dict:
    records = [r for r in caplog.records if r.name == "setup_doctor.diagnosis"]
    assert records, "expected a diagnosis log line"
    return json.loads(records[-1].getMessage())


def test_diagnose_emits_structured_log_without_plaintext_domain(caplog):
    caplog.set_level(logging.INFO, logger="setup_doctor.diagnosis")
    state = diagnose(MESS["domain"], FixtureResolver(MESS["records"]))
    payload = _last_diagnosis_payload(caplog)
    assert payload["event"] == "diagnosis"
    assert payload["explanation_source"] == "template"
    assert payload["findings_count"] == len(state["findings"])
    assert payload["duration_ms"] >= 0
    assert payload["rejection_reasons"] == []
    assert payload["cached"] is False
    assert payload["domain_hash"] == domain_hash(MESS["domain"])
    assert "domain" not in payload
    assert MESS["domain"] not in caplog.text


def test_model_fallback_logs_source_and_rejection_reasons(caplog):
    caplog.set_level(logging.INFO, logger="setup_doctor.diagnosis")
    diagnose(
        SPF11["domain"],
        FixtureResolver(SPF11["records"]),
        LLMExplainer(BEHAVIORS["misstates_numbers"]),
    )
    payload = _last_diagnosis_payload(caplog)
    assert payload["explanation_source"] == "template_fallback"
    assert payload["rejection_reasons"]
    assert SPF11["domain"] not in json.dumps(payload)


def test_faithful_model_logs_model_verified(caplog):
    caplog.set_level(logging.INFO, logger="setup_doctor.diagnosis")
    diagnose(
        MESS["domain"],
        FixtureResolver(MESS["records"]),
        LLMExplainer(BEHAVIORS["faithful"]),
    )
    payload = _last_diagnosis_payload(caplog)
    assert payload["explanation_source"] == "model_verified"
    assert payload["rejection_reasons"] == []


def test_log_domain_opt_in(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="setup_doctor.diagnosis")
    monkeypatch.setenv("SETUP_DOCTOR_LOG_DOMAIN", "1")
    log_diagnosis(
        explanation_source="template",
        findings_count=0,
        duration_ms=1,
        domain=CLEAN["domain"],
    )
    payload = _last_diagnosis_payload(caplog)
    assert payload["domain"] == CLEAN["domain"]
    assert payload["domain_hash"] == domain_hash(CLEAN["domain"])
