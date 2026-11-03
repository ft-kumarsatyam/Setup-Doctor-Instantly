---
name: fix-plan
description: >-
  Re-run Setup Doctor and present only the prioritized fix plan. Use for /fix-plan.
  Do not invent steps; use engine report/explanation only.
disable-model-invocation: true
---

# /fix-plan

```bash
python -m setup_doctor DOMAIN --json
```

Print the `explanation` field (or the Fix plan section of `report`). Keep finding ids in brackets. Do not add, remove, or re-order beyond what the engine returned.
