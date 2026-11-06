---
name: setup-doctor
description: >-
  Route Setup Doctor email-auth skills. Use when the user asks about
  SPF/DKIM/DMARC/MX setup, cold-email DNS, Instantly launch readiness, or types
  /setup-doctor. Do not invent DNS records or finding ids — only report engine
  output.
disable-model-invocation: true
---

# /setup-doctor

Setup Doctor diagnoses cold-email DNS (SPF, DKIM, DMARC, MX). **Findings come only from the engine.** Never invent missing records, selectors, or Instantly scores.

## User agents

These load on their own when the question matches. Follow that skill; do not invent a second procedure.

| Agent | Use when |
| --- | --- |
| Domain Doctor | One sending domain: what is wrong in DNS |
| Fix Coach | Registrar steps (Cloudflare, Namecheap, GoDaddy, Google Domains) |
| Workspace Ready | Instantly sender domains, agency handoff, all workspaces |
| Launch Gate | May this campaign activate? |
| Campaign Desk | Why is an Instantly campaign stalled or sending? |
| Reply Desk | Who replied, and what is still unread? |

Warmup versus placement compare stays on `/instantly`. Why a campaign is or is not sending is Campaign Desk. Unread replies are Reply Desk.

## Slash commands

```
/setup-doctor                 # this help
/diagnose <domain>            # Domain Doctor
/spf <domain>                 # SPF findings only
/dkim <domain> [--selector s] # DKIM (pass real selectors; do not guess as missing)
/dmarc <domain>
/mx <domain>
/fix-plan <domain>            # Fix Coach
/instantly                    # warmup vs placement only
/pre-launch-gate              # Launch Gate
/campaign-desk                # Campaign Desk
/reply-desk                   # Reply Desk
/eval-check                   # maintainers: pytest + evals + mutants
```

## Rules

1. Shell out to `python -m setup_doctor` or MCP tools `diagnose`, `compare_instantly`, `instantly_ready`, `pre_launch_gate`, `campaign_desk`, `reply_desk`.
2. Do not re-implement SPF/DKIM logic in chat.
3. DNS outage ≠ absence — if the CLI exits 2 / resolver error, say so. Launch Gate exit code 3 means blocked, not a crash.
4. DKIM selectors cannot be listed from DNS; never claim DKIM is missing without saying selectors were tried.
5. Instantly missing scores → **unknown**, never healthy. Instantly vitals never invent Findings.
6. `allowed_to_activate` is true only when `launch_verdict` is `ready`. Do not activate or pause campaigns.
