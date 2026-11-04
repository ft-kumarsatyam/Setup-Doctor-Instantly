---
name: instantly
description: >-
  Instantly warmup vs placement, domain-scoped diagnose signals, and workspace
  readiness (read-only). Use for /instantly. Missing scores are unknown —
  never report healthy when data is absent.
disable-model-invocation: true
---

# /instantly

Requires `INSTANTLY_API_KEY` (scopes: accounts:read, inbox_placement_tests:read,
inbox_placement_analytics:read; readiness may also need inbox_placement_reports:read
and ai_agents:read).

```bash
# Workspace-wide warmup vs placement
python -m setup_doctor --instantly-compare
python -m setup_doctor --instantly-compare --json

# Domain-filtered compare
python -m setup_doctor example.com --instantly-compare --json

# Attach Instantly signals to a DNS diagnosis (auto-prepends --esp-pack instantly)
python -m setup_doctor DOMAIN --with-instantly --json

# Workspace readiness: diagnose Instantly sender domains + vitals/CTD/placement signals
python -m setup_doctor --instantly-ready
python -m setup_doctor --instantly-ready --ctd-host track.example.com --json

# Bulk-diagnose unique Instantly sender domains
python -m setup_doctor --from-instantly --json
```

MCP: `compare_instantly`, `instantly_ready`, and `diagnose` with `include_instantly`.

HTTP: `GET|POST /instantly/compare`, `POST /instantly/ready`,
`POST /diagnose` with `include_instantly: true`.

When presenting: quote `verdict` and `note` from the engine. **unknown** means
data missing — do not soften to healthy. Instantly vitals/CTD are signals only;
they never invent Setup Doctor Findings.

Pre-launch with Instantly MCP: use `/pre-launch-gate` (Findings first; do not
activate campaigns while critical/high Findings remain). Connect pack:
`docs/INSTANTLY_CONNECT.md`.
