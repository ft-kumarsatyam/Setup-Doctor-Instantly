"""Platform layer: registry, selectors, result contract, auth, bulk, reputation, advisory."""
from __future__ import annotations

import pytest
from evals.detection.fixtures import ADVISORY_CASES, CASES, make
from fastapi.testclient import TestClient

from setup_doctor.checks import check_bimi, check_mta_sts, check_tls_rpt, run_checks
from setup_doctor.checks.registry import ALL_DNS_PACKS, get_default_registry
from setup_doctor.checks.selectors import resolve_selectors
from setup_doctor.core.result import SCHEMA_VERSION, DiagnosisResult
from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.integrations.reputation import NullReputationProvider, StaticListProvider, check_reputation
from setup_doctor.surfaces.api import create_app
from setup_doctor.surfaces.auth import ApiKeyAuth, load_api_keys
from setup_doctor.surfaces.bulk import parse_domain_list, run_bulk


def test_diagnosis_result_schema_keys():
    case = next(c for c in CASES if c["name"] == "clean")
    from setup_doctor import diagnose_result

    result = diagnose_result(case["domain"], FixtureResolver(case["records"]))
    d = result.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["findings"] == []
    assert d["signals"] is None
    assert isinstance(result, DiagnosisResult)


def test_registry_lists_core_and_advisory_specs():
    specs = {s.id: s.pack for s in get_default_registry().specs()}
    assert specs["spf"] == "dns_auth"
    assert specs["bimi"] == "dns_auth_advisory"


def test_default_run_checks_skips_advisory():
    case = next(c for c in CASES if c["name"] == "clean")
    got = {f.id for f in run_checks(case["domain"], FixtureResolver(case["records"]))}
    assert got == set()


def test_advisory_packs_match_fixtures():
    for c in ADVISORY_CASES:
        got = sorted(
            f.id
            for f in run_checks(
                c["domain"], FixtureResolver(c["records"]), packs=ALL_DNS_PACKS,
            )
        )
        assert got == c["expected"], c["name"]


def test_esp_selector_packs_prepend():
    sels = resolve_selectors(packs=("google",), defaults=("default",))
    assert sels[0] == "google"
    assert "default" in sels
    with pytest.raises(ValueError):
        resolve_selectors(packs=("nope",), defaults=())


def test_api_key_auth_optional_and_required():
    open_auth = ApiKeyAuth({})
    assert open_auth.authenticate(None) is None
    gated = ApiKeyAuth({"secret": "acme"})
    with pytest.raises(PermissionError):
        gated.authenticate(None)
    tenant = gated.authenticate("secret")
    assert tenant is not None and tenant.tenant_id == "acme"
    # Full env-style paste `key:tenant` should also authenticate.
    assert gated.authenticate("secret:acme").tenant_id == "acme"
    assert load_api_keys("a:t1,b") == {"a": "t1", "b": "default"}


def test_api_rejects_bad_key_when_configured():
    mess = next(c for c in CASES if c["name"] == "worst_case_combo")
    app = create_app(
        resolver_factory=lambda: FixtureResolver(mess["records"]),
        auth=ApiKeyAuth({"good": "t1"}),
    )
    client = TestClient(app)
    assert client.post("/diagnose", json={"domain": mess["domain"]}).status_code == 401
    r = client.post(
        "/diagnose",
        json={"domain": mess["domain"]},
        headers={"X-API-Key": "good"},
    )
    assert r.status_code == 200
    assert r.json()["schema_version"] == SCHEMA_VERSION
    assert r.headers.get("X-Tenant") == "t1"


def test_bulk_parse_and_run():
    text = "domain\nclean.test\nmess.test\n"
    domains = parse_domain_list(text)
    assert domains == ["clean.test", "mess.test"]
    clean = next(c for c in CASES if c["name"] == "clean")
    mess = next(c for c in CASES if c["name"] == "worst_case_combo")
    # Combined fixture map for both domains
    records = {**clean["records"], **mess["records"]}
    report = run_bulk(
        domains,
        FixtureResolver(records),
        dkim_selectors=("google",),
    )
    assert report.to_dict()["ok"] == 2


def test_reputation_null_and_static():
    n = NullReputationProvider().check_domain("x.test")
    assert n.listed is None
    s = StaticListProvider(frozenset({"bad.test"})).check_domain("bad.test")
    assert s.listed is True
    rows = check_reputation("x.test", NullReputationProvider())
    assert rows[0]["listed"] is None


def test_bimi_mta_sts_tls_helpers():
    domain = "x.test"
    empty = FixtureResolver({})
    assert check_bimi(domain, empty)[0].id == "BIMI_MISSING"
    assert check_mta_sts(domain, empty)[0].id == "MTA_STS_MISSING"
    assert check_tls_rpt(domain, empty)[0].id == "TLS_RPT_MISSING"
    recs = make(
        domain,
        extra={
            f"default._bimi.{domain}": {"TXT": ["v=BIMI1; l=https://x.test/l.svg"]},
            f"_mta-sts.{domain}": {"TXT": ["v=STSv1; id=1"]},
            f"_smtp._tls.{domain}": {"TXT": ["v=TLSRPTv1; rua=mailto:t@x.test"]},
        },
    )
    r = FixtureResolver(recs)
    assert check_bimi(domain, r) == []
    assert check_mta_sts(domain, r) == []
    assert check_tls_rpt(domain, r) == []


def test_mcp_tool_diagnose_offline(monkeypatch):
    from setup_doctor.surfaces import mcp_server

    case = next(c for c in CASES if c["name"] == "spf_missing")

    class FakeLive:
        def domain_exists(self, domain):
            return True

        def txt(self, name):
            return FixtureResolver(case["records"]).txt(name)

        def mx(self, name):
            return FixtureResolver(case["records"]).mx(name)

        def a(self, name):
            return FixtureResolver(case["records"]).a(name)

    monkeypatch.setattr(mcp_server, "LiveResolver", FakeLive)
    out = mcp_server.tool_diagnose({"domain": case["domain"]})
    assert out["schema_version"] == SCHEMA_VERSION
    assert {f["id"] for f in out["findings"]} == set(case["expected"])


def test_schema_endpoint():
    app = create_app(resolver_factory=lambda: FixtureResolver({}))
    r = TestClient(app).get("/schema")
    assert r.status_code == 200
    assert r.json()["schema_version"] == SCHEMA_VERSION
