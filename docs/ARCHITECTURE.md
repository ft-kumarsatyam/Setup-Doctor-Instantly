# Setup Doctor architecture

## Layered packages

```
src/setup_doctor/
  core/           Finding, DiagnosisResult, observability   (no I/O)
  dns/            Resolver, SPF parse                       (injectable DNS)
  checks/         registry + engine (SPF/DKIM/DMARC/MX/…)   (Findings only)
  explain/        template/LLM rewrite + verify + report    (never invent Findings)
  pipeline/       LangGraph diagnose                        (orchestration)
  integrations/   Instantly, reputation                     (signals / unknown)
  surfaces/       CLI, HTTP API, MCP, auth, bulk            (thin adapters)
```

Dependency rule (inward only):

```
surfaces → pipeline → checks/explain → dns/core
integrations → surfaces/pipeline (signals only)
```

Surfaces must not reimplement SPF/DKIM logic. Skills/MCP call surfaces or the public `diagnose_result` API.

## Data flow

```
Resolver → CheckRegistry.run → Findings
     → retrieve examples (LLM path only; ids must be a subset)
     → Explainer (optional LLM) → verify_plan → render
     → DiagnosisResult (+ optional signals)
```

## Instantly integration (signals only)

```
InstantlyClient (read-only API v2)
  → compare_warmup_to_placement (aligned|mismatch|unknown)
  → account vitals / CTD / placement insights / Deliverability Agent state
  → DiagnosisSignals.instantly  (never Findings)
  → optional LLM rewrite with verify_instantly_rewrite (fallback = template)

Workspace readiness:
  Instantly accounts → unique domains → diagnose (+ esp-pack instantly)
  → correlate vitals agree|disagree|unknown vs Findings

Campaign Desk (`campaign_desk.py`): list campaigns, analytics counts, sending-status.
Reply Desk (`reply_desk.py`): unread count and up to five pages of received threads.
`domain_blocked` is true only when the caller names that sending domain; otherwise null.
Deliverability Agent handoff (`agent_handoff.py`): an action card (`hold` / `review` /
`clear` / `unknown`) built from Findings plus whether Instantly has a default agent.
The card does not pause or activate. Missing agent state stays null.
Both desks are read-only. Missing Instantly fields stay unknown. MCP tools:
`campaign_desk`, `reply_desk`. CLI: `--campaign-desk`, `--reply-desk`.
```

Missing Instantly data ⇒ `unknown` / `not_checked`. Surfaces: CLI
(`--with-instantly`, `--instantly-compare`, `--instantly-ready`, `--from-instantly`),
HTTP (`/instantly/compare`, `/instantly/ready`, `include_instantly` on `/diagnose`),
MCP stdio + streamable HTTP (`compare_instantly`, `instantly_ready`, diagnose flag).
Instantly key order: `X-Instantly-Api-Key` → tenant vault (optional) → env.
Hosted dual-MCP: [INSTANTLY_CONNECT.md](INSTANTLY_CONNECT.md) (also live at `GET /connect`).
MCP mount rewrites `/mcp`→`/mcp/` in-process and forces HTTPS Location headers behind Fly (`force_https` + `ProxyHeadersMiddleware`).
Launch gate: `integrations/instantly/launch.py` (`launch_verdict`, `pre_launch_gate`).
Fix packets: `explain/fix_packets.py`. Webhook: `POST /hooks/instantly` diagnoses DNS,
attaches the agent handoff, and writes the row to `SETUP_DOCTOR_WEBHOOK_STORE`
(default under the system temp directory). `GET /hooks/instantly/last/{domain}`
reads that file after a process restart.
Partner copy: [MARKETPLACE.md](MARKETPLACE.md).

## Tests mirror packages

```
tests/core|dns|checks|explain|pipeline|integrations|surfaces/
```

## Evals

```
evals/detection|guardrails|mutations|shadow|contracts|corpus/
```

`evals/corpus/` is a frozen public-DNS snapshot (SPF closure included) with separate labels and grounded rewrite pairs. Its score is reported on its own and is never added to the synthetic detection precision/recall.

## Adding a check (scale path)

1. Implement in `checks/` (or new pack module).
2. Register in `checks/registry.py`.
3. Labeled fixture (+ boundary) under `evals/detection/`.
4. Unit test under `tests/checks/`.
5. Mutant in `evals/mutations/mutation_check.py`.
6. Keep advisory packs opt-in unless product decides otherwise.

## Entrypoints

| Surface | Module |
|---------|--------|
| CLI | `python -m setup_doctor` → `surfaces.cli` |
| API | `uvicorn setup_doctor.api:app` (shim) or `setup_doctor.surfaces.api:app` |
| MCP | `python -m setup_doctor.mcp_server` |
| Library | `from setup_doctor import diagnose, diagnose_result, run_checks` |
