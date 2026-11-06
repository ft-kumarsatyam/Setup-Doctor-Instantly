"""Run the full eval suite and write evals/RESULTS.md.

    python evals/run_evals.py          # exit code 0 only if every expectation holds

Questions answered separately:
  1. Detection: do the deterministic checks find exactly the planted problems?
  2. Advisory detection: BIMI/MTA-STS/TLS-RPT packs (opt-in)
  3. Guardrail: when the LLM misbehaves, does bad text ever reach the user?
  4. Schema contract: DiagnosisResult shape stable
  5. Shadow: reported separately (skipped in CI without corpus)
  6. Public DNS corpus: frozen real records, scored on their own (not added to synthetic P/R)
  7. Rewrite pairs: grounded plans from that corpus; invented ids/records rejected
  8. Rewrite RAG: retrieved examples are a subset of the current findings (not a finder)

The guardrail leak metric is deliberately NOT computed with the verifier under
test (that would be circular). Hallucinating fakes plant a marker string, and we
search the delivered text for it independently.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.contracts.schema_contract import eval_schema_contract  # noqa: E402
from evals.corpus.load import load_public_cases  # noqa: E402
from evals.detection.fixtures import ADVISORY_CASES, CASES  # noqa: E402
from evals.guardrails.fakes import BEHAVIORS, PLANTED_MARKERS, faithful  # noqa: E402
from evals.shadow.run_shadow import eval_shadow  # noqa: E402
from setup_doctor import FixtureResolver, LLMExplainer, diagnose, run_checks, verify_grounding  # noqa: E402
from setup_doctor.checks.registry import ALL_DNS_PACKS  # noqa: E402
from setup_doctor.core.models import Finding  # noqa: E402
from setup_doctor.core.result import DiagnosisResult  # noqa: E402
from setup_doctor.explain import render_prompt, verify_plan  # noqa: E402
from setup_doctor.explain.instantly_rewrite import (  # noqa: E402
    rewrite_instantly_signals,
    verify_instantly_rewrite,
)
from setup_doctor.explain.rag_index import PLANS  # noqa: E402
from setup_doctor.explain.retrieve import format_examples, retrieve_examples  # noqa: E402
from setup_doctor.integrations.instantly.agent_handoff import (  # noqa: E402
    build_agent_handoff,
    verify_agent_handoff,
)
from setup_doctor.integrations.instantly.campaign_desk import (  # noqa: E402
    run_campaign_desk,
    verify_campaign_desk_honesty,
)
from setup_doctor.integrations.instantly.client import (  # noqa: E402
    InstantlyClient,
    RecordingTransport,
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
from setup_doctor.integrations.instantly.reply_desk import (  # noqa: E402
    run_reply_desk,
    verify_reply_desk_honesty,
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
    payload = json.dumps([f.to_dict() for f in findings], indent=2)
    block = format_examples(retrieve_examples([f.id for f in findings]))
    return render_prompt(payload, example_block=block)


def eval_guardrail(cases: list[dict] | None = None) -> dict:
    cases = CASES if cases is None else cases
    rows = {}
    for name, fn in BEHAVIORS.items():
        r = Counter()
        marker = PLANTED_MARKERS.get(name)
        for c in cases:
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


def eval_desks() -> dict:
    """Unhealthy sending status must stall. Unread mail must not look clear."""
    client = InstantlyClient(
        api_key="eval-key-not-secret",
        base_url="https://example.test/api/v2",
        transport=RecordingTransport({
            ("GET", "/campaigns"): (200, {
                "items": [{"id": "c1", "name": "Live", "status": 1}],
                "next_starting_after": None,
            }),
            ("GET", "/campaigns/analytics"): (200, [{
                "campaign_id": "c1",
                "campaign_name": "Live",
                "emails_sent_count": 10,
                "reply_count_unique": 2,
                "bounced_count": 1,
            }]),
            ("GET", "/campaigns/c1/sending-status"): (200, {
                "diagnostics": {"status": "campaign_accounts_unhealthy"},
                "summary": {"status": "campaign_accounts_unhealthy", "status_message": "Accounts are unhealthy."},
            }),
        }),
        sleep=lambda _s: None,
    )
    desk = run_campaign_desk(client)
    lied = desk.to_dict()
    lied["verdict"] = "sending"
    reply = run_reply_desk(InstantlyClient(
        api_key="eval-key-not-secret",
        base_url="https://example.test/api/v2",
        transport=RecordingTransport({
            ("GET", "/emails/unread/count"): (200, {"count": 4}),
            ("GET", "/emails"): (200, {"items": [], "next_starting_after": None}),
        }),
        sleep=lambda _s: None,
    ))
    missing = run_reply_desk(InstantlyClient(
        api_key="eval-key-not-secret",
        base_url="https://example.test/api/v2",
        transport=RecordingTransport({
            ("GET", "/emails/unread/count"): (200, {}),
            ("GET", "/emails"): (200, {"items": []}),
        }),
        sleep=lambda _s: None,
    ))
    return {
        "unhealthy_stalls": desk.verdict == "stalled",
        "honesty_rejects_sending": bool(verify_campaign_desk_honesty(lied)),
        "unread_is_attention": reply.verdict == "attention",
        "missing_count_unknown": missing.verdict == "unknown",
        "clear_rejected": bool(verify_reply_desk_honesty({**reply.to_dict(), "verdict": "clear"})),
        "pages_joined": _reply_pages_joined(),
        "handoff_holds": _handoff_holds(),
        "handoff_clear_rejected": _handoff_clear_rejected(),
    }


def _reply_pages_joined() -> bool:
    """Two Instantly pages must both show up. One page is not the whole inbox."""
    page_one = {
        "items": [{
            "id": "mail-a", "ue_type": 2, "lead": "a@client.test",
            "subject": "First", "is_unread": 1, "eaccount": "rep@send.test",
        }],
        "next_starting_after": "cursor-2",
    }
    page_two = {
        "items": [{
            "id": "mail-b", "ue_type": 2, "lead": "b@client.test",
            "subject": "Second", "is_unread": 1, "eaccount": "rep@send.test",
        }],
        "next_starting_after": None,
    }
    report = run_reply_desk(InstantlyClient(
        api_key="eval-key-not-secret",
        base_url="https://example.test/api/v2",
        transport=RecordingTransport({
            ("GET", "/emails/unread/count"): (200, {"count": 2}),
            ("GET", "/emails", ""): (200, page_one),
            ("GET", "/emails", "cursor-2"): (200, page_two),
        }),
        sleep=lambda _s: None,
    ), blocked_domains={"send.test"})
    ids = [thread.email_id for thread in report.threads]
    blocked = all(thread.domain_blocked is True for thread in report.threads)
    return ids == ["mail-a", "mail-b"] and blocked and report.more_threads is False


def _handoff_holds() -> bool:
    card = build_agent_handoff([
        Finding("SPF_MISSING", "critical", "SPF missing", "No SPF record.", "Publish SPF."),
    ])
    return card["act"] == "hold" and card["allowed_to_activate"] is False


def _handoff_clear_rejected() -> bool:
    card = build_agent_handoff([
        Finding("SPF_MISSING", "critical", "SPF missing", "No SPF record.", "Publish SPF."),
    ])
    lied = {**card, "act": "clear", "allowed_to_activate": True}
    return bool(verify_agent_handoff(lied))


def _guard_failures(guard: dict, prefix: str) -> list[str]:
    bad = []
    b = guard["behaviors"]
    n = b["faithful"]["with_findings"]
    if b["faithful"].get("accepted", 0) != n:
        bad.append(f"{prefix}: faithful drafts should all be accepted")
    for name in (
        "hallucinated_finding", "hallucinated_record", "malformed_json",
        "duplicate_ids", "raises", "empty",
    ):
        if b[name].get("fell_back", 0) != n:
            bad.append(f"{prefix}: {name}: every draft should be rejected")
    if b["drops_severe_finding"].get("fell_back", 0) != b["drops_severe_finding"]["with_severe"]:
        bad.append(f"{prefix}: drops_severe_finding: should be rejected exactly when a critical/high finding exists")
    if b["misstates_numbers"].get("fell_back", 0) != b["misstates_numbers"].get("exercised", 0):
        bad.append(f"{prefix}: misstates_numbers: should be rejected exactly when a number was changed")
    for name, row in b.items():
        if row.get("planted_hallucinations_delivered", 0):
            bad.append(f"{prefix}: {name}: planted hallucination reached the user")
        if row.get("delivered_failing_verifier", 0):
            bad.append(f"{prefix}: {name}: delivered text fails verification")
    return bad


def eval_rewrite_pairs(cases: list[dict]) -> dict:
    """Teacher plans must be grounded. A planted id or record on the same plan must not be."""
    path = Path(__file__).resolve().parent / "corpus" / "rewrite_pairs.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    pairs_by = {row["domain"]: row for row in lines}
    with_findings = accepted = id_rejected = record_rejected = 0
    missing: list[str] = []
    seen: set[str] = set()
    for c in cases:
        findings = run_checks(c["domain"], FixtureResolver(c["records"]))
        if not findings:
            if c["domain"] in pairs_by:
                missing.append(f"{c['domain']} has a pair but no findings")
            continue
        with_findings += 1
        seen.add(c["domain"])
        row = pairs_by.get(c["domain"])
        if row is None:
            missing.append(c["domain"])
            continue
        plan = row["plan"]
        ids_ok = sorted(it["id"] for it in plan) == sorted(f.id for f in findings)
        if ids_ok and verify_plan(plan, findings) == []:
            accepted += 1
        invented = list(plan) + [{
            "id": "SPF_DOMAIN_SPOOFED",
            "explanation": "Your domain is being spoofed right now.",
        }]
        if any("unknown finding id" in v for v in verify_plan(invented, findings)):
            id_rejected += 1
        altered = [{"id": it["id"], "explanation": it["explanation"]} for it in plan]
        altered[0]["explanation"] += " Also publish `v=spf1 include:totally-made-up.test -all`."
        if any("not grounded" in v for v in verify_plan(altered, findings)):
            record_rejected += 1
    extra = sorted(set(pairs_by) - seen)
    return {
        "pairs": len(lines),
        "with_findings": with_findings,
        "teacher_accepted": accepted,
        "invented_id_rejected": id_rejected,
        "invented_record_rejected": record_rejected,
        "missing": missing,
        "extra": extra,
    }


_RECORD_RE = re.compile(r"v=(spf1|dmarc1|dkim1)", re.I)


def shipped_finding_ids() -> set[str]:
    text = (ROOT / "src" / "setup_doctor" / "checks" / "engine.py").read_text()
    return set(re.findall(
        r'Finding\(\s*"([A-Z][A-Z0-9_]+)",\s*"(?:critical|high|medium|low|info)"',
        text,
    ))


def eval_rag(public_cases: list[dict]) -> dict:
    """Example retrieval stays inside the current finding set and matches the builder."""
    from evals.corpus.build_rag_index import build_plans

    rebuilt = build_plans()
    indexed = {finding_id for plan in PLANS for finding_id, _ in plan}
    missing_ids = sorted(shipped_finding_ids() - indexed)
    unsafe: list[str] = []
    checked = 0
    groups = (
        (CASES, None),
        (ADVISORY_CASES, ALL_DNS_PACKS),
        (public_cases, None),
    )
    for cases, packs in groups:
        for case in cases:
            findings = run_checks(
                case["domain"], FixtureResolver(case["records"]), packs=packs,
            )
            if not findings:
                continue
            checked += 1
            query = {f.id for f in findings}
            got = retrieve_examples([f.id for f in findings])
            if len(got) > 2:
                unsafe.append(f"{case['name']}: returned {len(got)} examples")
            for plan in got:
                ids = {finding_id for finding_id, _ in plan}
                if not ids <= query:
                    unsafe.append(f"{case['name']}: example ids {sorted(ids - query)} are not in the findings")
                for _finding_id, explanation in plan:
                    if _RECORD_RE.search(explanation):
                        unsafe.append(f"{case['name']}: example contains a DNS record")
    return {
        "plans": len(PLANS),
        "drift": rebuilt != PLANS,
        "missing_ids": missing_ids,
        "unsafe": unsafe,
        "cases_checked": checked,
        "ids_covered": len(indexed),
        "ids_shipped": len(shipped_finding_ids()),
    }


def check_expectations(
    det: dict, guard: dict, adv: dict, contract: dict, instantly: dict | None = None,
    gate: dict | None = None, public: dict | None = None, public_guard: dict | None = None,
    rewrite: dict | None = None, rag: dict | None = None, desks: dict | None = None,
) -> list[str]:
    bad = []
    if det["exact_match"] != det["cases"]:
        bad.append(f"detection: {det['cases'] - det['exact_match']} case(s) mismatched")
    if adv["exact_match"] != adv["cases"]:
        bad.append(f"advisory detection: {adv['cases'] - adv['exact_match']} case(s) mismatched")
    if not contract.get("ok"):
        bad.append(f"schema contract failed: {contract}")
    bad += _guard_failures(guard, "guardrail")
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
    if desks:
        if not desks.get("unhealthy_stalls"):
            bad.append("campaign desk: unhealthy sending status must stall")
        if not desks.get("honesty_rejects_sending"):
            bad.append("campaign desk: sending verdict with a stalled row must be rejected")
        if not desks.get("unread_is_attention"):
            bad.append("reply desk: unread count above zero must be attention")
        if not desks.get("missing_count_unknown"):
            bad.append("reply desk: missing unread count must stay unknown")
        if not desks.get("clear_rejected"):
            bad.append("reply desk: clear with unread mail must be rejected")
        if not desks.get("pages_joined"):
            bad.append("reply desk: two pages must both be present")
        if not desks.get("handoff_holds"):
            bad.append("agent handoff: a critical Finding must hold")
        if not desks.get("handoff_clear_rejected"):
            bad.append("agent handoff: a clear act on a hold must be rejected")
    if public is not None:
        if public["exact_match"] != public["cases"]:
            bad.append(
                f"public corpus: {public['cases'] - public['exact_match']} case(s) mismatched"
            )
            for miss in public["misses"]:
                bad.append(
                    f"public corpus: {miss['case']} expected {miss['expected']} got {miss['got']}"
                )
    if public_guard is not None:
        bad += _guard_failures(public_guard, "public guardrail")
    if rewrite is not None:
        n = rewrite["with_findings"]
        if rewrite["teacher_accepted"] != n:
            bad.append("rewrite pairs: every teacher plan must be grounded")
        if rewrite["invented_id_rejected"] != n or rewrite["invented_record_rejected"] != n:
            bad.append("rewrite pairs: invented id or record must be rejected")
        if rewrite["missing"] or rewrite["extra"]:
            bad.append(
                f"rewrite pairs: missing={rewrite['missing']} extra={rewrite['extra']}"
            )
    if rag is not None:
        if rag["drift"]:
            bad.append("rewrite RAG: committed index drifted from evals/corpus/build_rag_index.py")
        if rag["missing_ids"]:
            bad.append(f"rewrite RAG: finding ids missing from the index: {rag['missing_ids']}")
        if rag["unsafe"]:
            bad.append(f"rewrite RAG: unsafe examples: {rag['unsafe'][:5]}")
    return bad


def _guard_table(guard: dict, case_count: int) -> list[str]:
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
    n = guard["behaviors"]["faithful"]["with_findings"]
    lines = [
        "Each scripted model behavior is run against every case that has findings "
        f"({n} of {case_count}). "
        "'Exercised' counts cases where the fake's output actually differed from a faithful one.",
        "",
        "| Model behavior | Exercised | Accepted | Rejected -> fallback | Planted hallucinations delivered | Expected |",
        "|---|---|---|---|---|---|",
    ]
    for name, r in guard["behaviors"].items():
        planted = r.get("planted_hallucinations_delivered", 0) if name in PLANTED_MARKERS else "n/a"
        lines.append(
            f"| `{name}` | {r.get('exercised', 0)} | {r.get('accepted', 0)} | "
            f"{r.get('fell_back', 0)} | {planted} | {expect[name]} |"
        )
    return lines


def render(
    det: dict, guard: dict, adv: dict, contract: dict, shadow: dict,
    failures: list[str], instantly: dict | None = None, gate: dict | None = None,
    public: dict | None = None, public_guard: dict | None = None, rewrite: dict | None = None,
    rag: dict | None = None, desks: dict | None = None,
) -> str:
    L = ["# Eval results", "",
         "Generated by `python evals/run_evals.py`. Section 1 fixtures are synthetic "
         "(see `evals/detection/fixtures.py`), so those numbers show correctness "
         "and regression safety, not real-world accuracy. Section 5 is a frozen "
         "public-DNS snapshot and is not added to section 1.", "",
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
    L += ["", "## 2. Guardrail", ""]
    L += _guard_table(guard, det["cases"])
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
    if desks:
        L += ["", "## 2d. Campaign Desk and Reply Desk", ""]
        L += [
            f"- Unhealthy sending status stalls: **{desks.get('unhealthy_stalls')}**",
            f"- Sending verdict with a stalled row rejected: **{desks.get('honesty_rejects_sending')}**",
            f"- Unread mail is attention: **{desks.get('unread_is_attention')}**",
            f"- Missing unread count stays unknown: **{desks.get('missing_count_unknown')}**",
            f"- Clear with unread mail rejected: **{desks.get('clear_rejected')}**",
            f"- Two reply pages joined: **{desks.get('pages_joined')}**",
            f"- Critical Finding holds the agent card: **{desks.get('handoff_holds')}**",
            f"- Clear act on a hold rejected: **{desks.get('handoff_clear_rejected')}**",
            "",
            "Counts are copied from Instantly. No reply rate is computed. "
            "The agent card does not pause or activate.",
            "",
        ]
    L += ["", "## 3. Schema contract", "",
          f"- schema_version: `{contract.get('schema_version')}` "
          f"(expected `{contract.get('expected_schema_version')}`)",
          f"- ok: **{contract.get('ok')}**", ""]
    L += ["", "## 4. Shadow corpus (not production accuracy)", "",
          f"- status: **{shadow.get('status')}** · cases: {shadow.get('cases', 0)}",
          f"- {shadow.get('note', '')}", ""]
    if public is not None:
        L += ["", "## 5. Public DNS corpus (not added to section 1)", "",
              "Frozen records in `evals/corpus/public_dns.json`, labels in `evals/corpus/labels.json`. "
              "A DKIM miss means the nine default selectors, not every selector on the internet.",
              "",
              f"- Cases: **{public['cases']}**; exact finding-set match: **{public['exact_match']}/{public['cases']}**",
              f"- Precision: **{public['precision']:.3f}**, recall: **{public['recall']:.3f}** "
              f"(TP {public['tp']}, FP {public['fp']}, FN {public['fn']})", ""]
        L += ["| Finding id | TP | FP | FN |", "|---|---|---|---|"]
        for k, v in public["per_id"].items():
            L.append(f"| `{k}` | {v.get('tp', 0)} | {v.get('fp', 0)} | {v.get('fn', 0)} |")
        if public["misses"]:
            L += ["", "Mismatches:"]
            for miss in public["misses"]:
                L.append(f"- `{miss['case']}` expected {miss['expected']} got {miss['got']}")
        L.append("")
    if public_guard is not None and public is not None:
        L += ["", "## 5b. Public-corpus guardrail", ""]
        L += _guard_table(public_guard, public["cases"])
        L.append("")
    if rewrite is not None:
        L += ["", "## 5c. Rewrite pairs (grounded teacher plans)", "",
              f"- Pairs: **{rewrite['pairs']}** (domains with findings: {rewrite['with_findings']})",
              f"- Teacher plans accepted: **{rewrite['teacher_accepted']}**",
              f"- Invented finding id rejected: **{rewrite['invented_id_rejected']}**",
              f"- Invented DNS record rejected: **{rewrite['invented_record_rejected']}**",
              "",
              "Pairs are in `evals/corpus/rewrite_pairs.jsonl`. They train the rewrite "
              "to stay inside the finding set. They do not create findings.",
              ""]
    if rag is not None:
        L += ["", "## 5d. Rewrite RAG (examples only, not a finder)", "",
              "Retrieved plans must be a subset of the current findings. "
              "This score is not added to section 1 or section 5.",
              "",
              f"- Plans in the index: **{rag['plans']}**",
              f"- Finding ids covered: **{rag['ids_covered']}/{rag['ids_shipped']}**",
              f"- Cases checked: **{rag['cases_checked']}**",
              f"- Index matches builder: **{not rag['drift']}**",
              f"- Unsafe examples: **{len(rag['unsafe'])}**",
              ""]
    return "\n".join(L)


def main() -> int:
    det = eval_detection()
    adv = eval_advisory_detection()
    guard = eval_guardrail()
    instantly = eval_instantly_rewrite()
    gate = eval_pre_launch_gate()
    desks = eval_desks()
    contract = eval_schema_contract()
    shadow = eval_shadow()
    public_cases = load_public_cases()
    public = _score_cases(public_cases)
    public_guard = eval_guardrail(public_cases)
    rewrite = eval_rewrite_pairs(public_cases)
    rag = eval_rag(public_cases)
    failures = check_expectations(
        det, guard, adv, contract, instantly, gate, public, public_guard, rewrite, rag, desks,
    )
    out = Path(__file__).resolve().parent
    md = render(
        det, guard, adv, contract, shadow, failures, instantly, gate,
        public, public_guard, rewrite, rag, desks,
    )
    (out / "RESULTS.md").write_text(md)
    print(md)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
