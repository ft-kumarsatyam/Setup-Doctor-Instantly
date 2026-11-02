# Loom script (about 3 minutes 30 seconds)

Speak it in your own words; this is a shot list, not a teleprompter. Keep your editor, a terminal, and the README
open. Nothing here should be said unless it is true after you have run the project yourself.

## 0:00 - 0:25 | Who you are and why this

"I'm [name], an AI engineer. I wanted to show you how I work rather than describe it, so I built a small project
around a problem new cold-email senders keep hitting: getting SPF, DKIM, DMARC and MX right before the first
campaign. I know you already have a Deliverability Agent for running workspaces, so this targets the setup step
before it."

## 0:25 - 1:15 | The one design idea (show the diagram in the README)

"The rule is that the LLM never decides what is wrong. Deterministic code produces findings. The model only turns
them into a plan. Then a verifier checks the draft: every finding id has to be real, every critical and high finding
has to be present, and any DNS record the model suggests has to come from a finding. If the check fails, or the
model errors, it falls back to a template. So a hallucination can't reach the user."

## 1:15 - 2:15 | Prove it (terminal)

1. `python -m setup_doctor mess.test --records examples/mess.json` : show the prioritized report.
2. `python evals/run_evals.py` : "24 labeled domains, exact match on all; seven fake model behaviors; invented
   findings and invented records are rejected every time."
3. `python evals/mutation_check.py` : "Here I break the code on purpose, eight different ways. If any mutant
   survived, my evals would have a blind spot. All eight are caught."

## 2:15 - 3:00 | What broke (this is the part they asked for)

Tell the real story from the build:
- "My first live resolver turned any DNS failure into an empty answer. In my sandbox every lookup returned NXDOMAIN,
  even for example.com, and the tool confidently reported SPF_MISSING and DMARC_MISSING. That is a false diagnosis
  caused by treating an outage as a missing record. Now outages raise an error, an apex domain that does not resolve
  is refused, and there is a regression test."
- "My first guardrail metric re-ran the verifier on its own output, which is circular. I replaced it with planted
  strings searched independently, then added the mutation check."

## 3:00 - 3:30 | Honest limits and what is next

"It doesn't verify numbers yet: a model that says 14 lookups instead of 11 gets through, and there's a test pinning
that. Fixtures are synthetic, so the next step is a real labeled set. And on your side, I'd like to test whether warmup
scores predict real inbox placement using the API. Thanks for watching: the repo and README have the details."

## Delivery notes

- Do not show any real customer, domain, or API key on screen.
- If something fails on camera, say what it is. They explicitly ask for what broke and how you fixed it.
