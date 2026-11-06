---
name: domain-doctor
description: >-
  Diagnose one sending domain for cold-email DNS (SPF, DKIM, DMARC, MX) by
  running Setup Doctor. Use when the user gives a domain, asks if email
  authentication or DNS is healthy, or asks what is wrong before sending.
  Presents only engine findings. Hands record fixes to Fix Coach and Instantly
  launch questions to Launch Gate.
---

# Domain Doctor

One sending domain. Findings come only from Setup Doctor. Do not reimplement SPF, DKIM, DMARC, or MX checks in chat.

## Run

Prefer MCP tool `diagnose` (`domain` required; optional `dkim_selectors`, `esp_packs`, `include_advisory`, `include_instantly`).

Or from the repo root (or with `setup-doctor` on PATH):

```bash
python -m setup_doctor DOMAIN --json
# optional, only when the user asked:
python -m setup_doctor DOMAIN --json --advisory
python -m setup_doctor DOMAIN --json --esp-pack PACK --dkim-selector SELECTOR
python -m setup_doctor DOMAIN --json --with-instantly
```

`--esp-pack` must be a pack the CLI accepts. `--with-instantly` needs `INSTANTLY_API_KEY` (or the MCP Instantly header). It attaches signals; it does not create Findings.

## Present

Use only the JSON (`schema_version` should be `1.0`):

1. One-line verdict from the engine report (healthy, issues found, or not diagnosed).
2. Each finding as returned: id, severity, and the engine fix text. Do not add, drop, or re-rank ids.
3. What was not checked. DKIM selectors cannot be listed from DNS. If the user did not pass `--dkim-selector` or `--esp-pack`, say which selectors were tried and that a custom selector can still exist. If `not_checked` or Instantly data is missing, say **unknown**.

Exit code 2, MCP `resolver_error`, or `NXDOMAIN` is an outage or a missing domain. Say that. Do not invent `SPF_MISSING` or any other finding.

## Hand off

- Any finding with a fix → Fix Coach (ask the registrar if they have not named one).
- They use Instantly and ask whether they can send or activate → Launch Gate.
- Workspace-wide Instantly accounts, not one domain → Workspace Ready.
