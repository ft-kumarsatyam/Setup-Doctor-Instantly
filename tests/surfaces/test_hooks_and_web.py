"""Webhook signature + public web checker surface."""
from __future__ import annotations

import json

from evals.fixtures import CASES
from fastapi.testclient import TestClient

from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.surfaces.api import create_app
from setup_doctor.surfaces.hooks import extract_domains, sign_payload, verify_signature
from setup_doctor.surfaces.webhook_store import WebhookStore

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
    assert r2.json()["rows"][0]["agent_handoff"]["act"] in ("hold", "review", "unknown", "clear")


def test_webhook_result_survives_a_new_process(tmp_path, monkeypatch):
    monkeypatch.setenv("SETUP_DOCTOR_INSTANTLY_HOOK_SECRET", "hook-secret")
    store = WebhookStore(tmp_path / "hooks.json")
    app = create_app(
        resolver_factory=lambda: FixtureResolver(MESS["records"]),
        webhook_store=store,
    )
    body = {"domain": MESS["domain"], "idempotency_key": "k-disk"}
    raw = json.dumps(body).encode()
    sig = sign_payload("hook-secret", raw)
    posted = TestClient(app).post(
        "/hooks/instantly",
        content=raw,
        headers={"X-Setup-Doctor-Signature": sig, "Content-Type": "application/json"},
    )
    assert posted.status_code == 200
    restarted = create_app(
        resolver_factory=lambda: FixtureResolver({}),
        webhook_store=store,
    )
    last = TestClient(restarted).get(f"/hooks/instantly/last/{MESS['domain']}")
    assert last.status_code == 200
    assert last.json()["ok"] is True
    assert last.json()["agent_handoff"]["act"] == "hold"


def test_web_checker_serves_html():
    app = create_app(resolver_factory=lambda: FixtureResolver({}))
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "Setup Doctor" in r.text
    assert "/diagnose" in r.text
    assert "safe to launch" in r.text.lower()
    assert "Advanced — API keys" in r.text
    assert "mcp.instantly.ai" in r.text
    assert 'href="/connect"' in r.text
    assert 'data-auth-required="0"' in r.text
    assert "Where do I get a Setup Doctor API key?" in r.text
    assert "Enter domain" in r.text
    assert "Reply Desk" in r.text
    assert "does not send replies" in r.text
    assert "friendlyError" in r.text


def test_connect_page_mirrors_instantly_docs():
    app = create_app(resolver_factory=lambda: FixtureResolver({}))
    r = TestClient(app).get("/connect")
    assert r.status_code == 200
    assert "Connect Instantly MCP" in r.text
    assert "mcp.instantly.ai" in r.text
    assert "SETUP_DOCTOR_API_KEYS" in r.text
    assert "pre_launch_gate" in r.text
    assert "docs/INSTANTLY_CONNECT.md" in r.text
    assert "no</em> public signup" in r.text or "no public signup" in r.text.lower()


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
