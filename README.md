# Setup Doctor

DNS doctor for Instantly workspaces. Instantly tells you whether the **mailbox** can send. Setup Doctor tells you whether the **sending domain** will be trusted — SPF, DKIM, DMARC, and MX — and holds the launch when those records are wrong.

Read the short brief first: **[docs/FOR_INSTANTLY.md](docs/FOR_INSTANTLY.md)**.

```
Instantly accounts → Workspace Ready → Domain Doctor → Fix Coach → Launch Gate
                                                                      ↓
                                                         a person activates in Instantly
```

Findings come from deterministic checks. An optional model only rewrites them. A verifier rejects invented finding ids, DNS records, and allow-listed numbers. A failed rewrite falls back to the template.

```
check → explain → verify → render
                 ↘ fallback → render
```

CLI, HTTP API, MCP, and Cursor skills share one contract: `DiagnosisResult` (`schema_version` **1.0**).

## What Instantly owns, and what this adds

| Instantly | Setup Doctor |
|---|---|
| Accounts, warmup, inbox placement, tracking domains | Deep DNS Findings and a fix order |
| Four vitals booleans (the record exists) | Why the record is wrong: `+all`, lookup limits, weak DKIM, DMARC policy, null MX |
| Campaign activate and the Deliverability Agent | Launch Gate (`allowed_to_activate`) and a read-only agent handoff card |
| Unibox, CRM fields, campaign analytics | Reply Desk and Campaign Desk quote lead, interest, and send counts. They do not write the CRM |
| Sequences and in-product automations | Signed provisioning webhook plus an optional Slack line |

Instantly vitals never become Findings. Missing scores and tests stay **unknown**. Setup Doctor does not pause accounts, enable warmup, or activate campaigns.

Partner copy: [docs/MARKETPLACE.md](docs/MARKETPLACE.md)

## Jobs

| Job | What it answers | Command |
|---|---|---|
| Domain Doctor | What is wrong on this sending domain? | `python -m setup_doctor yourdomain.com` |
| Fix Coach | Which records do I paste at the registrar? | `python -m setup_doctor yourdomain.com --fix-packet cloudflare` |
| Workspace Ready | Are this account’s sender domains ready? | `python -m setup_doctor --instantly-ready` |
| Launch Gate | May this campaign activate? | `python -m setup_doctor --pre-launch-gate` |
| Warmup vs placement | Do warmup and inbox rate agree? | `python -m setup_doctor --instantly-compare` |
| Campaign Desk | Why is this campaign stalled? | `python -m setup_doctor --campaign-desk` |
| Reply Desk | Who replied, and what is the lead’s interest? | `python -m setup_doctor --reply-desk` |
| Provisioning webhook | A new account or domain list just arrived — diagnose it | `POST /hooks/instantly` |

Offline, with no API key: `python -m setup_doctor mess.test --records examples/mess.json`. `--share-demo` shows the vitals gap with no key: vitals can all pass while launch stays blocked, and a scripted model that invents a score or a finding is rejected.

## Run

```bash
pip install -e ".[dev]"

python -m setup_doctor mess.test --records examples/mess.json
python -m setup_doctor yourdomain.com
python -m setup_doctor yourdomain.com --llm   # ANTHROPIC_API_KEY + SETUP_DOCTOR_MODEL
python -m setup_doctor yourdomain.com --advisory --esp-pack google --json
python -m setup_doctor --bulk domains.csv

python -m pytest -q
python evals/run_evals.py
python evals/mutation_check.py
```

Instantly calls are read-only API v2 and need `INSTANTLY_API_KEY` (or the `X-Instantly-Api-Key` header). Scopes: `accounts:read`, `inbox_placement_tests:read`, `inbox_placement_analytics:read`. Readiness may also need `inbox_placement_reports:read` and `ai_agents:read`. Campaign Desk needs `campaigns:read`. Reply Desk needs `emails:read`. `--all-workspaces` needs `workspaces:read`.

```bash
python -m setup_doctor --instantly-compare
python -m setup_doctor yourdomain.com --with-instantly --json
python -m setup_doctor --instantly-ready --ctd-host track.example.com
python -m setup_doctor --instantly-ready --agency-export
python -m setup_doctor --instantly-ready --all-workspaces --json
python -m setup_doctor --share-demo
python -m setup_doctor --pre-launch-gate --json
python -m setup_doctor --campaign-desk --json
python -m setup_doctor --reply-desk --json
python -m setup_doctor mess.test --records examples/mess.json --fix-packet cloudflare
python -m setup_doctor --from-instantly --json
```

`--esp-pack` and `--dkim-selector` matter because DNS cannot list DKIM selectors. Advisory checks (BIMI, MTA-STS, TLS-RPT) stay off unless you pass `--advisory`.

## CRM, webhooks, and Slack

Instantly keeps the CRM and the sequences. Setup Doctor reads the CRM-shaped fields and can run when Instantly (or an agency workflow) calls the hook.

**Reply Desk** quotes Unibox thread heads: lead, subject, interest status (`i_status`), AI interest value, auto-reply flag, and a short preview. It does not reply, forward, or change a lead’s interest. **Campaign Desk** quotes Instantly’s own counts (emails sent, unique replies, bounced leads) next to the sending-status code.

**Provisioning webhook.** Point an Instantly or agency webhook at `POST /hooks/instantly`. The body can carry `domain`, `email`, `account.email`, or a `domains` list. Setup Doctor diagnoses each sender domain, stores the row (it survives a process restart), and attaches the Deliverability Agent handoff. The handoff is instructions. The hook does not activate, pause, or update a lead.

```bash
export SETUP_DOCTOR_INSTANTLY_HOOK_SECRET='long-random-secret'
export SETUP_DOCTOR_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'   # optional
```

Sign the raw body as `X-Setup-Doctor-Signature: t=<unix>,v1=<hex>`. The MAC is HMAC-SHA256 over `{timestamp}.{body}` with that secret, and the timestamp must be within five minutes. An unset Slack URL returns `not_checked` on the hook response. It does not fail the diagnosis. Fetch the last stored row with `GET /hooks/instantly/last/{domain}` and an API key.

## Connect beside Instantly

Dual MCP in one chat. Full steps: [docs/INSTANTLY_CONNECT.md](docs/INSTANTLY_CONNECT.md).

```json
{
  "mcpServers": {
    "instantly": {
      "url": "https://mcp.instantly.ai/mcp",
      "headers": { "Authorization": "Bearer YOUR_INSTANTLY_KEY" }
    },
    "setup-doctor": {
      "url": "https://YOUR_HOST/mcp",
      "headers": {
        "X-API-Key": "YOUR_SETUP_DOCTOR_KEY",
        "X-Instantly-Api-Key": "YOUR_INSTANTLY_KEY"
      }
    }
  }
}
```

HTTP API (`pip install -e ".[api]"`):

```bash
uvicorn setup_doctor.surfaces.api:app
# POST /diagnose          {"domain":"example.com", "include_instantly": false}
# POST /instantly/compare {"domain": null}
# POST /instantly/ready   {"ctd_hosts": []}
# POST /bulk              {"domains":["a.test","b.test"]}
# POST /hooks/instantly   signed account / domain payload (see below)
# GET  /hooks/instantly/last/{domain}
# GET  /schema
# Auth: SETUP_DOCTOR_API_KEYS=key:tenant  (header X-API-Key)
# LLM on the API: SETUP_DOCTOR_API_LLM=true
```

MCP (`pip install -e ".[mcp]"`):

```bash
python -m setup_doctor.surfaces.mcp_server
python -m setup_doctor.surfaces.mcp_server --transport streamable-http --port 8000
# Or mount MCP on the API: SETUP_DOCTOR_MOUNT_MCP=1 uvicorn setup_doctor.surfaces.api:app
```

Docker (API + `/mcp`): `docker compose up --build`. Fly: `fly.toml` → `https://setup-doctor-instantly.fly.dev`. Set `SETUP_DOCTOR_API_KEYS` before any public Instantly share. MCP URL: `https://HOST/mcp`. Connect page: `GET /connect`. Public checker: `GET /`.

Cursor skills in this repo: `/domain-doctor`, `/fix-coach`, `/workspace-ready`, `/launch-gate`, `/campaign-desk`, `/reply-desk`. Slash-only: `/setup-doctor`, `/diagnose`, `/spf`, `/dkim`, `/dmarc`, `/mx`, `/fix-plan`, `/instantly`, `/pre-launch-gate`, `/eval-check`.

## Results

From `python evals/run_evals.py` and `evals/mutation_check.py` (see [evals/RESULTS.md](evals/RESULTS.md)):

- Detection: **34/34** labeled fixtures (precision/recall 1.000)
- Advisory detection: **4/4** BIMI / MTA-STS / TLS-RPT fixtures
- Guardrail: faithful rewrites accepted; invented ids, records, bad JSON, duplicates, empty output, and errors rejected; numeric misstatements rejected when exercised
- Schema contract: `DiagnosisResult` `schema_version=1.0` ok
- Shadow: skipped in CI without `evals/shadow/shadow_cases.json` (never merged into synthetic precision/recall)
- Instantly rewrite guardrail: invented scores and verdicts fall back; a faithful rewrite is accepted
- Pre-launch gate: critical Findings block activate; an invented `allowed_to_activate` is rejected
- Campaign Desk: an unhealthy sending-status code stalls the workspace; a sending verdict on a stalled row is rejected
- Reply Desk: an unread count above zero is attention; a missing count stays unknown; two Unibox pages are joined
- Deliverability Agent handoff: a critical Finding holds activation; a clear act on that hold is rejected
- Public DNS corpus: **40/40** frozen domains, scored on its own (not added to the synthetic precision/recall). Rewrite pairs **31/31** grounded; invented ids and records rejected
- Rewrite RAG: **32** example plans, **22/22** finding ids, checked on **61** cases. Retrieved ids are a subset of the current findings. This does not change the detection scores
- Mutations: **24/24** killed
- Tests: **194** pytest

## Limits

- Synthetic fixtures are not real-world accuracy. The public corpus is one DNS-over-HTTPS snapshot from 2026-11-05 (40 domains, default DKIM selectors only), not a zone-wide measurement.
- A null MX (`0 .`, RFC 7505) is treated as no mail server. An empty DKIM `p=` is a revoked key, not a usable key.
- Rewrite RAG shows the model up to two grounded example plans. It does not choose findings, and it does not raise detection precision or recall.
- DKIM selectors cannot be listed from DNS. The check uses common selectors plus `--dkim-selector` / `--esp-pack`.
- Numeric grounding is allow-list patterns only.
- Live DNS, real Anthropic, and a real Instantly account are not assumed green in CI. Instantly mode reports missing scores and tests as **unknown**.
- Reputation adapters default to **not checked**.
- Instantly write APIs (pause accounts, enable warmup, create campaigns) are out of scope. The Deliverability Agent card and the webhook handoff are instructions only.
- Reply Desk reads at most five Unibox pages (20 threads each). A repeated cursor or a sixth page is `more_threads`. `domain_blocked` is set only for a sending domain the caller already named.
- `POST /hooks/instantly` stores the DNS result and the agent card in `SETUP_DOCTOR_WEBHOOK_STORE` (default: a file under the system temp directory). That file is what survives a process restart.

## Layout

Layering rules: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
src/setup_doctor/
  core/             Finding, DiagnosisResult, observability
  dns/              Resolver, SPF parse
  checks/           registry + engine (Findings only)
  explain/          rewrite + verify + report
  pipeline/         diagnose graph
  integrations/     Instantly, reputation
  surfaces/         CLI, API, MCP, auth, bulk
evals/              detection/, guardrails/, mutations/, shadow/, contracts/, corpus/
tests/              mirrors packages (core|dns|checks|explain|…)
.cursor/skills/     domain-doctor, fix-coach, workspace-ready, launch-gate, …
docs/               FOR_INSTANTLY.md, ARCHITECTURE.md, INSTANTLY_CONNECT.md
examples/           offline DNS fixtures
```
