"""Public web checker HTML — Instantly-adjacent UX, same /diagnose engine."""

WEB_CHECK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Setup Doctor — DNS pre-launch for Instantly</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #faf9f7;
      --ink: #111111;
      --muted: #5c5c5c;
      --line: #ebe8e4;
      --panel: #ffffff;
      --instantly: #ff6b2c;
      --instantly-dark: #e2551a;
      --instantly-soft: rgba(255, 107, 44, 0.12);
      --doctor: #0d7a5f;
      --doctor-soft: rgba(13, 122, 95, 0.1);
      --good: #039855;
      --good-bg: #ecfdf3;
      --warn: #b54708;
      --warn-bg: #fffaeb;
      --bad: #d92d20;
      --bad-bg: #fef3f2;
      --sans: "Plus Jakarta Sans", system-ui, sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; color: var(--ink); font-family: var(--sans);
      background:
        radial-gradient(1100px 480px at 85% -10%, var(--instantly-soft) 0%, transparent 55%),
        radial-gradient(800px 420px at -5% 5%, var(--doctor-soft) 0%, transparent 50%),
        linear-gradient(180deg, #fff 0%, var(--bg) 40%);
    }
    .top {
      position: sticky; top: 0; z-index: 20;
      backdrop-filter: blur(12px);
      background: rgba(255,255,255,0.9);
      border-bottom: 1px solid var(--line);
      padding: 0.7rem 1.25rem;
      display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    }
    .brand-lockup {
      display: flex; align-items: baseline; gap: 0.4rem;
      font-weight: 800; letter-spacing: -0.03em; font-size: 1.05rem;
    }
    .brand-lockup .x { color: var(--muted); font-weight: 500; font-size: 0.95rem; }
    .brand-lockup .in { color: var(--instantly); }
    .nav { display: flex; align-items: center; flex-wrap: wrap; gap: 0.15rem; }
    .nav a {
      color: var(--muted); text-decoration: none; font-size: 0.88rem; font-weight: 600;
      padding: 0.4rem 0.65rem; border-radius: 8px;
    }
    .nav a:hover { color: var(--ink); background: rgba(0,0,0,0.03); }
    .nav a.primary {
      background: var(--instantly); color: #fff; padding: 0.5rem 0.95rem; margin-left: 0.35rem;
    }
    .nav a.primary:hover { background: var(--instantly-dark); color: #fff; }

    .wrap { max-width: 900px; margin: 0 auto; padding: 1.85rem 1.25rem 4rem; }

    .banner {
      display: none;
      margin-bottom: 1.15rem;
      border-radius: 12px;
      padding: 0.85rem 1.05rem;
      font-size: 0.88rem;
      line-height: 1.5;
    }
    .banner.show { display: block; animation: rise 0.4s ease both; }
    .banner code { font-family: var(--mono); font-size: 0.8em; }
    .banner.warn { border: 1px solid #f9dbaf; background: #fffaeb; color: #93370d; }
    .banner.info { border: 1px solid #cce3de; background: #f0faf6; color: #0d5c47; }
    .banner a { color: inherit; font-weight: 700; }

    .steps {
      display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem;
      margin-bottom: 1.5rem; animation: rise 0.5s ease both;
    }
    @media (max-width: 700px) { .steps { grid-template-columns: 1fr 1fr; } }
    .step {
      background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
      padding: 0.7rem 0.8rem; min-height: 100%;
    }
    .step .n {
      font-size: 0.68rem; font-weight: 800; letter-spacing: 0.06em;
      text-transform: uppercase; color: var(--instantly); margin: 0 0 0.25rem;
    }
    .step p { margin: 0; font-size: 0.82rem; color: var(--muted); line-height: 1.4; font-weight: 500; }
    .step strong { color: var(--ink); font-weight: 700; }

    .arch {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 0.85rem;
      margin-bottom: 1.85rem;
      animation: rise 0.55s ease both;
    }
    @media (max-width: 700px) {
      .arch { grid-template-columns: 1fr; }
      .arch .flow { transform: rotate(90deg); margin: 0.1rem auto; }
    }
    .arch-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 1.1rem 1.15rem;
      box-shadow: 0 1px 0 rgba(17,17,17,0.02);
      transition: transform 0.25s ease, box-shadow 0.25s ease;
    }
    .arch-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(17,17,17,0.06);
    }
    .arch-card .k {
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em;
      text-transform: uppercase; margin: 0 0 0.4rem;
    }
    .arch-card.instantly .k { color: var(--instantly); }
    .arch-card.doctor .k { color: var(--doctor); }
    .arch-card h2 { margin: 0 0 0.4rem; font-size: 1.08rem; letter-spacing: -0.025em; font-weight: 700; }
    .arch-card p { margin: 0; color: var(--muted); font-size: 0.88rem; line-height: 1.5; }
    .flow { align-self: center; color: var(--muted); font-weight: 700; font-size: 1.35rem; }

    .hero { animation: rise 0.65s 0.05s ease both; margin-bottom: 1.35rem; }
    .hero .eyebrow {
      display: inline-block; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.07em;
      text-transform: uppercase; color: var(--instantly); margin: 0 0 0.55rem;
    }
    .hero h1 {
      font-size: clamp(1.95rem, 4.8vw, 2.75rem);
      letter-spacing: -0.04em;
      line-height: 1.08;
      margin: 0 0 0.7rem;
      max-width: 14ch;
      font-weight: 800;
    }
    .hero .lede {
      margin: 0; color: var(--muted); font-size: 1.05rem; line-height: 1.55; max-width: 38rem;
    }

    form.check {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 1.2rem;
      box-shadow: 0 12px 40px rgba(17,17,17,0.04);
      animation: rise 0.7s 0.08s ease both;
    }
    .domain-row {
      display: grid; grid-template-columns: 1fr auto; gap: 0.65rem; align-items: end;
    }
    @media (max-width: 560px) { .domain-row { grid-template-columns: 1fr; } }
    .field label {
      display: block; font-size: 0.78rem; font-weight: 600; color: var(--muted);
      margin-bottom: 0.35rem;
    }
    .field input {
      width: 100%; border: 1px solid var(--line); border-radius: 10px;
      padding: 0.85rem 0.95rem; font: 500 1rem/1.2 var(--sans); color: var(--ink);
      background: #fff; outline: none; transition: border-color 0.15s, box-shadow 0.15s;
    }
    .field input:focus {
      border-color: var(--instantly);
      box-shadow: 0 0 0 3px var(--instantly-soft);
    }
    .field input.invalid {
      border-color: var(--bad);
      box-shadow: 0 0 0 3px rgba(217,45,32,0.12);
    }
    .field-msg {
      display: none; margin: 0.4rem 0 0; font-size: 0.82rem; color: var(--bad); line-height: 1.4;
    }
    .field-msg.show { display: block; }
    .cta {
      border: 0; border-radius: 10px; background: var(--instantly); color: #fff;
      font: 700 0.95rem/1 var(--sans); padding: 0.95rem 1.35rem; cursor: pointer;
      white-space: nowrap; transition: background 0.15s, transform 0.15s;
    }
    .cta:hover { background: var(--instantly-dark); }
    .cta:active { transform: scale(0.98); }
    .cta:disabled { opacity: 0.65; cursor: wait; }
    .opts {
      display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.95rem;
      font-size: 0.88rem; color: var(--muted); font-weight: 500;
    }
    .opts label { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; }
    .opts input { accent-color: var(--instantly); width: 1rem; height: 1rem; }
    .hint { margin: 0.85rem 0 0; color: var(--muted); font-size: 0.82rem; line-height: 1.45; }
    .hint code { font-family: var(--mono); font-size: 0.85em; }
    details.advanced { margin-top: 0.95rem; border-top: 1px solid var(--line); padding-top: 0.75rem; }
    details.advanced summary {
      cursor: pointer; font-size: 0.85rem; font-weight: 600; color: var(--muted);
      list-style: none;
    }
    details.advanced summary::-webkit-details-marker { display: none; }
    .advanced-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem;
    }
    @media (max-width: 560px) { .advanced-grid { grid-template-columns: 1fr; } }
    .key-help {
      margin: 0.75rem 0 0; padding: 0.75rem 0.85rem; border-radius: 10px;
      background: #f7f6f4; border: 1px solid var(--line);
      font-size: 0.82rem; color: var(--muted); line-height: 1.5;
    }
    .key-help strong { color: var(--ink); }
    .key-help a { color: var(--instantly-dark); font-weight: 700; }

    #out { margin-top: 1.35rem; animation: rise 0.4s ease both; }
    .result {
      background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
      padding: 1.2rem; box-shadow: 0 12px 40px rgba(17,17,17,0.04);
    }
    .verdict { margin-bottom: 1.1rem; }
    .verdict-kicker {
      margin: 0 0 0.35rem; font-size: 0.7rem; font-weight: 700;
      letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted);
    }
    .verdict-word {
      margin: 0 0 0.4rem; font-size: clamp(1.6rem, 3vw, 2rem);
      font-weight: 800; letter-spacing: -0.03em;
    }
    .verdict-word.clear { color: var(--good); }
    .verdict-word.blocked { color: var(--bad); }
    .verdict-word.caution { color: var(--warn); }
    .verdict-word.error { color: var(--bad); }
    .verdict-copy { margin: 0; color: var(--muted); line-height: 1.5; font-size: 0.95rem; }
    .meta-line { margin: 0.65rem 0 0; font-size: 0.78rem; color: var(--muted); font-family: var(--mono); }
    .next-steps {
      margin-top: 1rem; padding: 0.9rem 1rem; border-radius: 12px;
      background: #f7f6f4; border: 1px solid var(--line);
    }
    .next-steps h3 {
      margin: 0 0 0.45rem; font-size: 0.78rem; font-weight: 800;
      letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink);
    }
    .next-steps ol { margin: 0; padding-left: 1.15rem; color: var(--muted); font-size: 0.88rem; line-height: 1.55; }
    .next-steps li { margin: 0.25rem 0; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.55rem; margin-top: 0.9rem; }
    .actions a, .actions button {
      display: inline-flex; align-items: center; justify-content: center;
      border-radius: 9px; font: 700 0.85rem/1 var(--sans); padding: 0.65rem 0.95rem;
      text-decoration: none; cursor: pointer; border: 1px solid var(--line); background: #fff; color: var(--ink);
    }
    .actions a.primary, .actions button.primary {
      background: var(--instantly); color: #fff; border-color: var(--instantly);
    }
    .actions a.primary:hover, .actions button.primary:hover { background: var(--instantly-dark); }
    .section-title {
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase;
      color: var(--muted); margin: 1.15rem 0 0.65rem;
    }
    .finding {
      border: 1px solid var(--line); border-radius: 12px; padding: 0.85rem 0.95rem; margin-bottom: 0.55rem;
      border-left: 3px solid var(--line);
    }
    .finding.critical, .finding.high { border-left-color: var(--bad); background: var(--bad-bg); }
    .finding.medium { border-left-color: var(--warn); background: var(--warn-bg); }
    .finding.ok { border-left-color: var(--good); background: var(--good-bg); }
    .finding-id { font-family: var(--mono); font-size: 0.72rem; color: var(--muted); margin-right: 0.5rem; }
    .sev {
      display: inline-block; font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.04em; padding: 0.15rem 0.4rem; border-radius: 4px; background: #eee;
    }
    .sev.critical, .sev.high { background: #fee4e2; color: var(--bad); }
    .sev.medium { background: #fef0c7; color: var(--warn); }
    .finding-title { margin: 0.35rem 0 0.2rem; font-weight: 700; font-size: 0.95rem; }
    .finding-fix { margin: 0; color: var(--muted); font-size: 0.88rem; line-height: 1.45; }
    ul.signals { margin: 0; padding-left: 1.1rem; color: var(--muted); font-size: 0.9rem; line-height: 1.55; }
    ul.signals .unknown { color: var(--warn); }
    details.report { margin-top: 1rem; }
    details.report summary { cursor: pointer; font-weight: 600; font-size: 0.88rem; color: var(--muted); }
    pre.report-body {
      margin: 0.65rem 0 0; background: #111; color: #f5f5f5; border-radius: 10px;
      padding: 0.9rem 1rem; overflow: auto; font: 400 0.75rem/1.5 var(--mono);
    }
    .loading {
      display: flex; align-items: center; gap: 0.65rem; color: var(--muted);
      font-size: 0.95rem; padding: 1rem 0;
    }
    .spinner {
      width: 1.1rem; height: 1.1rem; border: 2px solid var(--line);
      border-top-color: var(--instantly); border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes rise {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: none; }
    }
    footer {
      margin-top: 2.75rem; padding-top: 1.15rem; border-top: 1px solid var(--line);
      color: var(--muted); font-size: 0.82rem; line-height: 1.55;
    }
    footer a { color: var(--instantly-dark); font-weight: 700; text-decoration: none; }
    footer a:hover { text-decoration: underline; }
    .split { color: var(--line); margin: 0 0.4rem; }
  </style>
</head>
<body>
  <header class="top">
    <div class="brand-lockup">
      <span class="sd">Setup Doctor</span>
      <span class="x">×</span>
      <span class="in">Instantly</span>
    </div>
    <nav class="nav">
      <a href="/connect">Connect</a>
      <a href="/schema">Schema</a>
      <a class="primary" href="/connect">Dual-MCP setup</a>
    </nav>
  </header>

  <div class="wrap">
    <div id="auth-banner" class="banner warn" data-auth-required="__AUTH_REQUIRED__"></div>

    <div class="steps" aria-label="How the pre-launch flow works">
      <div class="step"><p class="n">1</p><p><strong>Enter domain</strong> — your Instantly sending host</p></div>
      <div class="step"><p class="n">2</p><p><strong>Check DNS</strong> — SPF / DKIM / DMARC / MX Findings</p></div>
      <div class="step"><p class="n">3</p><p><strong>Fix blockers</strong> — paste records at your DNS host</p></div>
      <div class="step"><p class="n">4</p><p><strong>Activate in Instantly</strong> — only when DNS is clear</p></div>
    </div>

    <section class="arch" aria-label="How Setup Doctor fits Instantly">
      <div class="arch-card instantly">
        <p class="k">Instantly</p>
        <h2>Placement · warmup · activate</h2>
        <p>Mailbox vitals, inbox placement, Deliverability Agent. Owns campaign send decisions.</p>
      </div>
      <div class="flow" aria-hidden="true">→</div>
      <div class="arch-card doctor">
        <p class="k">Setup Doctor</p>
        <h2>SPF · DKIM · DMARC · MX</h2>
        <p>Deterministic DNS Findings Instantly can’t fully see. Read-only — never invents health.</p>
      </div>
    </section>

    <header class="hero">
      <p class="eyebrow">Pre-launch gate for Instantly GTM</p>
      <h1>Is this domain safe to launch?</h1>
      <p class="lede">
        Fix DNS blockers here, then activate in Instantly.
        Missing Instantly data stays <em>unknown</em> — never “healthy.”
      </p>
    </header>

    <form class="check" id="f" novalidate>
      <div class="domain-row">
        <div class="field">
          <label for="domain">Sending domain</label>
          <input id="domain" type="text" placeholder="send.yourcompany.com" required autocomplete="off" spellcheck="false" aria-describedby="domain-msg" />
          <p id="domain-msg" class="field-msg" role="alert"></p>
        </div>
        <button type="submit" class="cta" id="go">Check DNS</button>
      </div>
      <div class="opts">
        <label><input type="checkbox" id="instantly" /> Include Instantly signals</label>
        <label><input type="checkbox" id="advisory" /> Advisory DNS packs</label>
      </div>
      <p class="hint">Same engine as Instantly dual-MCP <code>pre_launch_gate</code> — Findings first, then signals.</p>
      <details class="advanced" id="advanced">
        <summary>Advanced — API keys</summary>
        <div class="advanced-grid">
          <div class="field">
            <label for="sdkey">Setup Doctor API key (X-API-Key)</label>
            <input id="sdkey" type="password" placeholder="Paste the key your host shared" autocomplete="off" />
          </div>
          <div class="field">
            <label for="ikey">Instantly API key (optional)</label>
            <input id="ikey" type="password" placeholder="From Instantly → Settings → Integrations" autocomplete="off" />
          </div>
        </div>
        <div class="key-help">
          <strong>Where do I get a Setup Doctor API key?</strong>
          There is no public signup. The person who hosts this app creates one with
          <code>SETUP_DOCTOR_API_KEYS=your-secret:tenant</code>
          (Fly: <code>fly secrets set …</code>) and shares that secret with you.
          Instantly keys come from your Instantly workspace — see
          <a href="/connect">Connect guide</a>.
        </div>
      </details>
    </form>

    <div id="out" hidden></div>

    <footer>
      Architecture: Instantly MCP (<code style="font-family:var(--mono);font-size:0.85em">mcp.instantly.ai</code>)
      + Setup Doctor MCP (<code style="font-family:var(--mono);font-size:0.85em">/mcp</code>).
      <a href="/connect">Connect guide</a><span class="split">·</span>
      <a href="/schema">Schema</a><span class="split">·</span>
      <a href="/healthz">Health</a>
      <br />Setup Doctor is read-only on Instantly — we never pause accounts or activate campaigns.
      Full docs: <a href="/connect">/connect</a> (mirrors <code style="font-family:var(--mono);font-size:0.85em">docs/INSTANTLY_CONNECT.md</code>).
    </footer>
  </div>

  <script>
    const AUTH_REQUIRED = "__AUTH_REQUIRED__" === "1";
    const STORAGE_SD = "sd_api_key";
    const STORAGE_IK = "sd_instantly_key";

    (function initBannersAndKeys() {
      const el = document.getElementById("auth-banner");
      if (el) {
        if (!AUTH_REQUIRED) {
          el.classList.add("show");
          el.innerHTML = "<strong>Open demo mode.</strong> Before sharing with Instantly, set "
            + "<code>SETUP_DOCTOR_API_KEYS=key:tenant</code> on the host, then paste that key under Advanced "
            + "(or use MCP <code>X-API-Key</code>).";
        } else {
          el.className = "banner info show";
          el.innerHTML = "<strong>API key required.</strong> Open <em>Advanced</em> below and paste the Setup Doctor key "
            + "your host shared. <a href=\\"#advanced\\" id=\\"open-advanced\\">Jump to keys</a> · "
            + "<a href=\\"/connect\\">How keys work</a>";
          document.getElementById("advanced")?.setAttribute("open", "");
        }
      }
      try {
        const sd = sessionStorage.getItem(STORAGE_SD);
        const ik = sessionStorage.getItem(STORAGE_IK);
        if (sd) document.getElementById("sdkey").value = sd;
        if (ik) document.getElementById("ikey").value = ik;
      } catch (_) {}
      document.getElementById("open-advanced")?.addEventListener("click", (e) => {
        e.preventDefault();
        const adv = document.getElementById("advanced");
        if (adv) adv.open = true;
        document.getElementById("sdkey")?.focus();
      });
    })();

    const form = document.getElementById("f");
    const out = document.getElementById("out");
    const domainInput = document.getElementById("domain");
    const domainMsg = document.getElementById("domain-msg");

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    function setDomainError(msg) {
      if (msg) {
        domainInput.classList.add("invalid");
        domainMsg.textContent = msg;
        domainMsg.classList.add("show");
      } else {
        domainInput.classList.remove("invalid");
        domainMsg.textContent = "";
        domainMsg.classList.remove("show");
      }
    }

    function normalizeDomain(raw) {
      let s = String(raw || "").trim().toLowerCase();
      s = s.replace(/^https?:\\/\\//, "").replace(/\\/$/, "");
      if (s.includes("/") || s.includes("?") || s.includes("@") || s.includes(" ")) {
        return { ok: false, msg: "Use only the hostname — not a URL or email. Example: send.yourcompany.com" };
      }
      if (!s) return { ok: false, msg: "Enter a sending domain (example: send.yourcompany.com)." };
      if (!s.includes(".")) return { ok: false, msg: "Use a full domain with a dot (example: send.yourcompany.com)." };
      return { ok: true, domain: s };
    }

    function detailText(detail) {
      if (detail == null) return "";
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail.map((d) => (typeof d === "string" ? d : (d.msg || JSON.stringify(d)))).join(" ");
      }
      if (typeof detail === "object" && detail.msg) return String(detail.msg);
      try { return JSON.stringify(detail); } catch (_) { return String(detail); }
    }

    function friendlyError(status, detail) {
      const raw = detailText(detail);
      const lower = raw.toLowerCase();
      if (status === 401 || lower.includes("api key")) {
        return {
          word: "API key needed",
          copy: raw || "This host requires a Setup Doctor API key.",
          steps: [
            "Ask the person who deployed Setup Doctor for the key from SETUP_DOCTOR_API_KEYS (not Instantly).",
            "Open Advanced below, paste it, and run Check DNS again.",
            "For MCP/Cursor, put the same value in X-API-Key — see Connect."
          ],
          actions: [
            { href: "#advanced", label: "Open API keys", primary: true, openAdvanced: true },
            { href: "/connect", label: "Connect guide" }
          ]
        };
      }
      if (status === 429) {
        return {
          word: "Slow down",
          copy: raw || "Too many checks in a short time.",
          steps: ["Wait about a minute.", "Run Check DNS once more."]
        };
      }
      if (status === 504 || lower.includes("timed out") || lower.includes("timeout")) {
        return {
          word: "DNS timed out",
          copy: raw || "Lookups took too long — no Findings were produced.",
          steps: [
            "A timeout is not the same as missing SPF/DKIM/DMARC.",
            "Retry in a moment. If it keeps failing, check the domain spelling."
          ],
          actions: [{ href: "#", label: "Try again", primary: true, retry: true }]
        };
      }
      if (status === 502 || lower.includes("resolver") || lower.includes("outage")) {
        return {
          word: "DNS unreachable",
          copy: raw || "We couldn't complete DNS lookups right now.",
          steps: [
            "This is an outage/reachability issue — not proof that records are missing.",
            "Retry shortly. If Instantly signals failed, uncheck them and check DNS only."
          ],
          actions: [{ href: "#", label: "Try again", primary: true, retry: true }]
        };
      }
      if (status === 400 || status === 422) {
        return {
          word: "Check the domain",
          copy: raw || "That domain couldn't be accepted.",
          steps: ["Paste a hostname like send.yourcompany.com — no https://."]
        };
      }
      if (status === 0 || !status) {
        return {
          word: "Connection problem",
          copy: raw || "Couldn't reach Setup Doctor. Check your network and try again.",
          steps: ["Confirm you're online.", "Reload the page, then Check DNS again."],
          actions: [{ href: "#", label: "Try again", primary: true, retry: true }]
        };
      }
      return {
        word: "Can't diagnose",
        copy: raw || "Something went wrong. No Findings were produced.",
        steps: ["Try again. If it persists, open Connect or ask your host to check /healthz."],
        actions: [
          { href: "#", label: "Try again", primary: true, retry: true },
          { href: "/healthz", label: "Health check" }
        ]
      };
    }

    function renderActions(actions) {
      if (!actions || !actions.length) return "";
      let html = `<div class="actions">`;
      for (const a of actions) {
        const cls = a.primary ? "primary" : "";
        const attrs = [];
        if (a.openAdvanced) attrs.push('data-open-advanced="1"');
        if (a.retry) attrs.push('data-retry="1"');
        if (a.href === "#" || a.retry || a.openAdvanced) {
          html += `<button type="button" class="${cls}" ${attrs.join(" ")}>${escapeHtml(a.label)}</button>`;
        } else {
          html += `<a class="${cls}" href="${escapeHtml(a.href)}">${escapeHtml(a.label)}</a>`;
        }
      }
      return html + `</div>`;
    }

    function renderErrorCard(err) {
      const steps = (err.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
      return `<div class="result">
        <div class="verdict">
          <p class="verdict-kicker">Something went wrong</p>
          <p class="verdict-word error">${escapeHtml(err.word)}</p>
          <p class="verdict-copy">${escapeHtml(err.copy)}</p>
        </div>
        ${steps ? `<div class="next-steps"><h3>What to do</h3><ol>${steps}</ol></div>` : ""}
        ${renderActions(err.actions)}
      </div>`;
    }

    function verdictFromFindings(findings) {
      if (!findings.length) {
        return {
          cls: "clear", word: "DNS clear",
          copy: "No SPF / DKIM / DMARC / MX Findings. Confirm Instantly placement, then activate in Instantly.",
          steps: [
            "Re-check Instantly mailbox vitals / inbox placement.",
            "Only then call Instantly activate_campaign (or activate in the Instantly UI).",
            "Optional: connect dual MCP so agents run pre_launch_gate before activate."
          ],
          actions: [
            { href: "/connect", label: "Dual-MCP connect", primary: true }
          ]
        };
      }
      const sev = findings.map((f) => f.severity);
      if (sev.includes("critical")) {
        return {
          cls: "blocked", word: "Blocked",
          copy: "Critical DNS Findings — do not call Instantly activate_campaign until these are fixed.",
          steps: [
            "Fix each Finding at your DNS provider (Cloudflare, Google Domains, etc.).",
            "Wait for DNS to propagate, then Check DNS again here.",
            "Keep Instantly campaigns paused until this page shows DNS clear."
          ]
        };
      }
      if (sev.includes("high") || sev.includes("medium")) {
        return {
          cls: "caution", word: "Needs fixes",
          copy: "High/medium Findings. Launch is risky — resolve DNS, then re-check Instantly vitals.",
          steps: [
            "Apply the suggested fixes in order of severity.",
            "Re-run Check DNS until critical/high are gone.",
            "Then confirm Instantly signals separately."
          ]
        };
      }
      return {
        cls: "caution", word: "Review",
        copy: "Low/info Findings only. Review, then confirm Instantly signals separately.",
        steps: ["Skim the Findings below.", "If acceptable, proceed to Instantly placement checks."]
      };
    }

    function renderSignals(signals) {
      if (!signals || !signals.instantly) return "";
      const rows = signals.instantly;
      if (!Array.isArray(rows) || !rows.length) {
        return `<p class="hint">Instantly checked — no account rows for this domain.</p>`;
      }
      let html = `<div class="section-title">Instantly signals</div><ul class="signals">`;
      for (const row of rows) {
        const v = escapeHtml(row.verdict || "unknown");
        const klass = v === "unknown" ? "unknown" : "";
        html += `<li class="${klass}"><strong>${escapeHtml(row.email || "account")}</strong> — ${v}${row.note ? ": " + escapeHtml(row.note) : ""}</li>`;
      }
      if ((signals.not_checked || []).length) {
        html += `<li class="unknown">Not checked: ${escapeHtml(signals.not_checked.join(", "))}</li>`;
      }
      return html + `</ul>`;
    }

    function renderFindings(findings) {
      if (!findings.length) {
        return `<div class="finding ok"><p class="finding-title">No auth Findings</p>
          <p class="finding-fix">DNS auth looks clear. Instantly still owns inbox placement.</p></div>`;
      }
      let html = `<div class="section-title">Findings to fix before Instantly activate</div>`;
      for (const f of findings) {
        const sev = escapeHtml(f.severity || "info");
        html += `<div class="finding ${sev}">
          <div><span class="finding-id">${escapeHtml(f.id || "")}</span><span class="sev ${sev}">${sev}</span></div>
          <p class="finding-title">${escapeHtml(f.title || "")}</p>
          <p class="finding-fix">${escapeHtml(f.fix || "")}</p>
        </div>`;
      }
      return html;
    }

    function wireResultActions(root) {
      root.querySelectorAll("[data-open-advanced]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const adv = document.getElementById("advanced");
          if (adv) adv.open = true;
          document.getElementById("sdkey")?.focus();
          adv?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      });
      root.querySelectorAll("[data-retry]").forEach((btn) => {
        btn.addEventListener("click", () => form.requestSubmit());
      });
    }

    domainInput.addEventListener("input", () => setDomainError(""));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const parsed = normalizeDomain(domainInput.value);
      if (!parsed.ok) {
        setDomainError(parsed.msg);
        domainInput.focus();
        return;
      }
      setDomainError("");
      const domain = parsed.domain;
      domainInput.value = domain;

      const btn = document.getElementById("go");
      btn.disabled = true;
      out.hidden = false;
      out.innerHTML = `<div class="loading"><span class="spinner"></span> Checking DNS for <strong style="color:var(--ink)">${escapeHtml(domain)}</strong>…</div>`;

      const headers = { "Content-Type": "application/json" };
      const sd = document.getElementById("sdkey").value.trim();
      const ik = document.getElementById("ikey").value.trim();
      if (sd) headers["X-API-Key"] = sd;
      if (ik) headers["X-Instantly-Api-Key"] = ik;
      try {
        if (sd) sessionStorage.setItem(STORAGE_SD, sd); else sessionStorage.removeItem(STORAGE_SD);
        if (ik) sessionStorage.setItem(STORAGE_IK, ik); else sessionStorage.removeItem(STORAGE_IK);
      } catch (_) {}

      if (AUTH_REQUIRED && !sd) {
        const adv = document.getElementById("advanced");
        if (adv) adv.open = true;
        out.innerHTML = renderErrorCard(friendlyError(401, "Setup Doctor API key required before we can check DNS."));
        wireResultActions(out);
        document.getElementById("sdkey")?.focus();
        btn.disabled = false;
        return;
      }

      try {
        const r = await fetch("/diagnose", {
          method: "POST",
          headers,
          body: JSON.stringify({
            domain,
            include_instantly: document.getElementById("instantly").checked,
            include_advisory: document.getElementById("advisory").checked,
          }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          out.innerHTML = renderErrorCard(friendlyError(r.status, data.detail || r.statusText));
          wireResultActions(out);
          if (r.status === 401) {
            document.getElementById("advanced").open = true;
            document.getElementById("sdkey")?.focus();
          }
          if (r.status === 400) setDomainError(detailText(data.detail) || "Check the domain format.");
          return;
        }
        const findings = data.findings || [];
        const v = verdictFromFindings(findings);
        const steps = (v.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
        out.innerHTML = `<div class="result">
          <div class="verdict">
            <p class="verdict-kicker">Pre-launch · Setup Doctor DNS</p>
            <p class="verdict-word ${v.cls}">${v.word}</p>
            <p class="verdict-copy">${escapeHtml(v.copy)}</p>
            <p class="meta-line">${escapeHtml(data.domain || domain)} · schema ${escapeHtml(data.schema_version || "1.0")} · ${findings.length} finding(s)</p>
          </div>
          ${renderFindings(findings)}
          ${renderSignals(data.signals)}
          ${steps ? `<div class="next-steps"><h3>Next steps</h3><ol>${steps}</ol></div>` : ""}
          ${renderActions(v.actions)}
          ${data.report ? `<details class="report"><summary>Full report</summary><pre class="report-body">${escapeHtml(data.report)}</pre></details>` : ""}
        </div>`;
        wireResultActions(out);
        out.querySelector(".result")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) {
        out.innerHTML = renderErrorCard(friendlyError(0, String(err)));
        wireResultActions(out);
      } finally {
        btn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def render_web_check_html(*, auth_required: bool) -> str:
    """Inject whether public API auth is currently required."""
    return WEB_CHECK_HTML.replace("__AUTH_REQUIRED__", "1" if auth_required else "0")
