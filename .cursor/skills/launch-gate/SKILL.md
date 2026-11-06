---
name: launch-gate
description: >-
  Decide whether an Instantly campaign may activate, using Setup Doctor
  Findings first. Use when the user asks to launch, activate, go live, or pass
  a pre-launch gate. allowed_to_activate is true only when launch_verdict is
  ready. Never activates or pauses campaigns.
---

# Launch Gate

Thin orchestration only. Call MCP or CLI. No SPF/DKIM logic in this skill.

Requires Setup Doctor MCP (hosted `/mcp` or local stdio) and `INSTANTLY_API_KEY` or `X-Instantly-Api-Key`. See `docs/INSTANTLY_CONNECT.md`.

## Run

Prefer MCP tool `pre_launch_gate` (optional `domain`, `ctd_hosts`, `include_rich_signals`).

Or:

```bash
python -m setup_doctor --pre-launch-gate --json
python -m setup_doctor DOMAIN --pre-launch-gate --json
python -m setup_doctor --pre-launch-gate --ctd-host track.example.com --json
```

CLI exit code 3 means the gate ran and `allowed_to_activate` is false. That is a block, not a crash. Exit code 2, `instantly_http`, or `resolver_error` means no gate was produced. A resolver error is an outage, not missing records.

If `pre_launch_gate` is unavailable, fall back in this order and say which one you used:

1. MCP `instantly_ready` or `python -m setup_doctor --instantly-ready --json`
2. MCP `diagnose` with `include_instantly: true` for one named domain

Quote Instantly tool output. If Instantly's Deliverability Agent recommends a pause, quote it. Do not pause or activate.

## Present

In this order:

1. `launch_verdict`, `allowed_to_activate`, `summary_spoken`
2. `blocking_finding_ids` and the Findings behind them — Findings first
3. `instantly_mismatches` and `vitals_disagreements`
4. Anything `unknown` or in `not_checked` — say so plainly

## Gate

- `allowed_to_activate` is true only when `launch_verdict` is `ready`
- Critical or high Findings block activate. Do not call Instantly `activate_campaign`
- Missing Instantly data is unknown, not ready
- Leave activate to the human in Instantly

## Hand off

If blocked, name `blocking_finding_ids` and the domains they belong to, then hand those domains to Fix Coach. After DNS changes, re-run this gate. A ready verdict still means a person activates in Instantly. This agent does not.

## Do not

- Invent finding ids, DNS records, or Instantly scores
- Soften `unknown` to healthy
- Pause accounts, enable warmup, or activate campaigns
- Reimplement SPF/DKIM checks when tool JSON is available
