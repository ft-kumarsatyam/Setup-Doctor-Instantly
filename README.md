# Setup Doctor

Diagnoses the DNS side of a cold-email setup (SPF, DKIM, DMARC, MX) and explains **what to fix first** in plain English.

The interesting part is not the DNS checks. It is how an LLM is allowed to touch the result:

> **The LLM never decides what is wrong.** Deterministic code produces Findings. The model only rewrites them into a plan. A verifier rejects any draft that invents findings, DNS records, or allow-listed numbers. Rejected drafts fall back to a template — so a hallucination cannot reach the user.

## Quickstart

```bash
pip install -e ".[dev]"

python -m setup_doctor mess.test --records examples/mess.json   # offline demo (no DNS)
python -m setup_doctor yourdomain.com                           # live DNS
python -m setup_doctor yourdomain.com --llm                     # live DNS + model explanation

python -m pytest -q                 # unit tests
python evals/run_evals.py           # detection + guardrail evals
python evals/mutation_check.py      # prove the evals can fail
```

`--llm` needs `ANTHROPIC_API_KEY` and `SETUP_DOCTOR_MODEL`. Without `--llm`, you still get a full prioritized report from the template explainer.

## End to end: what happens when you run a domain

One command. Five steps. The model only touches step 2, and only under a verifier.

```
 you pass a domain
        |
        v
 1. CHECK     Look up SPF / DKIM / DMARC / MX (live DNS or a frozen fixture).
              Pure Python produces a sorted list of Findings.
              No LLM. This list is ground truth.
        |
        v
 2. EXPLAIN   Turn Findings into a short plan.
              • default: deterministic template (always safe)
              • --llm:    model returns JSON [{id, explanation}, ...]
        |
        v
 3. VERIFY    Does the draft match the Findings?
              • every id must exist; none may be invented
              • critical/high findings cannot be dropped
              • DNS records and allow-listed numbers in explanations
                must appear in a finding's fix or evidence
              Fail / empty / malformed / API error → go to step 4.
        |
        +-- ok ------------------+
        |                        |
        v                        v
 4. FALLBACK              5. RENDER
    Use the template.         Markdown report:
    Model text is discarded.  title + fix from Findings;
                              explanation from the verified plan
                              (or the template).
```

Built with LangGraph (conditional edge after verify). DNS sits behind a small `Resolver` interface, so the same checks run against live DNS or frozen records in tests and evals.

### Concrete example

```bash
python -m setup_doctor mess.test --records examples/mess.json
```

1. Fixture DNS is loaded — no network.
2. Checks emit findings such as `SPF_TOO_MANY_LOOKUPS`, `MX_MISSING`, …
3. Template (or LLM + verifier) writes one explanation per finding id.
4. You get a Markdown report ordered by severity: fix MX / SPF before polishing DMARC wording.

If the model invents a finding id or a DNS record that the checks never produced, verify rejects the draft and the report is the template — never the hallucination.

## Why this exists

Public reviews and setup guides keep describing the same early-stage pain: new senders get SPF, DKIM, DMARC and MX wrong before their first campaign (the SPF 10-lookup limit and forgotten MX records come up repeatedly), and an inexperienced sender cannot tell which of several warnings matters first. Mailbox providers now reject, not just spam-folder, non-compliant bulk mail. This is a hypothesis built from public sources, not from any company's internal data, and the first step in a real deployment would be to check it against actual onboarding data.

## Design decisions worth reviewing

1. **Findings are the only source of truth.** The prompt contains the findings JSON and nothing else, and the test suite asserts that. Model output cannot create, remove, or re-rank findings; render takes title/fix from Findings.
2. **Structured grounding verifier.** Model drafts must be a JSON list of `{id, explanation}`. Rejects malformed JSON, duplicate ids, id-set mismatches, DNS records in explanations that appear in neither fix nor evidence, and allow-listed numeric claims that do not match a number in a finding's title or evidence.
3. **An outage is not a missing record.** `LiveResolver` treats NXDOMAIN/no-answer as "absent" but raises `ResolverError` on timeouts, and the CLI refuses to diagnose a domain whose apex does not resolve. I found this while building: in my sandbox the resolver answered NXDOMAIN for every name, including `example.com`, and the first version reported confident `SPF_MISSING`/`DMARC_MISSING` findings. There is now a regression test.
4. **Evals that can fail.** See below.

## Results

Reproduce with `python evals/run_evals.py` (writes `evals/RESULTS.md`).

**Detection** against 31 labeled synthetic domains: 31/31 exact finding-set matches, precision 1.000, recall 1.000
(34 TP, 0 FP, 0 FN). Boundaries covered include: exactly 10 SPF lookups fine / 11 flagged; exactly 2 SPF void
lookups fine / 3 flagged; 2048-bit DKIM fine / 1024-bit flagged; nested includes; include loops; bare `all` means
`+all`; `redirect=` replaces `all`; absent DMARC `sp=` inherits `p=` (not flagged).

**Guardrail**: nine scripted model behaviors run against every fixture that has findings (24 of 31):

| Model behavior | Result |
|---|---|
| faithful JSON rewrite | accepted 24/24 |
| invents a finding | rejected 24/24 |
| invents a DNS record | rejected 24/24 |
| drops a critical/high finding | rejected 10/10 where one exists |
| changes a number in an explanation | rejected 2/2 where a lookup count was altered |
| malformed JSON | rejected 24/24 |
| duplicate ids | rejected 24/24 |
| API error, or empty output | rejected 24/24 each |

Planted hallucinations delivered to the user: **0**, measured by searching the delivered text for the planted
strings, not by re-running the verifier (that would be circular).

**Mutation check** (`python evals/mutation_check.py`): 13 deliberate bugs, each injected into a copy of the code
(SPF limit / void limit off by one, DKIM/DMARC regressions, verifier checks disabled, fallback removed, and so on).
All 13 make the eval suite fail. That is the evidence the evals are not just rubber-stamping the code.

**Unit tests**: `python -m pytest -q` runs 104 tests.

### Checks added in this revision (with sources)

- **DKIM_WEAK_KEY** — RSA `p=` shorter than 2048 bits when DER SPKI parses (RFC 8301 §3.2 SHOULD ≥2048).
- **SPF_VOID_LOOKUPS** — more than 2 void lookups for include/a/mx/exists/redirect (RFC 7208 §4.6.4).
- **DMARC_SP_NONE** — `sp=none` while `p=quarantine|reject` (RFC 7489 §6.3 subdomain policy).
- **DMARC_STRICT_ALIGNMENT** — `adkim=s` and/or `aspf=s` (RFC 7489 §6.3; changes subdomain-sending advice).

### Checks considered and rejected

- **BIMI / MTA-STS / TLS-RPT / DNSSEC / ARC** — useful later, but need extra record types and (for BIMI) VMC material we cannot honestly fixture without inventing validation we did not implement.
- **DMARC `ruf=`** — forensic reports are often unused and raise privacy issues; not actionable for most cold-email setups.
- **Empty DKIM `p=` (revoked key)** — distinct from weak keys; skipped to keep the key-strength check focused.
- **SPF `ptr` void lookups** — RFC counts them, but the Resolver has no PTR API; voids for ptr are not counted (ptr is already flagged separately as deprecated).
- **Ed25519 DKIM key “strength”** — not RSA; bit-length rule does not apply.

## Known limitations (read before trusting this)

- **Numeric grounding is allow-list only.** The verifier checks claim shapes such as `needs N DNS lookups`,
  `limit is N`, `pct=N`, and `N% of mail` against numbers in finding titles/evidence. Free-form invented numbers
  outside those patterns are still not checked.
- **Fixtures are synthetic.** 100% here shows the rules are implemented correctly and regressions get caught. It says
  nothing about how real-world domains behave. A real labeled set of domains is the first thing I would build next.
- **DKIM cannot be enumerated.** DNS has no way to list selectors, so the check tries 9 common ones and reports a
  possible false positive for custom selectors (use `--dkim-selector`).
- **DKIM key size only when parseable.** If `p=` is not valid base64 DER SubjectPublicKeyInfo, key strength is not
  guessed — no fabricated bit length.
- **SPF ptr voids not counted.** See rejected checks above.
- **DNS only.** It does not measure inbox placement, warmup quality, list quality, or sender reputation.
- **Live mode is verified with stubs, not end to end.** The sandbox this was built in returns NXDOMAIN for every
  name, so I could not run a real lookup against a real domain. Run it on your machine and check a domain you know.
  The HTTP API's live path was likewise not exercised end to end here; tests inject `FixtureResolver` only.
- **The Anthropic adapter is untested against the real API.** The suite uses scripted fakes. `--llm` needs
  `ANTHROPIC_API_KEY` and `SETUP_DOCTOR_MODEL`.

## HTTP API (optional)

```bash
pip install -e ".[api]"            # adds fastapi + uvicorn (reason: free-tool HTTP surface)
uvicorn setup_doctor.api:app --reload
# POST /diagnose  {"domain": "example.com"}  -> {domain, findings, report, cached}
```

Hostname input is validated to reject IPs, localhost/internal suffixes, schemes, paths, ports, and over-long
strings (SSRF / internal probing). Per-IP rate limiting and a short in-memory response cache are on by default.
DNS work has a hard timeout; `ResolverError` returns **502** with a clear message and **no** fabricated findings.

### Privacy and observability

Every `diagnose()` call emits one JSON log line (`setup_doctor.diagnosis`) with
`explanation_source` (`template` / `model_verified` / `template_fallback`), `rejection_reasons`,
`findings_count`, `duration_ms`, and `domain_hash` (SHA-256 prefix). Plaintext domain names are
**not** logged unless `SETUP_DOCTOR_LOG_DOMAIN=1`. Request bodies are never logged. The free-tool
HTTP path uses live DNS + the deterministic template explainer only — do not send API keys in the
request.

## CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on push/PR for **Python 3.11 and 3.13**:
`ruff check`, `pytest`, `evals/run_evals.py`, and `evals/mutation_check.py`.

## What I would build next

1. A labeled set of real domains with human-verified diagnoses, so detection accuracy means something.
2. Instantly API mode: read each connected account's warmup score and inbox-placement test results through the
   public API v2 and report how well the score predicts placement. This addresses the widely reported
   "dashboard looks healthy but mail lands in spam" complaint, and it needs real account data to validate.
3. A webhook-driven reply classifier with the same grounding discipline.

## Layout

```
src/setup_doctor/   models, resolver, spf, checks, explain, graph, report, cli, api, observability
evals/              fixtures, fakes, run_evals, mutation_check, RESULTS.md
tests/              104 pytest tests
.github/workflows/  ci.yml (3.11 + 3.13)
examples/           frozen DNS records for offline demos
```
