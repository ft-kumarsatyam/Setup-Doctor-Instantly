---
name: workspace-ready
description: >-
  Check an Instantly workspace for sender-domain readiness with Setup Doctor.
  Use when the user asks about Instantly accounts, sender domains, workspace
  readiness, a client handoff, or all workspaces. Missing Instantly scores stay
  unknown. Warmup-versus-placement compare stays on /instantly. Launch
  permission stays on Launch Gate.
---

# Workspace Ready

Read-only Instantly sender domains. Needs `INSTANTLY_API_KEY` (or the MCP `X-Instantly-Api-Key` header). Scopes: accounts:read; rich signals may also need inbox_placement_reports:read and ai_agents:read. `--all-workspaces` also needs workspaces:read and group access.

Do not reimplement DNS checks. Do not pause accounts, enable warmup, or activate campaigns.

## Run

Prefer MCP tool `instantly_ready` (optional `ctd_hosts`, `include_rich_signals`).

Or:

```bash
python -m setup_doctor --instantly-ready --json
```

Only when the user asks:

```bash
python -m setup_doctor --instantly-ready --ctd-host track.example.com --json
python -m setup_doctor --instantly-ready --agency-export
python -m setup_doctor --instantly-ready --all-workspaces --json
python -m setup_doctor --from-instantly --json
```

`--agency-export` is the white-label client handoff. Do not add `--json` on that command; JSON replaces the agency markdown. `--from-instantly` bulk-diagnoses unique sender domains. It is not the readiness report.

Warmup score versus inbox placement is MCP `compare_instantly` or `/instantly`, not this skill.

## Present

Quote `launch_verdict` and `summary_spoken`. Then each sender domain's verdict from the report. **unknown** and `not_checked` stay unknown. Do not call missing scores healthy. Instantly vitals never become Findings. Findings in the report are Setup Doctor DNS findings only.

Exit code 2, `instantly_http`, or `resolver_error` means the report was not produced. Say that. A resolver error is an outage, not missing records.

## Hand off

- One blocked domain needs a deeper DNS read → Domain Doctor.
- They want registrar steps → Fix Coach.
- They ask whether they can launch or activate → Launch Gate.
