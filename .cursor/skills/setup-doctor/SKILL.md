---
name: setup-doctor
description: >-
  Route Setup Doctor email-auth diagnosis skills. Use when the user asks about
  SPF/DKIM/DMARC/MX setup, cold-email DNS, or types /setup-doctor. Do not invent
  DNS records or finding ids — only report engine output.
disable-model-invocation: true
---

# /setup-doctor

Setup Doctor diagnoses cold-email DNS (SPF, DKIM, DMARC, MX). **Findings come only from the engine.** Never invent missing records, selectors, or Instantly scores.

## Usage

```
/setup-doctor                 # this help
/diagnose <domain>            # full diagnosis
/spf <domain>                 # SPF-focused reading of /diagnose
/dkim <domain> [--selector s] # DKIM (pass real selectors; do not guess as missing)
/dmarc <domain>
/mx <domain>
/fix-plan <domain>           # re-run diagnose; present plan only
/instantly                    # warmup vs placement (unknown when data missing)
/eval-check                   # maintainers: pytest + evals + mutants
```

## Rules

1. Shell out to `python -m setup_doctor` or MCP tools `diagnose` / `compare_instantly`.
2. Do not re-implement SPF/DKIM logic in chat.
3. DNS outage ≠ absence — if the CLI exits 2 / resolver error, say so.
4. DKIM selectors cannot be listed from DNS; never claim DKIM is missing without saying selectors were tried.
5. Instantly missing scores → **unknown**, never healthy.
