"""ESP pack mapping + multi-workspace readiness."""
from __future__ import annotations

from evals.fixtures import CASES

from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.explain import TemplateExplainer
from setup_doctor.integrations.instantly import InstantlyClient, RecordingTransport
from setup_doctor.integrations.instantly.esp import esp_packs_for_accounts, provider_from_account
from setup_doctor.integrations.instantly.workspaces import run_all_workspaces_readiness

CLEAN = next(c for c in CASES if c["name"] == "clean")


def test_provider_from_account_aliases():
    assert provider_from_account({"provider": "Google Workspace"}) == "google"
    assert provider_from_account({"provider_code": "outlook"}) == "microsoft"
    assert provider_from_account({"email": "a@x.com"}) is None


def test_esp_packs_merge_instantly_and_google():
    packs = esp_packs_for_accounts([
        {"email": "a@x.com", "provider": "google"},
        {"email": "b@x.com", "provider": "microsoft"},
    ])
    assert packs[0] == "instantly"
    assert "google" in packs and "microsoft" in packs


def test_with_workspace_sets_header():
    transport = RecordingTransport({
        ("GET", "/accounts"): (200, {"items": [], "next_starting_after": None}),
    })
    client = InstantlyClient(
        api_key="k",
        base_url="https://example.test/api/v2",
        transport=transport,
    ).with_workspace("ws-sub-1")
    client.list_accounts()
    assert transport.last_headers.get("x-as-workspace") == "ws-sub-1"


def test_run_all_workspaces_readiness_with_fixtures():
    transport = RecordingTransport({
        ("GET", "/workspaces/current"): (
            200, {"id": "ws-admin", "name": "Agency Admin"},
        ),
        ("GET", "/workspace-group-members"): (
            200,
            {
                "items": [{"sub_workspace_id": "ws-sub", "id": "m1"}],
                "next_starting_after": None,
            },
        ),
        ("GET", "/accounts"): (
            200,
            {
                "items": [{"email": f"a@{CLEAN['domain']}", "stat_warmup_score": 80}],
                "next_starting_after": None,
            },
        ),
        ("GET", "/inbox-placement-tests"): (
            200, {"items": [], "next_starting_after": None},
        ),
        ("POST", "/inbox-placement-analytics/stats-by-test-id"): (200, []),
        ("POST", "/accounts/warmup-analytics"): (
            200, {"aggregate_data": {}, "email_date_data": {}},
        ),
        ("POST", "/accounts/test/vitals"): (
            200, {"success_list": [], "failure_list": []},
        ),
        ("GET", "/ai-agents/deliverability/state"): (
            200, {"agent": None},
        ),
    })
    client = InstantlyClient(
        api_key="k",
        base_url="https://example.test/api/v2",
        transport=transport,
    )
    report = run_all_workspaces_readiness(
        client,
        FixtureResolver(CLEAN["records"]),
        TemplateExplainer(),
        include_rich_signals=True,
    )
    assert report.admin_workspace and report.admin_workspace.get("id") == "ws-admin"
    assert len(report.workspaces) >= 2  # admin/current + sub
    assert any(w.workspace_id == "ws-sub" for w in report.workspaces)
    assert all(w.ok for w in report.workspaces)
    d = report.to_dict()
    assert "ready_count" in d
