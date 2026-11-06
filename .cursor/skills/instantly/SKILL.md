---
name: instantly
description: >-
  Instantly warmup vs placement compare (read-only). Use for /instantly.
  Missing scores are unknown — never report healthy when data is absent.
  Workspace readiness is Workspace Ready. Launch permission is Launch Gate.
disable-model-invocation: true
---

# /instantly

Warmup versus inbox placement only. Workspace readiness is the Workspace Ready skill (`.cursor/skills/workspace-ready/SKILL.md`). Whether a campaign may activate is the Launch Gate skill (`.cursor/skills/launch-gate/SKILL.md`).

Requires `INSTANTLY_API_KEY` (scopes: accounts:read, inbox_placement_tests:read, inbox_placement_analytics:read).

```bash
python -m setup_doctor --instantly-compare
python -m setup_doctor --instantly-compare --json
python -m setup_doctor example.com --instantly-compare --json
```

MCP: `compare_instantly` (optional `domain`).

Quote `verdict` and `note` from the engine. **unknown** means data missing — do not soften to healthy. Instantly vitals never invent Setup Doctor Findings.
