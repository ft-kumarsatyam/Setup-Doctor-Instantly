# Marketplace & partner positioning

**One-liner:** DNS Doctor for Instantly workspaces — Setup Doctor finds the SPF/DKIM/DMARC/MX blockers; Instantly owns placement, warmup, and Deliverability Agent actions.

## Positioning (honest)

| Setup Doctor | Instantly |
|---|---|
| Deterministic DNS Findings | Warmup / inbox placement / CTD |
| Pre-launch gate (`allowed_to_activate`) | Campaign activate / pause |
| Paste-ready registrar fix packets | AI Deliverability Agent |
| Hosted MCP beside `mcp.instantly.ai` | Hosted Instantly MCP |

We **do not** seed placement networks, verify prospect emails, or write Instantly mutations.

## Listings copy (draft)

**Instantly Partner / Experts:**  
“Setup Doctor — deep DNS pre-launch checks for Instantly agencies. Dual-MCP with Instantly: Findings first, then placement signals. Never invents healthy when data is missing.”

**MCP directories:**  
Name: `setup-doctor`  
URL: `https://YOUR_HOST/mcp` (HTTPS only; e.g. `https://setup-doctor-instantly.fly.dev/mcp`)  
Auth: `X-API-Key` (require `SETUP_DOCTOR_API_KEYS` on public hosts)  
Optional: `X-Instantly-Api-Key`  
Tools: `diagnose`, `compare_instantly`, `instantly_ready`, `pre_launch_gate`  
Connect one-pager: `https://YOUR_HOST/connect`

**OpenAPI:** expose FastAPI `/schema`, `/diagnose`, `/instantly/ready`, `/instantly/pre-launch-gate`, `/fix-packet`.

## Agency handoff

```bash
python -m setup_doctor --instantly-ready --agency-export
# or POST /instantly/ready {"agency_export": true, "client_name": "Acme", "agency_name": "You"}
```

Connect pack: [INSTANTLY_CONNECT.md](INSTANTLY_CONNECT.md).
