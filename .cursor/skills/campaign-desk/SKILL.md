---
name: campaign-desk
description: >-
  Explain why Instantly campaigns are sending or stalled. Use when the user
  asks why a campaign is not sending, is slow, is paused by Instantly, or
  wants campaign analytics counts. Read-only. Does not activate or pause.
---

# Campaign Desk

Read-only. Call MCP or CLI. Do not activate or pause campaigns. Do not invent reply rates or health scores.

Requires `INSTANTLY_API_KEY` or `X-Instantly-Api-Key`. Scopes include `campaigns:read`.

## Run

Prefer MCP tool `campaign_desk` (optional `campaign_id`).

Or:

```bash
python -m setup_doctor --campaign-desk --json
python -m setup_doctor --campaign-desk --campaign-id CAMPAIGN_ID --json
```

Exit code 3 means the desk ran and the verdict is `stalled` or `unknown`. That is a stall, not a crash. Exit code 2 means Instantly failed and no report was produced. Exit code 0 is `sending` or `idle` (no campaigns, or only parked ones).

## Present

1. `verdict` and `summary_spoken`
2. Each campaign's `verdict`, sending-status code, and Instantly `sending_status_message` when present
3. Counts only as returned: unique replies, bounced leads, emails sent
4. Anything in `not_checked` — say it was not read

`unknown` means Instantly omitted the code or the request failed for that campaign. Do not call that healthy or sending.

Parked means the campaign record is Draft, Paused, or Completed. A paused campaign in the list is parked. Ask for `--campaign-id` when you need that campaign's sending-status code.

## Do not

- Activate, pause, or edit the campaign
- Compute a reply rate or a 0–100 score
- Treat a missing analytics count as zero
