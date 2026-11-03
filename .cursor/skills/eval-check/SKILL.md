---
name: eval-check
description: >-
  Maintainer skill: run Setup Doctor pytest, detection/guardrail evals, and mutation check.
  Use for /eval-check. Never weaken fixtures or mutants to get green.
disable-model-invocation: true
---

# /eval-check

From repo root:

```bash
python -m pytest -q
python evals/run_evals.py
python evals/mutation_check.py
```

Report exit codes and summarize `evals/RESULTS.md`. Do not edit expected labels or mutants to pass.
