"""Prove the evals can fail.

Copies the project to a temp directory, applies one deliberate bug at a time, and
runs the eval suite. Every mutant must make the suite fail (exit code != 0);
a mutant that survives means the evals have a blind spot.

    python evals/mutation_check.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

MUTANTS = [
    ("SPF lookup limit off by one", "src/setup_doctor/checks/engine.py",
     "if lookups > 10 or loop:", "if lookups > 11 or loop:"),
    ("SPF 'bare all' no longer treated as +all", "src/setup_doctor/dns/spf.py",
     'return t[0] if t[0] in _QUALIFIERS else "+"', 'return t[0] if t[0] in _QUALIFIERS else "~"'),
    ("redirect no longer exempts SPF_NO_ALL", "src/setup_doctor/checks/engine.py",
     "elif q is None and not spf.has_redirect(record):", "elif q is None:"),
    ("DMARC p=none no longer flagged", "src/setup_doctor/checks/engine.py",
     'if policy == "none":', 'if policy == "never":'),
    ("DKIM weak key threshold raised to ignore 1024-bit", "src/setup_doctor/checks/engine.py",
     "if bits is not None and bits < 2048:", "if bits is not None and bits < 1024:"),
    ("SPF void lookup limit off by one", "src/setup_doctor/checks/engine.py",
     "if voids > 2:", "if voids > 3:"),
    ("DMARC sp=none under enforce no longer flagged", "src/setup_doctor/checks/engine.py",
     'if sp == "none" and policy in ("quarantine", "reject"):',
     'if sp == "never" and policy in ("quarantine", "reject"):'),
    ("DMARC strict alignment no longer flagged", "src/setup_doctor/checks/engine.py",
     "if strict_bits:", "if False:"),
    ("verifier ignores unknown finding ids", "src/setup_doctor/explain/explainer.py",
     'violations += [f"unknown finding id [{c}]" for c in sorted(returned_set - ids)]',
     "violations += []"),
    ("verifier ignores ungrounded DNS records", "src/setup_doctor/explain/explainer.py",
     "if _RECORD_RE.search(code) and code.lower() not in allowed:", "if False:"),
    ("verifier ignores dropped findings", "src/setup_doctor/explain/explainer.py",
     "for missing in sorted(ids - returned_set):", "for missing in []:"),
    ("verifier ignores ungrounded numeric claims", "src/setup_doctor/explain/explainer.py",
     "if n not in allowed_nums:", "if False:"),
    ("graph never falls back", "src/setup_doctor/pipeline/graph.py",
     'return "fallback" if state.get("violations") else "render"', 'return "render"'),
    ("BIMI missing never flagged", "src/setup_doctor/checks/engine.py",
     'return [Finding(\n        "BIMI_MISSING", "info",',
     'return []  # mutant\n    return [Finding(\n        "BIMI_MISSING", "info",'),
    ("MTA-STS missing never flagged", "src/setup_doctor/checks/engine.py",
     'return [Finding(\n        "MTA_STS_MISSING", "info",',
     'return []  # mutant\n    return [Finding(\n        "MTA_STS_MISSING", "info",'),
    ("instantly rewrite skips grounding verify", "src/setup_doctor/explain/instantly_rewrite.py",
     "violations = verify_instantly_rewrite(items, comparisons)",
     "violations = []  # mutant"),
    ("pre_launch_gate ignores critical Findings", "src/setup_doctor/integrations/instantly/launch.py",
     "if blocking:\n        return \"blocked\"",
     "if False:  # mutant\n        return \"blocked\""),
]


def run_suite(project: Path) -> int:
    proc = subprocess.run([sys.executable, "evals/run_evals.py"], cwd=project,
                          capture_output=True, text=True)
    return proc.returncode


def main() -> int:
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "baseline"
        shutil.copytree(
            ROOT, base,
            ignore=shutil.ignore_patterns(
                "__pycache__", ".pytest_cache", ".venv", "venv", ".git", ".cursor",
            ),
        )
        if run_suite(base) != 0:
            print("Baseline suite already fails; fix that first.")
            print(subprocess.run(
                [sys.executable, "evals/run_evals.py"], cwd=base,
                capture_output=True, text=True,
            ).stdout[-2000:])
            return 2
        print("baseline: PASS\n")
        for i, (label, rel, old, new) in enumerate(MUTANTS):
            work = Path(tmp) / f"mutant{i}"
            shutil.copytree(base, work)
            target = work / rel
            src = target.read_text()
            if old not in src:
                print(f"[?] {label}: pattern not found in {rel} (mutant is stale)")
                survivors.append(label)
                continue
            target.write_text(src.replace(old, new, 1))
            killed = run_suite(work) != 0
            print(f"[{'killed' if killed else 'SURVIVED'}] {label}")
            if not killed:
                survivors.append(label)
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
