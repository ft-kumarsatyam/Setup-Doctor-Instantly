"""Deliverability Agent handoff. Findings decide the act. Agent state is quoted."""
from __future__ import annotations

from setup_doctor.core.models import Finding
from setup_doctor.integrations.instantly.agent_handoff import (
    build_agent_handoff,
    verify_agent_handoff,
)

CRITICAL = Finding("SPF_MISSING", "critical", "SPF missing", "No SPF.", "Publish SPF.")


def test_critical_finding_holds_and_missing_agent_stays_unknown():
    card = build_agent_handoff([CRITICAL])
    assert card["act"] == "hold"
    assert card["allowed_to_activate"] is False
    assert card["instantly_agent"]["deployed"] is None
    assert verify_agent_handoff(card) == []
    lied = {**card, "act": "clear", "allowed_to_activate": True}
    assert verify_agent_handoff(lied)


def test_clean_dns_without_instantly_stays_unknown():
    card = build_agent_handoff([])
    assert card["act"] == "unknown"
    assert card["allowed_to_activate"] is False


def test_deployed_agent_is_quoted_not_invented():
    card = build_agent_handoff(
        [],
        instantly_checked=True,
        agent_blob={"state": {"agent": {"id": "agent-1"}}, "feed": [{"id": "f1"}]},
    )
    assert card["act"] == "clear"
    assert card["instantly_agent"]["deployed"] is True
    assert card["instantly_agent"]["id"] == "agent-1"
    assert card["instantly_agent"]["feed_items"] == 1


def test_null_agent_is_not_deployed():
    card = build_agent_handoff(
        [],
        instantly_checked=True,
        agent_blob={"state": {"agent": None}, "feed": None},
    )
    assert card["act"] == "clear"
    assert card["instantly_agent"]["deployed"] is False
