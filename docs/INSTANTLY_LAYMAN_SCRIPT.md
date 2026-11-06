# Setup Doctor × Instantly — Layman script

*Read this out loud. No jargon required. Use it to understand the product, then to explain it.*

---

## Part 1 — What’s going on in cold email (30 seconds)

When you send cold email, two different things have to be healthy:

1. **The inbox** — Is the mailbox connected? Warming up? Landing in inbox or spam?
2. **The domain** — Does the internet trust that *your domain* is allowed to send that mail?

Instantly is great at **#1**.  
Setup Doctor is built for **#2**.

Most failed launches people blame on “deliverability” are actually a mix of both. If you only check Instantly, you can miss a broken domain.

---

## Part 2 — How Setup Doctor actually works (layman)

Think of Setup Doctor like a **mechanic for the domain’s ID cards**, not a gym for the inbox.

Email receivers (Gmail, Outlook, etc.) look up public DNS records on your sending domain and ask:

| Check | Simple meaning |
|---|---|
| **SPF** | “Which servers are allowed to send mail *as* this domain?” |
| **DKIM** | “Is there a cryptographic stamp so this wasn’t forged?” |
| **DMARC** | “If SPF/DKIM fail, what should happen — ignore, quarantine, or reject?” |
| **MX** | “Where should mail *to* this domain go?” |

Setup Doctor:

1. **Looks up those records** with real DNS checks (code — same inputs → same answers).
2. Turns each problem into a **Finding** — e.g. “SPF is missing” — with severity and a fix order.
3. Optionally rewrites the wording in plain English with an AI.
4. **Verifies** the AI didn’t invent new problems or fake numbers. If it did → fall back to a safe template.

Important: the AI does **not** decide what’s wrong. The checks do. That’s what “deterministic Findings” means.

If Instantly data is missing, Setup Doctor says **unknown** — it never paints a fake green “healthy.”

---

## Part 3 — What Instantly has (and what it doesn’t)

### Instantly *does* have
- Connected mailboxes / accounts  
- Warmup scores  
- Inbox placement tests  
- Tracking-domain status  
- Deliverability Agent (pause / act on send health)  
- Campaign activate  

Question Instantly answers well:  
**“Is this mailbox in a state where I can send?”**

### Instantly *does not* deeply own (the gap)
- A full **pre-launch DNS doctor** that walks SPF / DKIM / DMARC / MX as first-class Findings with fix order  
- Guaranteeing “warmup looks fine ⇒ domain auth is fine”  
- Sitting beside Instantly in the same AI chat as a **gate before activate** that refuses to lie when data is missing  

Instantly may show simple vitals (pass/fail style signals). That’s not the same as Setup Doctor’s deep, labeled Findings + verified explanation + “don’t activate yet” gate.

They are **teammates**, not replacements:

> Instantly runs outreach.  
> Setup Doctor makes sure the domain’s DNS won’t wreck the launch.

---

## Part 4 — How we tested that Instantly doesn’t fill this gap

We didn’t argue from a slide. We used a real Instantly API key and Setup Doctor’s own readiness tools.

### Test A — Empty Instantly workspace
- API key worked.  
- **0 accounts → 0 domains.**  
- Warmup/placement empty.  
- Deliverability Agent not deployed.  
- Result: `launch_verdict = unknown`.  

**What that proves:** Setup Doctor will not invent health when Instantly has nothing. Instantly also had nothing to diagnose DNS on — empty workspace ≠ “DNS is fine.”

### Test B — Added a real mailbox (personal Gmail)
- Instantly showed **1 account** (`…@gmail.com`).  
- Warmup present (score 0).  
- No inbox-placement test linked → compare = **unknown**.  
- Domain Instantly exposed = **`gmail.com`**.  

**What that proves:**
1. Instantly *does* give mailbox/warmup signals once an account exists.  
2. That still doesn’t give you a **custom sending domain** DNS story — `gmail.com` is Google’s domain, not a client domain you control.  
3. The Instantly gap we care about shows up on **agency/client domains** (you own DNS). Personal Gmail is a weak demo for DNS Findings — which itself shows Instantly’s account list ≠ deep DNS doctor.

### Test C — Offline “full picture” with fixtures (how the product behaves when Instantly *has* data)
Using recorded Instantly-shaped responses + broken DNS fixtures, Setup Doctor produced what Instantly alone doesn’t package as a launch gate:

- DNS Findings (SPF / DKIM / DMARC / MX missing)  
- Warmup vs placement **mismatches** (e.g. warmup looks strong, inbox % looks weak)  
- Vitals **agree / disagree** with deep DNS  
- `launch_verdict: caution` — don’t treat as ready  

**What that proves:** When Instantly-like signals and DNS both exist, Setup Doctor is the layer that **correlates** them and blocks a reckless activate. Instantly’s UI/API alone doesn’t replace that combined gate.

### Honest bottom line from testing
| Claim | Supported? |
|---|---|
| Instantly always deep-fixes SPF/DKIM/DMARC for you | **No** — we didn’t see that product job from the API/readiness path |
| Empty Instantly ⇒ Setup Doctor fakes healthy | **No** — it said unknown |
| Instantly account connected ⇒ DNS problem solved | **No** — Gmail account ≠ custom-domain DNS doctor |
| Setup Doctor + Instantly together is the pre-launch story | **Yes** — fixtures + live read path match the design |

---

## Part 5 — Why this is the best way (not “another Instantly”)

1. **Don’t compete with Instantly on warmup/placement.** They already own that. Duplicating it is worse for users.  
2. **Own the DNS pre-launch gap** Instantly users still hit — especially on **custom domains**.  
3. **Same place users already work** — dual MCP (Instantly MCP + Setup Doctor MCP) in Cursor / Claude / ChatGPT.  
4. **Honest when data is missing** — unknown / not_checked, never fake green. That builds trust with Instantly and agencies.  
5. **Read-only on Instantly** — Setup Doctor diagnoses; Instantly (or their Deliverability Agent) still activates/pauses. Clear lines = partner-friendly.  
6. **Deterministic Findings** — agencies and evals can trust the checklist; AI only explains.

---

## 60-second pitch (memorize this)

“Instantly tells you if the mailbox looks ready to send.  
Setup Doctor tells you if the *domain’s DNS* will let that mail be trusted — SPF, DKIM, DMARC, MX — as clear Findings, not vibes.  

We tested with a real Instantly key: empty workspace → unknown, not fake healthy.  
Connected Gmail → Instantly shows the account, but that’s not a custom-domain DNS doctor.  

So we don’t replace Instantly. We sit next to it as the pre-launch gate:  
if DNS Findings are serious, don’t activate yet.  

Instantly runs outreach. Setup Doctor keeps DNS from sabotaging the launch.”

---

## One-liner

**Instantly = mailbox health. Setup Doctor = domain DNS health. Together = safe to launch.**
