# Application note (AI Engineer, Instantly)

Fill every [BRACKET] yourself. Do not send until you have run the project on your own machine (checklist below).

## Before you send

1. Confirm the role and where to apply on Instantly's own careers page. The postings I found are on third-party
   job boards and recruiting-partner pages, some of them old. One listing says to email a CV plus a Loom; others
   describe a recruiter screen, a one-hour take-home, and a live coding interview.
2. **Do not drop the CV entirely.** You said you would rather share a project than a resume. A project is a strong
   lead, but the postings I found explicitly ask for a CV. Attach a one-page CV or link a LinkedIn profile as a
   secondary item, so a screener who needs one is not forced to reject you on process.
3. Run it yourself: `pip install -e ".[dev]"`, `pytest`, `python evals/run_evals.py`, `python evals/mutation_check.py`,
   and one live lookup on a domain you own. My build sandbox could not run a real DNS lookup, so your live run is
   the first real one. Put the real result in the README if it surprises you.
4. Push the repo to your GitHub (public), and record the Loom (script in `LOOM_SCRIPT.md`).
5. Only claim experience you have. Everything in the README is about this project; anything about your past work
   must come from you.

## Email / form text (about 150 words)

**Subject:** AI Engineer application: grounded-LLM project built on your public setup pain points

Hi [Name],

I'm [Your name], a senior developer and AI engineer with [N] years building [one concrete thing you have actually
shipped, with a number if you have one].

Instead of a long CV, I built something relevant: **Setup Doctor** ([repo link]), a LangGraph workflow that
diagnoses cold-email DNS setup (SPF/DKIM/DMARC/MX). Deterministic checks produce the findings, an LLM only explains
them, and a verifier rejects any explanation that invents a finding or DNS record. It has 57 tests, a 24-case
labeled eval, and a mutation check showing the evals fail when I break the code on purpose. The README lists
what it does not do, including a numeric-claim gap I have not closed.

3-minute walkthrough: [Loom link]. I know you already ship a Deliverability Agent, so I built the earlier part of
the journey instead. I would like to discuss where this thinking fits on your AI & Automation team.

CV attached for reference.

[Name] | [GitHub] | [LinkedIn]

## Things to avoid saying

- Anything implying inside knowledge of Instantly's systems, tickets, or funnel. Everything here comes from public
  reviews and public documentation, and the README says the pain-point framing is a hypothesis.
- Any revenue, reply-rate, or customer number you did not personally produce.
- That the live mode or the Anthropic adapter is production-tested. The README states exactly what was verified.
