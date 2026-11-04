---
name: pre-launch-gate
description: >-
  Dual-MCP Instantly pre-launch gate: Setup Doctor Findings first, then Instantly
  mismatches. Block campaign activate while critical/high Findings remain. Never
  invent DNS or treat missing Instantly data as healthy.
disable-model-invocation: true
---

# /pre-launch-gate

Thin orchestration only — call MCP/CLI. **No SPF/DKIM logic in this skill.**

Requires Setup Doctor MCP (hosted `/mcp` or local stdio) and ideally Instantly MCP.
See `docs/INSTANTLY_CONNECT.md`.

## Steps

1. **Preferred:** MCP tool `pre_launch_gate` (optional `domain`, `ctd_hosts`).
   Or CLI: `python -m setup_doctor --pre-launch-gate --json`

2. Fallbacks if gate tool unavailable:
   - MCP `instantly_ready` / CLI `--instantly-ready --json`
   - MCP `diagnose` with `include_instantly: true`

3. Optionally pull Instantly MCP account/vitals for operator context. Quote Instantly
   tool output; do not invent scores. If Instantly Deliverability Agent recommends
   pause, **quote it** — Setup Doctor explains DNS depth and does **not** auto-pause.

4. **Present in this order:**
   - `launch_verdict` / `allowed_to_activate` / `summary_spoken`
   - Setup Doctor `blocking_finding_ids` and findings — Findings first
   - Instantly mismatches / vitals disagreements
   - Anything `unknown` / `not_checked` — say so plainly

5. **Gate (hard rules):**
   - `allowed_to_activate` is true **only** when `launch_verdict == ready`
   - Critical Findings ⇒ blocked — **do not** call Instantly `activate_campaign`
   - Missing Instantly data ⇒ unknown — **not** ready
   - Leave activate to the human / Instantly MCP

## Do not

- Invent finding ids, DNS records, or Instantly scores.
- Soften `unknown` to healthy.
- Pause accounts, enable warmup, or activate campaigns via Setup Doctor (read-only).
- Reimplement SPF/DKIM checks in prose when tool JSON is available.
