# Setup Doctor

Diagnoses the DNS side of a cold-email setup (SPF, DKIM, DMARC, MX) and explains the fix order in plain English.
The interesting part is not the DNS checks. It is how an LLM is allowed to touch the result.

> **The LLM never decides what is wrong.** Deterministic code produces the findings. The model returns a JSON plan
> of `{id, explanation}` objects only; a verifier rejects any draft whose ids do not match the findings or whose
> explanations invent DNS records or allow-listed numbers. Validated plans are rendered with each finding's own
> title and fix. Rejected drafts fall back to a deterministic template, so a hallucination cannot reach the user.

## Why this exists

Public reviews and setup guides keep describing the same early-stage pain: new senders get SPF, DKIM, DMARC and MX
wrong before their first campaign (the SPF 10-lookup limit and forgotten MX records come up repeatedly), and an
inexperienced sender cannot tell which of several warnings matters first. Mailbox providers now reject, not just
spam-folder, non-compliant bulk mail. This is a hypothesis built from public sources, not from any company's
internal data, and the first step in a real deployment would be to check it against actual onboarding data.

## How it works

```
 domain
   |
   v
 [check]    deterministic SPF/DKIM/DMARC/MX checks  ->  Findings   (ground truth, no LLM)
   |
   v
 [explain]  LLM returns JSON [{id, explanation}, ...] (or template writes prose)
   |
   v
 [verify]   parse JSON; id set == findings; DNS + numeric claims in explanations grounded?
   |            |
   | ok         | violations / empty / malformed / model error
   v            v
 [render]   [fallback] deterministic template  --->  [render]
            (model path: title+fix from Findings, explanation from JSON)
```

Built with LangGraph (conditional edge on the verify step). Real DNS is behind a small `Resolver` interface, so the
same code runs against live DNS, or against frozen records in tests and evals.

## Design decisions worth reviewing

1. **Findings are the only source of truth.** The prompt contains the findings JSON and nothing else, and the test
   suite asserts that. Model output cannot create, remove, or re-rank findings; render takes title/fix from Findings.
2. **Structured grounding verifier.** Model drafts must be a JSON list of `{id, explanation}`. Rejects malformed
   JSON, duplicate ids, id-set mismatches, DNS records in explanations that appear in neither fix nor evidence, and
   allow-listed numeric claims that do not match a number in a finding's title or evidence.
3. **An outage is not a missing record.** `LiveResolver` treats NXDOMAIN/no-answer as "absent" but raises
   `ResolverError` on timeouts, and the CLI refuses to diagnose a domain whose apex does not resolve. I found this
   while building: in my sandbox the resolver answered NXDOMAIN for every name, including `example.com`, and the
   first version reported confident `SPF_MISSING`/`DMARC_MISSING` findings. There is now a regression test.
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

**Unit tests**: `python -m pytest -q` runs 74 tests.

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
- **The Anthropic adapter is untested against the real API.** The suite uses scripted fakes. `--llm` needs
  `ANTHROPIC_API_KEY` and `SETUP_DOCTOR_MODEL`.

## Quickstart

```bash
pip install -e ".[dev]"            # or: pip install langgraph dnspython pytest
python -m pytest -q                # 74 tests
python evals/run_evals.py          # detection + guardrail evals
python evals/mutation_check.py     # prove the evals can fail

python -m setup_doctor mess.test --records examples/mess.json     # offline demo
python -m setup_doctor yourdomain.com                              # live DNS
python -m setup_doctor yourdomain.com --llm                        # live DNS + model explanation
```

## What I would build next

1. A labeled set of real domains with human-verified diagnoses, so detection accuracy means something.
2. Instantly API mode: read each connected account's warmup score and inbox-placement test results through the
   public API v2 and report how well the score predicts placement. This addresses the widely reported
   "dashboard looks healthy but mail lands in spam" complaint, and it needs real account data to validate.
3. A webhook-driven reply classifier with the same grounding discipline.

## Layout

```
src/setup_doctor/   models, resolver, spf, checks, explain (+verifier), graph, report, cli
evals/              fixtures (labeled), fakes (scripted model failures), run_evals, mutation_check, RESULTS.md
tests/              74 pytest tests
examples/           frozen DNS records for offline demos
```
