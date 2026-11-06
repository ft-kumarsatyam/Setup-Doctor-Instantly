"""MCP HTTP auth gate + Instantly header context — no live Instantly/DNS."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from starlette.testclient import TestClient

from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.integrations.instantly import InstantlyClient, RecordingTransport
from setup_doctor.surfaces.api import create_app
from setup_doctor.surfaces.auth import ApiKeyAuth
from setup_doctor.surfaces.mcp_server import (
    TOOLS,
    create_mcp_http_app,
    reset_request_instantly_context,
    set_request_instantly_context,
    tool_compare_instantly,
)

pytest.importorskip("mcp")


def test_mcp_http_rejects_missing_api_key():
    auth = ApiKeyAuth(keys={"secret": "t1"})

    def authenticate(x_api_key, authorization):
        return auth.authenticate(x_api_key, authorization)

    app = create_mcp_http_app(auth_authenticate=authenticate)
    with TestClient(app) as client:
        r = client.post("/mcp", json={})
    assert r.status_code == 401
    detail = r.json()["detail"].lower()
    assert "api key" in detail


def test_mcp_http_allows_valid_api_key_through_gate():
    auth = ApiKeyAuth(keys={"secret": "t1"})

    def authenticate(x_api_key, authorization):
        return auth.authenticate(x_api_key, authorization)

    app = create_mcp_http_app(auth_authenticate=authenticate)
    with TestClient(app) as client:
        # Auth passes; MCP protocol may still reject malformed body (not 401).
        r = client.post(
            "/mcp",
            headers={"X-API-Key": "secret"},
            json={},
        )
    assert r.status_code != 401


def test_mcp_http_open_when_auth_disabled():
    app = create_mcp_http_app(auth_authenticate=None)
    with TestClient(app) as client:
        r = client.post("/mcp", json={})
    assert r.status_code != 401


def test_instantly_header_context_used_by_tool(monkeypatch, caplog):
    transport = RecordingTransport({
        ("GET", "/accounts"): (200, {"items": [], "next_starting_after": None}),
        ("GET", "/inbox-placement-tests"): (200, {"items": [], "next_starting_after": None}),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (200, []),
        ("POST", "/accounts/warmup-analytics"): (200, {"aggregate_data": {}, "email_date_data": {}}),
    })
    seen: dict[str, str] = {}

    def fake_resolve(**kwargs):
        seen["header"] = kwargs.get("header_value") or ""
        return InstantlyClient(
            api_key=kwargs.get("header_value") or "x",
            base_url="https://example.test/api/v2",
            transport=transport,
        )

    monkeypatch.setattr(
        "setup_doctor.surfaces.mcp_server.resolve_instantly_client",
        fake_resolve,
    )
    tokens = set_request_instantly_context(
        "header-secret-key",
        factory=lambda: InstantlyClient(api_key="factory-key", transport=transport),
    )
    try:
        with caplog.at_level(logging.INFO):
            out = tool_compare_instantly({})
        assert out["schema_version"] == "1.0"
        assert seen["header"] == "header-secret-key"
        assert "header-secret-key" not in caplog.text
    finally:
        reset_request_instantly_context(tokens)


def test_tools_registry_includes_pre_launch_gate():
    assert set(TOOLS) == {
        "diagnose",
        "compare_instantly",
        "instantly_ready",
        "campaign_desk",
        "reply_desk",
        "pre_launch_gate",
    }


def test_mounted_mcp_no_http_307_on_bare_path():
    """Fly/proxy clients break on 307 Location: http://…/mcp/ — rewrite in-process."""
    app = create_app(
        resolver_factory=lambda: FixtureResolver({}),
        auth=ApiKeyAuth(keys={"secret": "t1"}),
        mount_mcp=True,
    )
    with FastAPITestClient(app, follow_redirects=False) as client:
        r = client.post(
            "/mcp",
            headers={
                "X-API-Key": "secret",
                "X-Forwarded-Proto": "https",
            },
            json={},
        )
    # In-process rewrite → MCP protocol response (e.g. 406), never Mount 307 to http://…/mcp/
    assert r.status_code not in (301, 302, 307, 308)
    assert r.headers.get("location") is None


def test_schema_reports_auth_and_connect_docs():
    app = create_app(
        resolver_factory=lambda: FixtureResolver({}),
        auth=ApiKeyAuth(keys={"secret": "t1"}),
    )
    r = FastAPITestClient(app).get("/schema")
    assert r.status_code == 200
    body = r.json()
    assert body.get("auth_required") is True
    assert "connect" in (body.get("connect_docs") or "").lower()
