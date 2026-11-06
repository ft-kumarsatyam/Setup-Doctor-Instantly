# Setup Doctor for Instantly

A short brief for the Instantly team. Read this before the README.

**Instantly owns the mailbox. Setup Doctor owns the sending domain.**

Instantly already answers: is this account connected, warming, landing, and allowed to send? Setup Doctor answers the question that still sits in front of activate: will receivers trust mail from this domain?

The two products stay on different sides of the same launch.

| Instantly already owns | Setup Doctor adds |
|---|---|
| Connected accounts and mailboxes | A DNS doctor for each sending domain |
| Warmup scores | SPF, DKIM, DMARC, and MX as labeled Findings, with severity and a fix order |
| Inbox placement tests | A check of whether warmup and placement tell the same story |
| Four vitals booleans (MX, SPF, DKIM, DMARC exist) | The same records read in depth: multiple SPF, `+all`, too many lookups, weak or missing DKIM, DMARC policy, null MX |
| Custom tracking domain status | Correlation of those vitals with the Findings (`agree`, `disagree`, or `unknown`) |
| Campaigns, send status, analytics counts | Campaign Desk: a read-only “why is this stalled?” view |
| Unibox and the CRM (lead, interest, AI interest) | Reply Desk quotes those fields from received threads. It does not relabel, reply, or move a lead |
| Sequences and campaign automations | A signed provisioning webhook: diagnose the domains in the payload, store the result, optional Slack line |
| Deliverability Agent (pause and act) | A handoff card (`hold`, `review`, `clear`, `unknown`). Setup Doctor does not pause or activate |
| Campaign activate | Launch Gate: `allowed_to_activate` is true only when `launch_verdict` is `ready` |

Vitals are a pass/fail light. A light can be green while SPF is `+all`, DKIM is a weak key, or DMARC is `p=none`. Setup Doctor is the checklist behind that light.

## Seven jobs Instantly’s product does not package

1. **Domain Doctor.** One sending domain in, Findings out. Same DNS input, same Findings. An optional model may rewrite the wording. A verifier drops invented finding ids, record strings, and numbers. If the rewrite fails, the template is what the user sees.

2. **Launch Gate.** Critical and high Findings block activate. Missing Instantly scores stay `unknown`. The gate never calls Instantly’s activate or pause APIs. A person still launches inside Instantly.

3. **Workspace Ready.** Every unique sender domain on the Instantly account (or across a workspace group) is diagnosed, then lined up with Instantly vitals. Agencies can export a client handoff.

4. **Fix Coach.** Paste-ready DNS steps for Cloudflare, Namecheap, GoDaddy, or Google Domains. The record text comes from the Findings. The tool does not invent TXT, CNAME, or MX strings.

5. **Warmup versus placement.** When both numbers exist, the verdict is `aligned`, `mismatch`, or `unknown`. A strong warmup with a weak inbox rate is called a mismatch. A missing score is called unknown.

6. **Desks beside the agent.** Campaign Desk explains send versus stall from Instantly’s own status codes, including lead and bounce counts. Reply Desk shows the unread count and recent Unibox threads: lead, subject, interest status, AI interest value, and whether the message is an auto-reply. Both are read-only. The Deliverability Agent card tells Instantly’s agent to hold, review, or clear. It does not press the button.

7. **Provisioning webhook.** `POST /hooks/instantly` takes a signed payload (account created, domain list, or a mailbox email), diagnoses each sender domain, stores the last result, and attaches the agent handoff. Set `SETUP_DOCTOR_INSTANTLY_HOOK_SECRET`. The signature is `X-Setup-Doctor-Signature` (`t=<unix>,v1=<hmac-sha256>`), valid for five minutes. Read the stored row with `GET /hooks/instantly/last/{domain}`. If `SETUP_DOCTOR_SLACK_WEBHOOK_URL` is set, the hook posts one Slack line. An unset Slack URL is `not_checked`. The hook does not pause, activate, or change a CRM status.

Optional, and off unless asked: BIMI, MTA-STS, and TLS-RPT. These are advisory. They are not part of the launch block.

## What we leave to Instantly

Setup Doctor is read-only on the Instantly API v2. Instantly still owns the CRM, sequences, lead-status changes, replies, warmup enablement, and campaign activate. The webhook and the Slack line are notifications around a DNS diagnosis. They are not an Instantly automation that writes back.

If the Instantly key is missing, or the workspace has no scores, the report says **unknown**. It does not paint a green “healthy.”

## How a teammate would use it

```text
Instantly accounts
    → Workspace Ready (which domains are on the account)
    → Domain Doctor (Findings on each custom domain)
    → Fix Coach (records to paste at the registrar)
    → Launch Gate (allowed_to_activate?)
    → a person activates in Instantly
```

Connect both MCPs in one chat: Instantly at `mcp.instantly.ai`, Setup Doctor at `/mcp`. Tools: `diagnose`, `compare_instantly`, `instantly_ready`, `pre_launch_gate`, `campaign_desk`, `reply_desk`. Connect steps: [INSTANTLY_CONNECT.md](INSTANTLY_CONNECT.md).

## One sentence

Instantly tells you the mailbox can send. Setup Doctor tells you the domain’s DNS will let that mail be trusted, and it holds the launch when the Findings say so.
