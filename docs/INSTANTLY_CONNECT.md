# Connect Instantly MCP + Setup Doctor MCP

Setup Doctor is the **DNS pre-launch doctor** beside Instantly. Instantly owns placement, warmup, and Deliverability Agent actions. Setup Doctor owns deterministic SPF/DKIM/DMARC/MX Findings — never invents health when Instantly data is missing.

**Goal:** dual-MCP connect in under 5 minutes.

## What you get

| Surface | Role |
|---|---|
| Instantly MCP (`mcp.instantly.ai`) | Accounts, vitals, campaigns (incl. activate — use carefully) |
| Setup Doctor MCP | `diagnose`, `compare_instantly`, `instantly_ready` |

Before activating a campaign: run Setup Doctor readiness. If Findings are `critical`/`high`, **do not** call Instantly `activate_campaign`.

## Hosted Setup Doctor (recommended)

1. Deploy with Docker Compose or Fly (`fly.toml` in this repo; `SETUP_DOCTOR_MOUNT_MCP=1`).
2. **Required for any public Instantly share:** invent a secret and set
   `SETUP_DOCTOR_API_KEYS=your-key:tenant`
   (`fly secrets set SETUP_DOCTOR_API_KEYS='…'` — do not leave diagnose open).
   **There is no Setup Doctor signup page** — the host creates the key in env and shares it.
3. Optional process-wide Instantly key: `INSTANTLY_API_KEY=…` (read scopes only).
   Instantly keys come from Instantly Settings → Integrations / API — not from Setup Doctor.
4. Or pass Instantly per request: header `X-Instantly-Api-Key`.

Endpoints:

- Web connect one-pager (this doc, live): `https://YOUR_HOST/connect`
- API: `https://YOUR_HOST/healthz`, `POST /diagnose`, `POST /instantly/ready`
- MCP (streamable HTTP): **`https://YOUR_HOST/mcp`** (HTTPS only; trailing slash optional)

**MCP clients (Cursor / Claude):** use the HTTPS URL above. The API rewrites `/mcp` → `/mcp/` in-process and trusts `X-Forwarded-Proto` so Fly never returns a bare `http://…/mcp/` 307 that breaks MCP clients. Prefer documenting `/mcp` (no slash); both work over HTTPS.

Auth: `X-API-Key: your-key` or `Authorization: Bearer your-key`.

### Fly demo host

```bash
fly secrets set SETUP_DOCTOR_API_KEYS='demo-key:instantly-demo'
fly deploy
# MCP: https://setup-doctor-instantly.fly.dev/mcp
# Connect UI: https://setup-doctor-instantly.fly.dev/connect
```

## Cursor — dual MCP

Copy [examples/mcp.instantly-dual.json](../examples/mcp.instantly-dual.json) into your Cursor MCP config (merge with existing servers). Replace `YOUR_HOST` and keys.

```json
{
  "mcpServers": {
    "instantly": {
      "url": "https://mcp.instantly.ai/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_INSTANTLY_KEY"
      }
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

Local stdio (dev only):

```json
{
  "mcpServers": {
    "setup-doctor": {
      "command": "python",
      "args": ["-m", "setup_doctor.surfaces.mcp_server"],
      "env": {
        "INSTANTLY_API_KEY": "YOUR_INSTANTLY_KEY"
      }
    }
  }
}
```

Use the `/pre-launch-gate` skill in this repo for the agent workflow.

## Claude Desktop

Add both connectors under MCP servers (same URL + header shape as Cursor). Instantly remote MCP + Setup Doctor `https://YOUR_HOST/mcp` with `X-API-Key`.

## ChatGPT Custom GPT (Actions)

Point Actions at the FastAPI OpenAPI surface (same engine as MCP — no parallel DNS logic):

- `POST /diagnose` — body `{ "domain", "include_instantly": true }`
- `POST /instantly/ready` — body `{ "ctd_hosts": [] }`
- `GET /schema` — contract discovery

Send `X-API-Key` and optionally `X-Instantly-Api-Key` on each request.

## Honesty rules for agents

- Quote Setup Doctor `findings` / Instantly `verdict` fields from tool JSON only.
- Missing Instantly scores ⇒ **unknown**, not healthy.
- Instantly vitals/CTD are signals — they never invent Setup Doctor Findings.
- Outage (`resolver_error`) ≠ missing records.
- Do not pause Instantly accounts via Setup Doctor (read-only).

## Scopes (Instantly API v2, read-only)

`accounts:read`, `inbox_placement_tests:read`, `inbox_placement_analytics:read`; readiness may also need `inbox_placement_reports:read` and `ai_agents:read`.

Agency multi-workspace (`--all-workspaces` / `all_workspaces: true`): admin workspace-group key with `workspaces:read` + group member list access. Setup Doctor calls Instantly with `x-as-workspace` per sub-workspace. Missing group access ⇒ `not_checked`, never invents workspaces.

## Tenant Instantly key vault (hosted)

```bash
export SETUP_DOCTOR_API_KEYS=agency-key:acme
export SETUP_DOCTOR_VAULT_KEY='long-random-master-secret'
export SETUP_DOCTOR_VAULT_PATH=/var/lib/setup-doctor/vault.json

# Store once (encrypted at rest)
curl -X POST https://YOUR_HOST/connect/instantly \
  -H "X-API-Key: agency-key" \
  -H "Content-Type: application/json" \
  -d '{"instantly_api_key":"YOUR_INSTANTLY_KEY"}'
```

Later Instantly tools use the vault for that tenant when `X-Instantly-Api-Key` is omitted. Optional Slack notify on provisioning hooks: `SETUP_DOCTOR_SLACK_WEBHOOK_URL`.
