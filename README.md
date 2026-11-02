# Setup Doctor

Diagnoses the DNS side of a cold-email setup (SPF, DKIM, DMARC, MX) and explains the fix order in plain English.
The interesting part is not the DNS checks. It is how an LLM is allowed to touch the result.

> **The LLM never decides what is wrong.** Deterministic code produces the findings. The model only rewrites them
> into a plan, and a verifier rejects any draft that cites a problem or DNS record the checks did not produce. Rejected drafts fall back to a deterministic template, so a hallucination cannot reach the user.

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
 [explain]  LLM (or template) drafts a prioritized plan from the Findings only
   |
   v
 [verify]   every [FINDING_ID] real?  every critical/high finding present?  every DNS record grounded?
   |            |
   | ok         | violations / empty / model error
   v            v
 [render]   [fallback] deterministic template  --->  [render]
```

Built with LangGraph (conditional edge on the verify step). Real DNS is behind a small `Resolver` interface, so the
same code runs against live DNS, or against frozen records in tests and evals.

## Design decisions worth reviewing

1. **Findings are the only source of truth.** The prompt contains the findings JSON and nothing else, and the test
   suite asserts that.
2. **Grounding verifier.** Rejects unknown finding ids, omitted critical/high findings, DNS records that appear
   in neither a finding's evidence nor its fix, and allow-listed numeric claims (lookup counts, pct=, etc.) that
   do not match a number in a finding's title or evidence.
3. **An outage is not a missing record.** `LiveResolver` treats NXDOMAIN/no-answer as "absent" but raises
   `ResolverError` on timeouts, and the CLI refuses to diagnose a domain whose apex does not resolve. I found this
   while building: in my sandbox the resolver answered NXDOMAIN for every name, including `example.com`, and the
   first version reported confident `SPF_MISSING`/`DMARC_MISSING` findings. There is now a regression test.
4. **Evals that can fail.** See below.

## Results

Reproduce with `python evals/run_evals.py` (writes `evals/RESULTS.md`).

**Detection** against 24 labeled synthetic domains: 24/24 exact finding-set matches, precision 1.000, recall 1.000
(29 TP, 0 FP, 0 FN). Boundaries are covered (exactly 10 SPF lookups is fine, 11 is flagged; nested includes; include
loops; bare `all` means `+all`; `redirect=` replaces `all`).

**Guardrail**: seven scripted model behaviors run against every fixture that has findings (20 of 24):

| Model behavior | Result |
|---|---|
| faithful rewrite | accepted 20/20 |
| invents a finding | rejected 20/20 |
| invents a DNS record | rejected 20/20 |
| drops a critical/high finding | rejected 10/10 where one exists |
| API error, or empty output | rejected 20/20 each |
| changes a number in the text | rejected 2/2 where a lookup count was altered |

Planted hallucinations delivered to the user: **0**, measured by searching the delivered text for the planted
strings, not by re-running the verifier (that would be circular).

**Mutation check** (`python evals/mutation_check.py`): 9 deliberate bugs, each injected into a copy of the code
(SPF limit off by one, verifier checks disabled including numeric claims, fallback removed, and so on). All 9 make
the eval suite fail. That is the evidence the evals are not just rubber-stamping the code.

**Unit tests**: `python -m pytest -q` runs 58 tests.

## Known limitations (read before trusting this)

- **Numeric grounding is allow-list only.** The verifier checks claim shapes such as `needs N DNS lookups`,
  `limit is N`, `pct=N`, and `N% of mail` against numbers in finding titles/evidence. Free-form invented numbers
  outside those patterns are still not checked.
- **Fixtures are synthetic.** 100% here shows the rules are implemented correctly and regressions get caught. It says
  nothing about how real-world domains behave. A real labeled set of domains is the first thing I would build next.
- **DKIM cannot be enumerated.** DNS has no way to list selectors, so the check tries 9 common ones and reports a
  possible false positive for custom selectors (use `--dkim-selector`).
- **DNS only.** It does not measure inbox placement, warmup quality, list quality, or sender reputation.
- **Live mode is verified with stubs, not end to end.** The sandbox this was built in returns NXDOMAIN for every
  name, so I could not run a real lookup against a real domain. Run it on your machine and check a domain you know.
- **The Anthropic adapter is untested against the real API.** The suite uses scripted fakes. `--llm` needs
  `ANTHROPIC_API_KEY` and `SETUP_DOCTOR_MODEL`.

## Quickstart

```bash
pip install -e ".[dev]"            # or: pip install langgraph dnspython pytest
python -m pytest -q                # 58 tests
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
tests/              58 pytest tests
examples/           frozen DNS records for offline demos
```
