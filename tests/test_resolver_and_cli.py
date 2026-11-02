import json

import dns.resolver
import pytest
from evals.fixtures import CASES

from setup_doctor import LiveResolver, ResolverError
from setup_doctor.cli import main


class _Rdata:
    def __init__(self, *chunks):
        self.strings = chunks


def make_live(monkeypatch, behavior):
    r = LiveResolver()
    monkeypatch.setattr(r._resolver, "resolve", behavior)
    return r


def test_live_resolver_rejoins_split_txt_chunks(monkeypatch):
    r = make_live(monkeypatch, lambda name, rtype: [_Rdata(b"v=spf1 include:a.test ", b"-all")])
    assert r.txt("d.test") == ["v=spf1 include:a.test -all"]


def test_nxdomain_and_noanswer_mean_absent(monkeypatch):
    def nx(name, rtype):
        raise dns.resolver.NXDOMAIN()

    def no(name, rtype):
        raise dns.resolver.NoAnswer()

    assert make_live(monkeypatch, nx).txt("d.test") == []
    assert make_live(monkeypatch, no).mx("d.test") == []


def test_timeout_is_an_error_not_a_missing_record(monkeypatch):
    def boom(name, rtype):
        raise dns.resolver.LifetimeTimeout()

    r = make_live(monkeypatch, boom)
    with pytest.raises(ResolverError):
        r.txt("d.test")


def test_cli_offline_report_and_json(tmp_path, capsys):
    case = next(c for c in CASES if c["name"] == "worst_case_combo")
    path = tmp_path / "records.json"
    path.write_text(json.dumps(case["records"]))
    assert main([case["domain"], "--records", str(path)]) == 0
    out = capsys.readouterr().out
    assert "SPF_PLUS_ALL" in out and "# Setup Doctor report: mess.test" in out

    assert main([case["domain"], "--records", str(path), "--json"]) == 0
    ids = {f["id"] for f in json.loads(capsys.readouterr().out)}
    assert ids == set(case["expected"])


def test_domain_exists_distinguishes_nxdomain_from_noanswer(monkeypatch):
    def nx(name, rtype):
        raise dns.resolver.NXDOMAIN()

    def no(name, rtype):
        raise dns.resolver.NoAnswer()

    assert make_live(monkeypatch, nx).domain_exists("d.test") is False
    assert make_live(monkeypatch, no).domain_exists("sub.d.test") is True
    assert make_live(monkeypatch, lambda n, t: ["soa"]).domain_exists("d.test") is True


def test_cli_refuses_to_diagnose_a_domain_that_does_not_resolve(monkeypatch, capsys):
    """Regression: a resolver that answers NXDOMAIN for everything (as this build sandbox
    does, even for example.com) used to yield confident SPF_MISSING / DMARC_MISSING findings."""
    def nx(self, name, rtype):
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", nx)
    assert main(["example.com"]) == 2
    captured = capsys.readouterr()
    assert "does not exist in DNS" in captured.err
    assert "SPF_MISSING" not in captured.out


def test_cli_exits_2_with_no_diagnosis_when_dns_is_down(monkeypatch, capsys):
    def boom(self, name, rtype):
        raise dns.resolver.LifetimeTimeout()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", boom)
    assert main(["example.test"]) == 2
    captured = capsys.readouterr()
    assert "No diagnosis was produced" in captured.err
    assert "SPF_MISSING" not in captured.out
