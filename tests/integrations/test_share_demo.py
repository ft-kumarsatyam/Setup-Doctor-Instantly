"""The share demo is offline: Instantly booleans pass, the gate still blocks."""
from setup_doctor.integrations.instantly.share_demo import render_share_demo, run_share_demo
from setup_doctor.surfaces.cli import main


def test_share_demo_blocks_when_instantly_vitals_pass():
    demo = run_share_demo()
    assert demo.domain == "client.test"
    assert demo.instantly_all_pass is True
    assert demo.finding_ids == ["DKIM_WEAK_KEY", "DMARC_POLICY_NONE", "SPF_PLUS_ALL"]
    assert demo.vitals_correlation == "disagree"
    assert demo.warmup_verdict == "mismatch"
    assert demo.launch_verdict == "blocked"
    assert demo.allowed_to_activate is False
    assert "SPF_PLUS_ALL" in demo.summary_spoken
    assert demo.ai_rewrite_source == "template_fallback"
    assert demo.ai_rewrite_violations
    assert any("SPF_MISSING" in v for v in demo.ai_plan_violations)
    text = render_share_demo(demo)
    assert "allPass=true" in text
    assert "allowed_to_activate: false" in text


def test_share_demo_cli_needs_no_key():
    assert main(["--share-demo"]) == 0
    assert main(["--share-demo", "--json"]) == 0
