"""Webhook signature + public web checker surface."""
from __future__ import annotations

import json

from evals.fixtures import CASES
from fastapi.testclient import TestClient

from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.surfaces.api import create_app
from setup_doctor.surfaces.hooks import extract_domains, sign_payload, verify_signature

MESS = next(c for c in CASES if c["name"] == "worst_case_combo")


def test_sign_and_verify_roundtrip():
    import time

    body = b'{"domain":"a.test"}'
    ts = str(int(time.time()))
    header = sign_payload("s3cret", body, timestamp=ts)
    assert verify_signature("s3cret", body, header, max_age_sec=300)
    assert not verify_signature("wrong", body, header, max_age_sec=300)


def test_extract_domains_from_payloads():
    assert extract_domains({"domain": "Ex.TEST"}) == ["ex.test"]
    assert extract_domains({"email": "a@Send.Example.com"}) == ["send.example.com"]
    assert "a.test" in extract_domains({"domains": ["a.test", "a.test"]})


def test_webhook_requires_secret_and_signature(monkeypatch):
    monkeypatch.setenv("SETUP_DOCTOR_INSTANTLY_HOOK_SECRET", "hook-secret")
    app = create_app(resolver_factory=lambda: FixtureResolver(MESS["records"]))
    client = TestClient(app)
    body = {"domain": MESS["domain"], "idempotency_key": "k1"}
    raw = json.dumps(body).encode()
    r = client.post("/hooks/instantly", content=raw)
    assert r.status_code == 401
    sig = sign_payload("hook-secret", raw)
    r2 = client.post(
        "/hooks/instantly",
        content=raw,
        headers={"X-Setup-Doctor-Signature": sig, "Content-Type": "application/json"},
    )
    assert r2.status_code == 200
    assert r2.json()["count"] >= 1
    assert r2.json()["rows"][0]["ok"] is True


def test_web_checker_serves_html():
    app = create_app(resolver_factory=lambda: FixtureResolver({}))
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "Setup Doctor" in r.text
    assert "/diagnose" in r.text


def test_fix_packet_endpoint():
    app = create_app(resolver_factory=lambda: FixtureResolver(MESS["records"]))
    r = TestClient(app).post(
        "/fix-packet",
        json={"domain": MESS["domain"], "provider": "cloudflare"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fix_packet"]["provider"] == "cloudflare"
    assert body["violations"] == []
    assert body["findings"]
