"""Run the full eval suite and write evals/RESULTS.md + evals/results.json.

    python evals/run_evals.py          # exit code 0 only if every expectation holds

Two questions are answered separately:
  1. Detection: do the deterministic checks find exactly the planted problems?
  2. Guardrail: when the LLM misbehaves, does bad text ever reach the user?

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

from evals.fakes import BEHAVIORS, PLANTED_MARKERS, faithful  # noqa: E402
from evals.fixtures import CASES  # noqa: E402
from setup_doctor import FixtureResolver, LLMExplainer, diagnose, run_checks, verify_grounding  # noqa: E402
from setup_doctor.explain import PROMPT  # noqa: E402


def eval_detection() -> dict:
    tp = fp = fn = 0
    exact = 0
    per_id: dict[str, Counter] = defaultdict(Counter)
    misses = []
    for c in CASES:
        got = sorted(f.id for f in run_checks(c["domain"], FixtureResolver(c["records"])))
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
        "cases": len(CASES), "exact_match": exact,
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "tp": tp, "fp": fp, "fn": fn,
        "per_id": {k: dict(v) for k, v in sorted(per_id.items())},
        "misses": misses,
    }


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
                r["skipped_no_findings"] += 1  # nothing to explain; model never called
                continue
            r["with_findings"] += 1
            r["with_severe"] += _severe(findings)
            # Was the model's output actually different from a faithful one in this case?
            try:
                differs = fn(_prompt_for(findings)) != faithful(_prompt_for(findings))
            except Exception:
                differs = True
            r["exercised"] += differs
            state = diagnose(c["domain"], resolver, LLMExplainer(fn))
            r["fell_back" if state["used_fallback"] else "accepted"] += 1
            if marker and marker in state["explanation"]:
                r["planted_hallucinations_delivered"] += 1  # independent of the verifier
            if verify_grounding(state["explanation"], state["findings"]):
                r["delivered_failing_verifier"] += 1        # self-consistency only
        rows[name] = dict(r)
    return {"behaviors": rows}


def check_expectations(det: dict, guard: dict) -> list[str]:
    """Machine-checked claims. Anything listed here makes the run fail."""
    bad = []
    if det["exact_match"] != det["cases"]:
        bad.append(f"detection: {det['cases'] - det['exact_match']} case(s) mismatched")
    b = guard["behaviors"]
    n = b["faithful"]["with_findings"]
    if b["faithful"].get("accepted", 0) != n:
        bad.append("faithful drafts should all be accepted")
    for name in ("hallucinated_finding", "hallucinated_record", "raises", "empty"):
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
    return bad


def render(det: dict, guard: dict, failures: list[str]) -> str:
    L = ["# Eval results", "",
         "Generated by `python evals/run_evals.py`. Fixtures are synthetic (see fixtures.py), "
         "so detection numbers show correctness and regression safety, not real-world accuracy.", "",
         f"**Status: {'PASS' if not failures else 'FAIL'}**"]
    L += [f"- {f}" for f in failures]
    L += ["", "## 1. Detection (deterministic checks vs planted ground truth)", "",
          f"- Cases: **{det['cases']}**; exact finding-set match: **{det['exact_match']}/{det['cases']}**",
          f"- Precision: **{det['precision']:.3f}**, recall: **{det['recall']:.3f}** "
          f"(TP {det['tp']}, FP {det['fp']}, FN {det['fn']})", ""]
    L += ["| Finding id | TP | FP | FN |", "|---|---|---|---|"]
    for k, v in det["per_id"].items():
        L.append(f"| `{k}` | {v.get('tp', 0)} | {v.get('fp', 0)} | {v.get('fn', 0)} |")
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
          "Numeric grounding covers allow-listed claim shapes (lookup counts, pct=, "
          "\"N% of mail\", limit is N) against finding titles/evidence only.", ""]
    return "\n".join(L)


def main() -> int:
    det, guard = eval_detection(), eval_guardrail()
    failures = check_expectations(det, guard)
    out = Path(__file__).resolve().parent
    (out / "results.json").write_text(json.dumps({"detection": det, "guardrail": guard, "failures": failures}, indent=2))
    md = render(det, guard, failures)
    (out / "RESULTS.md").write_text(md)
    print(md)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
