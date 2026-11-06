---
name: reply-desk
description: >-
  Show Instantly unread mail and the latest received threads. Use when the
  user asks who replied, what is unread, or what the Unibox is holding.
  Read-only. Does not reply, forward, or rename interest statuses.
---

# Reply Desk

Read-only. Call MCP or CLI. Do not reply, forward, or mark mail done.

Requires `INSTANTLY_API_KEY` or `X-Instantly-Api-Key`. Scopes include `emails:read`. The email list is limited to 20 requests per minute by Instantly. This skill reads up to five pages and stops if Instantly repeats a cursor. `email_list_capped` means more threads exist.

## Run

Prefer MCP tool `reply_desk` (optional `campaign_id`).

Or:

```bash
python -m setup_doctor --reply-desk --json
python -m setup_doctor --reply-desk --campaign-id CAMPAIGN_ID --json
```

Exit code 3 means `attention` or `unknown`. Exit code 0 means `clear` (unread count is 0). Exit code 2 means Instantly failed and no report was produced.

## Present

1. `verdict`, `unread_count`, and `summary_spoken`
2. Each thread: lead, subject, whether it is unread, whether Instantly marked it an auto-reply, and the preview
3. `i_status` as the number Instantly sent. Do not translate that number into a label
4. `not_checked` stays unchecked. `domain_blocked` is true only for a sending domain the caller already marked. Null is not clean.

The unread count is the whole workspace. When a campaign id was passed, say the thread list is filtered and the count is not.

A missing unread count is unknown. Do not call the inbox clear.

## Do not

- Send, reply, or forward
- Invent interest labels from `i_status` or `ai_interest_value`
- Treat a missing count as zero
