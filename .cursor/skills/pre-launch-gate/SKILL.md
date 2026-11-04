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

1. **Setup Doctor readiness** (preferred single call):

   - MCP tool `instantly_ready` (optional `ctd_hosts`)
   - Or CLI: `python -m setup_doctor --instantly-ready --json`

2. If you only have one domain, also acceptable:

   - MCP `diagnose` with `include_instantly: true`
   - CLI: `python -m setup_doctor DOMAIN --with-instantly --json`

3. Optionally pull Instantly MCP account/vitals for operator context. Quote Instantly
   tool output; do not invent scores.

4. **Present in this order:**
   - Setup Doctor `findings` (ids, severity, fix) — Findings first
   - Instantly warmup/placement mismatches and vitals disagree notes
   - Anything `unknown` / `not_checked` — say so plainly

5. **Gate:**
   - If any Finding severity is `critical` or `high` → **do not** call Instantly
     `activate_campaign` (or equivalent). Tell the user to fix DNS first.
   - If Instantly data is missing → verdict is incomplete / unknown — **not** ready.
   - Only when Findings are clear of auth blockers and Instantly shows no mismatch
     should you say launch looks clear — still leave activate to the human/Instantly agent.

## Do not

- Invent finding ids, DNS records, or Instantly scores.
- Soften `unknown` to healthy.
- Pause accounts, enable warmup, or activate campaigns via Setup Doctor (read-only).
- Reimplement SPF/DKIM checks in prose when tool JSON is available.
