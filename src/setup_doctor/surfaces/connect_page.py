"""Hosted Instantly dual-MCP connect page (HTML) — mirrors docs/INSTANTLY_CONNECT.md."""

CONNECT_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Connect Instantly + Setup Doctor</title>
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
      --sans: "Plus Jakarta Sans", system-ui, sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: var(--sans); color: var(--ink);
      background:
        radial-gradient(900px 400px at 100% 0%, var(--instantly-soft) 0%, transparent 55%),
        radial-gradient(700px 360px at 0% 0%, var(--doctor-soft) 0%, transparent 50%),
        var(--bg);
    }
    .top {
      border-bottom: 1px solid var(--line); background: rgba(255,255,255,0.92);
      backdrop-filter: blur(10px);
      padding: 0.75rem 1.25rem; display: flex; align-items: center; justify-content: space-between; gap: 1rem;
      position: sticky; top: 0; z-index: 10;
    }
    .top a { color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600; margin-left: 1rem; }
    .top a:hover { color: var(--ink); }
    .logo { font-weight: 800; letter-spacing: -0.03em; }
    .logo span { color: var(--instantly); }
    main { max-width: 820px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
    .eyebrow {
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--instantly); margin: 0 0 0.55rem;
    }
    h1 {
      font-size: clamp(1.9rem, 4.2vw, 2.55rem); letter-spacing: -0.04em;
      margin: 0 0 0.75rem; line-height: 1.1; font-weight: 800;
    }
    .lede { color: var(--muted); font-size: 1.05rem; line-height: 1.55; margin: 0 0 2rem; max-width: 40rem; }
    .pair {
      display: grid; grid-template-columns: 1fr auto 1fr; gap: 0.85rem; align-items: stretch; margin-bottom: 2rem;
    }
    @media (max-width: 640px) { .pair { grid-template-columns: 1fr; } .pair .plus { display: none; } }
    .box {
      background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 1.15rem 1.25rem;
      box-shadow: 0 1px 0 rgba(17,17,17,0.02);
      transition: transform 0.25s ease, box-shadow 0.25s ease;
    }
    .box:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(17,17,17,0.06); }
    .box .k {
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; margin: 0 0 0.35rem;
    }
    .box.instantly .k { color: var(--instantly); }
    .box.doctor .k { color: var(--doctor); }
    .box h2 { margin: 0 0 0.4rem; font-size: 1.05rem; letter-spacing: -0.02em; }
    .box p { margin: 0; color: var(--muted); font-size: 0.9rem; line-height: 1.5; }
    .plus { align-self: center; font-weight: 800; color: var(--muted); text-align: center; font-size: 1.25rem; }
    h3 { font-size: 1.05rem; margin: 2rem 0 0.75rem; letter-spacing: -0.02em; }
    ol, ul { margin: 0; padding-left: 1.2rem; color: var(--ink); line-height: 1.6; }
    li { margin: 0.4rem 0; }
    pre, code { font-family: var(--mono); }
    code { font-size: 0.88em; }
    pre {
      background: #111; color: #f5f5f5; border-radius: 12px; padding: 1rem 1.1rem;
      overflow: auto; font-size: 0.78rem; line-height: 1.5;
    }
    .note {
      border-left: 3px solid var(--instantly); padding: 0.85rem 0 0.85rem 1rem;
      color: var(--muted); font-size: 0.92rem; margin: 1.25rem 0; background: rgba(255,107,44,0.04);
      border-radius: 0 10px 10px 0;
    }
    .cta-row { display: flex; flex-wrap: wrap; gap: 0.65rem; margin-top: 1.75rem; }
    .btn {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 0.75rem 1.15rem; border-radius: 10px; font-weight: 700; font-size: 0.9rem; text-decoration: none;
    }
    .btn-primary { background: var(--instantly); color: #fff; }
    .btn-primary:hover { background: var(--instantly-dark); }
    .btn-secondary { background: #fff; color: var(--ink); border: 1px solid var(--line); }
    .btn-secondary:hover { border-color: #ccc; }
  </style>
</head>
<body>
  <div class="top">
    <div class="logo">Setup Doctor <span>×</span> Instantly</div>
    <nav>
      <a href="/">DNS check</a>
      <a href="/schema">Schema</a>
    </nav>
  </div>
  <main>
    <p class="eyebrow">docs/INSTANTLY_CONNECT.md · live on this host</p>
    <h1>Connect Instantly MCP + Setup Doctor MCP</h1>
    <p class="lede">
      Same agent chat. Instantly owns placement, warmup, and activate.
      Setup Doctor owns deterministic SPF / DKIM / DMARC / MX Findings — never invents healthy when data is missing.
    </p>

    <div class="pair">
      <div class="box instantly">
        <p class="k">Instantly MCP</p>
        <h2>mcp.instantly.ai</h2>
        <p>Accounts, vitals, campaigns. Use for mailbox/placement state and activate (carefully).</p>
      </div>
      <div class="plus">+</div>
      <div class="box doctor">
        <p class="k">Setup Doctor MCP</p>
        <h2 id="mcp-url-label">/mcp</h2>
        <p><code>diagnose</code>, <code>instantly_ready</code>, <code>pre_launch_gate</code>, <code>campaign_desk</code>, <code>reply_desk</code>. DNS blocks activate. Campaign Desk explains a stall. Reply Desk lists unread mail.</p>
      </div>
    </div>

    <div class="note">
      Before Instantly <code>activate_campaign</code>: run Setup Doctor <code>pre_launch_gate</code>.
      If Findings are critical/high — fix DNS first. Missing Instantly scores stay <strong>unknown</strong>, never healthy.
    </div>

    <h3>1. Hosted endpoints on this server</h3>
    <ul>
      <li>Web check: <a href="/">/</a></li>
      <li>Health: <a href="/healthz">/healthz</a></li>
      <li>MCP (streamable HTTP): <code id="mcp-url">/mcp</code> — use this exact HTTPS URL (no bare HTTP; trailing slash optional)</li>
      <li>API: <code>POST /diagnose</code>, <code>POST /instantly/ready</code>, <code>POST /instantly/pre-launch-gate</code>, <code>POST /instantly/campaign-desk</code>, <code>POST /instantly/reply-desk</code></li>
    </ul>

    <h3>2. Where do the API keys come from?</h3>
    <div class="note">
      <strong>Setup Doctor API key</strong> — there is <em>no</em> public signup or dashboard.
      The person who hosts this app invents a secret and sets
      <code>SETUP_DOCTOR_API_KEYS=your-secret:tenant</code>
      (Fly: <code>fly secrets set SETUP_DOCTOR_API_KEYS='…'</code>), then shares that secret with Instantly / agents.
      Paste it as <code>X-API-Key</code> on the checker (Advanced), API, or MCP.
      <br /><br />
      <strong>Instantly API key</strong> — from your Instantly workspace
      (Settings → Integrations / API). Optional header <code>X-Instantly-Api-Key</code>,
      or store via <code>POST /connect/instantly</code> (vault).
    </div>

    <h3>3. Cursor dual MCP</h3>
    <pre id="mcp-json">{
  "mcpServers": {
    "instantly": {
      "url": "https://mcp.instantly.ai/mcp",
      "headers": { "Authorization": "Bearer YOUR_INSTANTLY_KEY" }
    },
    "setup-doctor": {
      "url": "MCP_URL_HERE",
      "headers": {
        "X-API-Key": "YOUR_SETUP_DOCTOR_KEY",
        "X-Instantly-Api-Key": "YOUR_INSTANTLY_KEY"
      }
    }
  }
}</pre>

    <h3>4. Agent rule</h3>
    <ol>
      <li>Call Setup Doctor <code>pre_launch_gate</code> (or <code>instantly_ready</code>).</li>
      <li>Present Findings first, Instantly mismatches second, unknowns honestly.</li>
      <li>Do <strong>not</strong> activate Instantly campaigns while critical/high Findings remain.</li>
      <li>Setup Doctor never pauses accounts — quote Instantly Deliverability Agent if it recommends pause.</li>
    </ol>

    <div class="cta-row">
      <a class="btn btn-primary" href="/">Run a DNS check</a>
      <a class="btn btn-secondary" href="/schema">View API schema</a>
    </div>
  </main>
  <script>
    const origin = location.origin;
    const mcp = origin + "/mcp";
    document.getElementById("mcp-url").textContent = mcp;
    const label = document.getElementById("mcp-url-label");
    if (label) label.textContent = mcp.replace("https://", "").replace("http://", "");
    document.getElementById("mcp-json").textContent =
      document.getElementById("mcp-json").textContent.replace("MCP_URL_HERE", mcp);
  </script>
</body>
</html>
"""
