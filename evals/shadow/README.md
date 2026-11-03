# Shadow corpus

Optional real-domain diagnoses (hashed domain labels only in RESULTS).

- Never merge shadow precision/recall into the synthetic detection score in README.
- Opt-in: place `shadow_cases.json` here (gitignored patterns welcome) with shape:

```json
[
  {"domain_hash": "abc…", "expected_ids": ["SPF_MISSING"], "note": "manual label"}
]
```

CI does not require live DNS. `evals/run_evals.py` reports shadow as **skipped** when no corpus file is present.
