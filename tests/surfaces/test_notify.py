"""Slack notify — missing webhook stays not_checked."""
from __future__ import annotations

from setup_doctor.surfaces.notify import notify_slack


def test_slack_not_checked_without_url(monkeypatch):
    monkeypatch.delenv("SETUP_DOCTOR_SLACK_WEBHOOK_URL", raising=False)
    assert notify_slack("hi")["status"] == "not_checked"


def test_slack_ok_with_transport():
    def transport(url, body):
        assert b"hi" in body
        return 200, b"ok"

    out = notify_slack("hi", webhook_url="https://hooks.example/test", transport=transport)
    assert out["status"] == "ok"
