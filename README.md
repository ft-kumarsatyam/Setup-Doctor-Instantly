# Setup Doctor

DNS checks for cold-email setup (SPF, DKIM, DMARC, MX), then a plain-English fix order.

Deterministic code owns the Findings. An optional LLM only rewrites them. A verifier blocks invented ids, records, and allow-listed numbers; failures fall back to a template.

```
check → explain → verify → render
                 ↘ fallback → render
```

## Run

```bash
pip install -e ".[dev]"

python -m setup_doctor mess.test --records examples/mess.json
python -m setup_doctor yourdomain.com
python -m setup_doctor yourdomain.com --llm   # needs ANTHROPIC_API_KEY + SETUP_DOCTOR_MODEL

python -m pytest -q
python evals/run_evals.py
python evals/mutation_check.py
```

HTTP API (optional: `pip install -e ".[api]"`):

```bash
uvicorn setup_doctor.api:app
# POST /diagnose {"domain":"example.com"}
```

Instantly warmup vs placement (read-only API v2, needs `INSTANTLY_API_KEY`):

```bash
python -m setup_doctor --instantly-compare
```

CI: `.github/workflows/ci.yml` (Python 3.11 / 3.13 — ruff, pytest, evals, mutants).

## Results

From `python evals/run_evals.py` (see `evals/RESULTS.md`):

- Detection: **31/31** labeled fixtures (precision/recall 1.000)
- Guardrail: faithful accepted; invented ids/records, bad JSON, dupes, empty/errors rejected; numeric misstatements rejected when exercised
- Mutations: **13/13** killed
- Tests: **111** pytest

## Limits

- Fixtures are synthetic — not real-world accuracy.
- DKIM selectors can’t be listed from DNS (common selectors + `--dkim-selector`).
- Numeric grounding is allow-list patterns only.
- Live DNS / real Anthropic / real Instantly account data are not assumed green in CI; Instantly mode reports missing scores/tests as **unknown**.

## Layout

```
src/setup_doctor/   checks, explain, graph, api, instantly_*
evals/              fixtures, fakes, run_evals, mutation_check
tests/              pytest
examples/           offline DNS fixtures
```
