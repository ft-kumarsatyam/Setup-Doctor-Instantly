# Setup Doctor

DNS checks for cold-email setup (SPF, DKIM, DMARC, MX), then a plain-English fix order. Optional advisory packs (BIMI / MTA-STS / TLS-RPT), Instantly signals, bulk scan, HTTP API, MCP, and Cursor `/skills`.

Deterministic code owns the Findings. An optional LLM only rewrites them. A verifier blocks invented ids, records, and allow-listed numbers; failures fall back to a template.

```
check → explain → verify → render
                 ↘ fallback → render
```

Versioned product contract: `DiagnosisResult` (`schema_version` **1.0**) shared by CLI, API, MCP, and skills.

## Run

```bash
pip install -e ".[dev]"

python -m setup_doctor mess.test --records examples/mess.json
python -m setup_doctor yourdomain.com
python -m setup_doctor yourdomain.com --llm   # needs ANTHROPIC_API_KEY + SETUP_DOCTOR_MODEL
python -m setup_doctor yourdomain.com --advisory --esp-pack google --json
python -m setup_doctor --bulk domains.csv

python -m pytest -q
python evals/run_evals.py
python evals/mutation_check.py
```

HTTP API (optional: `pip install -e ".[api]"`):

```bash
uvicorn setup_doctor.surfaces.api:app
# (compat) uvicorn setup_doctor.api:app
# POST /diagnose {"domain":"example.com", "include_instantly": false}
# POST /instantly/compare {"domain": null}
# POST /instantly/ready {"ctd_hosts": []}
# POST /bulk {"domains":["a.test","b.test"]}
# GET  /schema
# Auth: set SETUP_DOCTOR_API_KEYS=key:tenant (X-API-Key). LLM: SETUP_DOCTOR_API_LLM=true
```

MCP (optional: `pip install -e ".[mcp]"`):

```bash
python -m setup_doctor.surfaces.mcp_server
# Hosted streamable HTTP (API key via SETUP_DOCTOR_API_KEYS):
python -m setup_doctor.surfaces.mcp_server --transport streamable-http --port 8000
# Or mount MCP on the API: SETUP_DOCTOR_MOUNT_MCP=1 uvicorn setup_doctor.surfaces.api:app
```

Docker (API + `/mcp`): `docker compose up --build`. Fly: `fly.toml` →
`https://setup-doctor-instantly.fly.dev` (set `SETUP_DOCTOR_API_KEYS` before any Instantly share).
MCP URL: `https://HOST/mcp` (HTTPS; trailing slash optional — no HTTP 307).
Connect UI: `GET /connect` (same as [docs/INSTANTLY_CONNECT.md](docs/INSTANTLY_CONNECT.md)).
Per-request Instantly key: `X-Instantly-Api-Key` (else `INSTANTLY_API_KEY`).

Cursor skills (in-repo): `/setup-doctor`, `/diagnose`, `/spf`, `/dkim`, `/dmarc`, `/mx`, `/fix-plan`, `/instantly`, `/pre-launch-gate`, `/eval-check`.

Instantly (read-only API v2, needs `INSTANTLY_API_KEY`). Missing scores/tests ⇒ **unknown**, never healthy. Instantly vitals/CTD are signals — they never invent Findings:

```bash
python -m setup_doctor --instantly-compare
python -m setup_doctor yourdomain.com --with-instantly --json
python -m setup_doctor --instantly-ready --ctd-host track.example.com
python -m setup_doctor --instantly-ready --agency-export
python -m setup_doctor --instantly-ready --all-workspaces --json
python -m setup_doctor --pre-launch-gate --json
python -m setup_doctor mess.test --records examples/mess.json --fix-packet cloudflare
python -m setup_doctor --from-instantly --json
```

Agency / marketplace notes: [docs/MARKETPLACE.md](docs/MARKETPLACE.md). Public checker UI at `GET /` on the API.

CI: `.github/workflows/ci.yml` (Python 3.11 / 3.13 — ruff, pytest, evals, mutants).

## Results

From `python evals/run_evals.py` / `evals/mutation_check.py` (see `evals/RESULTS.md`):

- Detection: **31/31** labeled fixtures (precision/recall 1.000)
- Advisory detection: **4/4** BIMI / MTA-STS / TLS-RPT fixtures
- Guardrail: faithful accepted; invented ids/records, bad JSON, dupes, empty/errors rejected; numeric misstatements rejected when exercised
- Schema contract: `DiagnosisResult` `schema_version=1.0` ok
- Shadow: skipped in CI without `evals/shadow/shadow_cases.json` (never merged into synthetic P/R)
- Instantly rewrite guardrail: invented scores/verdicts fall back; faithful rewrite accepted
- Pre-launch gate: critical Findings block activate; invented `allowed_to_activate` rejected
- Mutations: **17/17** killed
- Tests: **174** pytest

## Limits

- Fixtures are synthetic — not real-world accuracy.
- DKIM selectors can’t be listed from DNS (common selectors + `--dkim-selector` / `--esp-pack`).
- Numeric grounding is allow-list patterns only.
- Live DNS / real Anthropic / real Instantly account data are not assumed green in CI; Instantly mode reports missing scores/tests as **unknown**.
- Reputation adapters default to **not checked** (never fabricated clean).
- Instantly write APIs (pause accounts, enable warmup, create campaigns) are out of scope.

## Layout

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for layering rules.

```
src/setup_doctor/
  core/             Finding, DiagnosisResult, observability
  dns/              Resolver, SPF parse
  checks/           registry + engine (Findings only)
  explain/          rewrite + verify + report
  pipeline/         diagnose graph
  integrations/     Instantly, reputation
  surfaces/         CLI, API, MCP, auth, bulk
evals/              detection/, guardrails/, mutations/, shadow/, contracts/
tests/              mirrors packages (core|dns|checks|explain|…)
.cursor/skills/     /diagnose, /spf, /dkim, …
docs/               ARCHITECTURE.md
examples/           offline DNS fixtures
```
