"""Run the full eval suite and write evals/RESULTS.md.

    python evals/run_evals.py          # exit code 0 only if every expectation holds

Questions answered separately:
  1. Detection: do the deterministic checks find exactly the planted problems?
  2. Advisory detection: BIMI/MTA-STS/TLS-RPT packs (opt-in)
  3. Guardrail: when the LLM misbehaves, does bad text ever reach the user?
  4. Schema contract: DiagnosisResult shape stable
  5. Shadow: reported separately (skipped in CI without corpus)

The guardrail leak metric is deliberately NOT computed with the verifier under
test (that would be circular). Hallucinating fakes plant a marker string, and we
search the delivered text for it independently.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.contracts.schema_contract import eval_schema_contract  # noqa: E402
from evals.detection.fixtures import ADVISORY_CASES, CASES  # noqa: E402
from evals.guardrails.fakes import BEHAVIORS, PLANTED_MARKERS, faithful  # noqa: E402
from evals.shadow.run_shadow import eval_shadow  # noqa: E402
from setup_doctor import FixtureResolver, LLMExplainer, diagnose, run_checks, verify_grounding  # noqa: E402
from setup_doctor.checks.registry import ALL_DNS_PACKS  # noqa: E402
from setup_doctor.core.models import Finding  # noqa: E402
from setup_doctor.core.result import DiagnosisResult  # noqa: E402
from setup_doctor.explain import PROMPT  # noqa: E402
from setup_doctor.explain.instantly_rewrite import (  # noqa: E402
    rewrite_instantly_signals,
    verify_instantly_rewrite,
)
from setup_doctor.integrations.instantly.compare import AccountComparison  # noqa: E402
from setup_doctor.integrations.instantly.launch import (  # noqa: E402
    build_pre_launch_gate,
    verify_pre_launch_gate_honesty,
)
from setup_doctor.integrations.instantly.readiness import (  # noqa: E402
    DomainReadiness,
    WorkspaceReadinessReport,
)


def _score_cases(cases: list[dict], *, packs=None) -> dict:
    tp = fp = fn = 0
    exact = 0
    per_id: dict[str, Counter] = defaultdict(Counter)
    misses = []
    for c in cases:
        got = sorted(
            f.id for f in run_checks(c["domain"], FixtureResolver(c["records"]), packs=packs)
        )
        want = c["expected"]
        g, w = set(got), set(want)
        tp += len(g & w)
        fp += len(g - w)
        fn += len(w - g)
        exact += got == want
        for i in g | w:
            key = "tp" if i in g and i in w else "fp" if i in g else "fn"
            per_id[i][key] += 1
        if got != want:
            misses.append({"case": c["name"], "expected": want, "got": got})
    return {
        "cases": len(cases), "exact_match": exact,
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "tp": tp, "fp": fp, "fn": fn,
        "per_id": {k: dict(v) for k, v in sorted(per_id.items())},
        "misses": misses,
    }


def eval_detection() -> dict:
    return _score_cases(CASES)


def eval_advisory_detection() -> dict:
    return _score_cases(ADVISORY_CASES, packs=ALL_DNS_PACKS)


def _severe(findings) -> bool:
    return any(f.severity in ("critical", "high") for f in findings)


def _prompt_for(findings) -> str:
    return PROMPT.format(findings=json.dumps([f.to_dict() for f in findings], indent=2))


def eval_guardrail() -> dict:
    rows = {}
    for name, fn in BEHAVIORS.items():
        r = Counter()
        marker = PLANTED_MARKERS.get(name)
        for c in CASES:
            resolver = FixtureResolver(c["records"])
            findings = run_checks(c["domain"], resolver)
            if not findings:
                r["skipped_no_findings"] += 1
                continue
            r["with_findings"] += 1
            r["with_severe"] += _severe(findings)
            try:
                differs = fn(_prompt_for(findings)) != faithful(_prompt_for(findings))
            except Exception:
                differs = True
            r["exercised"] += differs
            state = diagnose(c["domain"], resolver, LLMExplainer(fn))
            r["fell_back" if state["used_fallback"] else "accepted"] += 1
            if marker and marker in state["explanation"]:
                r["planted_hallucinations_delivered"] += 1
            if verify_grounding(state["explanation"], state["findings"]):
                r["delivered_failing_verifier"] += 1
        rows[name] = dict(r)
    return {"behaviors": rows}


def eval_instantly_rewrite() -> dict:
    """Instantly signal rewrite must reject invented scores/verdicts; fall back to template."""
    rows = [
        AccountComparison(
            email="a@example.com",
            warmup_score=92.0,
            health_score=88.0,
            inbox_percent=20.0,
            spam_percent=80.0,
            test_ids=["t1"],
            verdict="mismatch",
            note="engine note",
        ),
        AccountComparison(
            email="b@example.com",
            warmup_score=None,
            health_score=None,
            inbox_percent=None,
            spam_percent=None,
            test_ids=[],
            verdict="unknown",
            note="missing",
        ),
    ]

    def invent_score(_prompt: str) -> str:
        return json.dumps([
            {"email": "a@example.com", "summary": "Warmup 99 is aligned somehow."},
            {"email": "b@example.com", "summary": "Account looks healthy."},
        ])

    def faithful_rewrite(_prompt: str) -> str:
        return json.dumps([
            {
                "email": "a@example.com",
                "summary": "Engine verdict mismatch: warmup 92 vs inbox 20.",
            },
            {
                "email": "b@example.com",
                "summary": "Engine verdict unknown — no warmup or placement data.",
            },
        ])

    bad_md, bad_src, bad_viol = rewrite_instantly_signals(rows, invent_score)
    good_md, good_src, good_viol = rewrite_instantly_signals(rows, faithful_rewrite)
    # Direct verifier also rejects inventing aligned for mismatch
    direct = verify_instantly_rewrite(
        [
            {"email": "a@example.com", "summary": "aligned with warmup 92."},
            {"email": "b@example.com", "summary": "unknown."},
        ],
        rows,
    )
    return {
        "invented_falls_back": bad_src == "template_fallback" and bool(bad_viol),
        "faithful_accepted": good_src == "model_verified" and good_viol == [],
        "verdict_invention_rejected": bool(direct),
        "template_mentions_unknown": "unknown" in bad_md.lower(),
        "gtm_summary_present": "GTM summary" in good_md,
    }


def eval_pre_launch_gate() -> dict:
    """Critical Findings must never yield allowed_to_activate; invented allow rejected."""
    finding = Finding(
        id="SPF_MISSING",
        severity="critical",
        title="SPF missing",
        why="why",
        fix="Add SPF",
    )
    report = WorkspaceReadinessReport(
        domains=[DomainReadiness(
            domain="ex.test",
            diagnosis=DiagnosisResult(
                domain="ex.test",
                findings=[finding],
                explanation="",
                explanation_source="template",
                report="",
            ),
            error=None,
            comparisons=[AccountComparison(
                email="a@ex.test",
                warmup_score=90.0,
                health_score=90.0,
                inbox_percent=90.0,
                spam_percent=5.0,
                verdict="aligned",
                note="ok",
            )],
        )],
    )
    gate = build_pre_launch_gate(report)
    invented = {
        **gate,
        "allowed_to_activate": True,
        "launch_verdict": "ready",
        "blocking_finding_ids": ["SPF_MISSING"],
    }
    return {
        "critical_blocks": gate.get("allowed_to_activate") is False
        and gate.get("launch_verdict") == "blocked",
        "honesty_accepts_real_gate": verify_pre_launch_gate_honesty(gate) == [],
        "honesty_rejects_invented_allow": bool(verify_pre_launch_gate_honesty(invented)),
        "spoken_present": bool(gate.get("summary_spoken")),
    }


def check_expectations(
    det: dict, guard: dict, adv: dict, contract: dict, instantly: dict | None = None,
    gate: dict | None = None,
) -> list[str]:
    bad = []
    if det["exact_match"] != det["cases"]:
        bad.append(f"detection: {det['cases'] - det['exact_match']} case(s) mismatched")
    if adv["exact_match"] != adv["cases"]:
        bad.append(f"advisory detection: {adv['cases'] - adv['exact_match']} case(s) mismatched")
    if not contract.get("ok"):
        bad.append(f"schema contract failed: {contract}")
    b = guard["behaviors"]
    n = b["faithful"]["with_findings"]
    if b["faithful"].get("accepted", 0) != n:
        bad.append("faithful drafts should all be accepted")
    for name in (
        "hallucinated_finding", "hallucinated_record", "malformed_json",
        "duplicate_ids", "raises", "empty",
    ):
        if b[name].get("fell_back", 0) != n:
            bad.append(f"{name}: every draft should be rejected")
    if b["drops_severe_finding"].get("fell_back", 0) != b["drops_severe_finding"]["with_severe"]:
        bad.append("drops_severe_finding: should be rejected exactly when a critical/high finding exists")
    if b["misstates_numbers"].get("fell_back", 0) != b["misstates_numbers"].get("exercised", 0):
        bad.append("misstates_numbers: should be rejected exactly when a number was changed")
    for name, row in b.items():
        if row.get("planted_hallucinations_delivered", 0):
            bad.append(f"{name}: planted hallucination reached the user")
        if row.get("delivered_failing_verifier", 0):
            bad.append(f"{name}: delivered text fails verification")
    if instantly:
        if not instantly.get("invented_falls_back"):
            bad.append("instantly rewrite: invented scores must fall back to template")
        if not instantly.get("faithful_accepted"):
            bad.append("instantly rewrite: faithful grounded draft must be accepted")
        if not instantly.get("verdict_invention_rejected"):
            bad.append("instantly rewrite: invented verdicts must be rejected")
        if not instantly.get("template_mentions_unknown"):
            bad.append("instantly rewrite: template fallback must keep unknown explicit")
    if gate:
        if not gate.get("critical_blocks"):
            bad.append("pre_launch_gate: critical Findings must block activate")
        if not gate.get("honesty_accepts_real_gate"):
            bad.append("pre_launch_gate: honest gate payload must pass verifier")
        if not gate.get("honesty_rejects_invented_allow"):
            bad.append("pre_launch_gate: invented allowed_to_activate must be rejected")
        if not gate.get("spoken_present"):
            bad.append("pre_launch_gate: summary_spoken required")
    return bad


def render(
    det: dict, guard: dict, adv: dict, contract: dict, shadow: dict,
    failures: list[str], instantly: dict | None = None, gate: dict | None = None,
) -> str:
    L = ["# Eval results", "",
         "Generated by `python evals/run_evals.py`. Fixtures are synthetic "
         "(see `evals/detection/fixtures.py`), so detection numbers show correctness "
         "and regression safety, not real-world accuracy.", "",
         f"**Status: {'PASS' if not failures else 'FAIL'}**"]
    L += [f"- {f}" for f in failures]
    L += ["", "## 1. Detection (deterministic checks vs planted ground truth)", "",
          f"- Cases: **{det['cases']}**; exact finding-set match: **{det['exact_match']}/{det['cases']}**",
          f"- Precision: **{det['precision']:.3f}**, recall: **{det['recall']:.3f}** "
          f"(TP {det['tp']}, FP {det['fp']}, FN {det['fn']})", ""]
    L += ["| Finding id | TP | FP | FN |", "|---|---|---|---|"]
    for k, v in det["per_id"].items():
        L.append(f"| `{k}` | {v.get('tp', 0)} | {v.get('fp', 0)} | {v.get('fn', 0)} |")
    L += ["", "## 1b. Advisory detection (BIMI / MTA-STS / TLS-RPT)", "",
          f"- Cases: **{adv['cases']}**; exact match: **{adv['exact_match']}/{adv['cases']}**",
          f"- Precision: **{adv['precision']:.3f}**, recall: **{adv['recall']:.3f}**", ""]
    L += ["", "## 2. Guardrail", "",
          "Each scripted model behavior is run against every fixture that has findings "
          f"({guard['behaviors']['faithful']['with_findings']} of {det['cases']}). "
          "'Exercised' counts cases where the fake's output actually differed from a faithful one.", "",
          "| Model behavior | Exercised | Accepted | Rejected -> fallback | Planted hallucinations delivered | Expected |",
          "|---|---|---|---|---|---|"]
    expect = {
        "faithful": "accept all",
        "hallucinated_finding": "reject all",
        "hallucinated_record": "reject all",
        "drops_severe_finding": "reject iff a critical/high finding exists",
        "misstates_numbers": "reject when number changed",
        "malformed_json": "reject all",
        "duplicate_ids": "reject all",
        "raises": "reject all",
        "empty": "reject all",
    }
    for name, r in guard["behaviors"].items():
        L.append(f"| `{name}` | {r.get('exercised', 0)} | {r.get('accepted', 0)} | {r.get('fell_back', 0)} | "
                 f"{r.get('planted_hallucinations_delivered', 0) if name in PLANTED_MARKERS else 'n/a'} | {expect[name]} |")
    ms = guard["behaviors"]["misstates_numbers"]
    L += ["", f"`misstates_numbers` alters a lookup count while citing real ids and records. "
          f"It changed the text in {ms.get('exercised', 0)} fixtures; the verifier rejected "
          f"{ms.get('fell_back', 0)} of those and fell back to the template. "
          "Numeric grounding covers allow-listed claim shapes against finding titles/evidence only.", ""]
    L += ["", "## 2b. Instantly signal rewrite guardrail", ""]
    if instantly:
        L += [
            f"- Invented scores fall back: **{instantly.get('invented_falls_back')}**",
            f"- Faithful rewrite accepted: **{instantly.get('faithful_accepted')}**",
            f"- Invented verdict rejected: **{instantly.get('verdict_invention_rejected')}**",
            f"- Template keeps unknown: **{instantly.get('template_mentions_unknown')}**",
            "",
            "Instantly rewrite never invents Findings; missing Instantly data stays unknown.",
            "",
        ]
    if gate:
        L += ["", "## 2c. Pre-launch gate honesty", ""]
        L += [
            f"- Critical Findings block activate: **{gate.get('critical_blocks')}**",
            f"- Honest gate accepted: **{gate.get('honesty_accepts_real_gate')}**",
            f"- Invented allow rejected: **{gate.get('honesty_rejects_invented_allow')}**",
            f"- Spoken summary present: **{gate.get('spoken_present')}**",
            "",
        ]
    L += ["", "## 3. Schema contract", "",
          f"- schema_version: `{contract.get('schema_version')}` "
          f"(expected `{contract.get('expected_schema_version')}`)",
          f"- ok: **{contract.get('ok')}**", ""]
    L += ["", "## 4. Shadow corpus (not production accuracy)", "",
          f"- status: **{shadow.get('status')}** · cases: {shadow.get('cases', 0)}",
          f"- {shadow.get('note', '')}", ""]
    return "\n".join(L)


def main() -> int:
    det = eval_detection()
    adv = eval_advisory_detection()
    guard = eval_guardrail()
    instantly = eval_instantly_rewrite()
    gate = eval_pre_launch_gate()
    contract = eval_schema_contract()
    shadow = eval_shadow()
    failures = check_expectations(det, guard, adv, contract, instantly, gate)
    out = Path(__file__).resolve().parent
    md = render(det, guard, adv, contract, shadow, failures, instantly, gate)
    (out / "RESULTS.md").write_text(md)
    print(md)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
