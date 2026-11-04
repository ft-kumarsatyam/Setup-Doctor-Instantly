"""Minimal public web checker HTML — calls the same /diagnose API (no parallel DNS)."""

WEB_CHECK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Setup Doctor — DNS pre-launch check</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a222c;
      --ink: #e8eef4;
      --muted: #8b9aab;
      --accent: #3d9cf0;
      --good: #3ecf8e;
      --bad: #f07178;
      --warn: #e6b450;
      --mono: "IBM Plex Mono", ui-monospace, monospace;
      --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh;
      font-family: var(--sans);
      background: radial-gradient(1200px 600px at 10% -10%, #1c3a5a 0%, transparent 55%),
                  radial-gradient(900px 500px at 100% 0%, #243028 0%, transparent 50%),
                  var(--bg);
      color: var(--ink);
    }
    main { max-width: 720px; margin: 0 auto; padding: 3rem 1.25rem 4rem; }
    .brand { font-size: 0.85rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); }
    h1 { font-size: 2rem; font-weight: 600; margin: 0.4rem 0 0.5rem; line-height: 1.15; }
    .lede { color: var(--muted); margin: 0 0 1.75rem; max-width: 36rem; }
    form {
      display: grid; gap: 0.75rem;
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      border: 1px solid #2a3542; border-radius: 12px; padding: 1.25rem;
      backdrop-filter: blur(8px);
    }
    label { font-size: 0.8rem; color: var(--muted); }
    input[type=text], input[type=password] {
      width: 100%; padding: 0.7rem 0.85rem; border-radius: 8px;
      border: 1px solid #334155; background: #0c1117; color: var(--ink);
      font-family: var(--mono); font-size: 0.95rem;
    }
    .row { display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: center; }
    .row label { display: flex; gap: 0.4rem; align-items: center; color: var(--ink); font-size: 0.9rem; }
    button {
      justify-self: start; margin-top: 0.25rem;
      background: var(--accent); color: #041018; border: 0;
      font-weight: 600; padding: 0.7rem 1.2rem; border-radius: 8px; cursor: pointer;
    }
    button:disabled { opacity: 0.5; cursor: wait; }
    #out { margin-top: 1.5rem; }
    .finding {
      border-left: 3px solid var(--warn); padding: 0.65rem 0.85rem; margin: 0.5rem 0;
      background: var(--panel); border-radius: 0 8px 8px 0;
    }
    .finding.critical { border-color: var(--bad); }
    .finding.ok { border-color: var(--good); }
    .meta { font-family: var(--mono); font-size: 0.8rem; color: var(--muted); }
    pre {
      white-space: pre-wrap; background: #0c1117; border-radius: 8px;
      padding: 1rem; border: 1px solid #2a3542; font-size: 0.8rem;
    }
    footer { margin-top: 2.5rem; color: var(--muted); font-size: 0.85rem; }
    a { color: var(--accent); }
  </style>
</head>
<body>
  <main>
    <div class="brand">Setup Doctor</div>
    <h1>DNS pre-launch check</h1>
    <p class="lede">
      Deterministic SPF / DKIM / DMARC / MX Findings for Instantly GTM launches.
      Instantly owns placement and warmup — we never invent health when data is missing.
    </p>
    <form id="f">
      <div>
        <label for="domain">Domain</label>
        <input id="domain" name="domain" type="text" placeholder="send.example.com" required autocomplete="off" />
      </div>
      <div class="row">
        <label><input type="checkbox" id="instantly" /> Include Instantly signals</label>
        <label><input type="checkbox" id="advisory" /> Advisory packs</label>
      </div>
      <div>
        <label for="sdkey">Setup Doctor API key (if required)</label>
        <input id="sdkey" type="password" placeholder="X-API-Key" autocomplete="off" />
      </div>
      <div>
        <label for="ikey">Instantly API key (optional header)</label>
        <input id="ikey" type="password" placeholder="X-Instantly-Api-Key" autocomplete="off" />
      </div>
      <button type="submit" id="go">Diagnose</button>
    </form>
    <div id="out" hidden></div>
    <footer>
      Same engine as CLI / MCP / API.
      <a href="/schema">Schema</a> ·
      <a href="https://github.com/">Instantly dual-MCP connect docs on the host</a>
    </footer>
  </main>
  <script>
    const form = document.getElementById("f");
    const out = document.getElementById("out");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("go");
      btn.disabled = true;
      out.hidden = false;
      out.innerHTML = "<p class='meta'>Running diagnose…</p>";
      const headers = { "Content-Type": "application/json" };
      const sd = document.getElementById("sdkey").value.trim();
      const ik = document.getElementById("ikey").value.trim();
      if (sd) headers["X-API-Key"] = sd;
      if (ik) headers["X-Instantly-Api-Key"] = ik;
      try {
        const r = await fetch("/diagnose", {
          method: "POST",
          headers,
          body: JSON.stringify({
            domain: document.getElementById("domain").value.trim(),
            include_instantly: document.getElementById("instantly").checked,
            include_advisory: document.getElementById("advisory").checked,
          }),
        });
        const data = await r.json();
        if (!r.ok) {
          out.innerHTML = `<p class='finding critical'>${data.detail || r.statusText}</p>`;
          return;
        }
        const findings = data.findings || [];
        let html = `<p class='meta'>schema ${data.schema_version} · ${data.domain} · ${findings.length} finding(s)</p>`;
        if (!findings.length) {
          html += `<div class='finding ok'><strong>No auth Findings</strong> — still confirm Instantly placement separately.</div>`;
        } else {
          for (const f of findings) {
            html += `<div class='finding ${f.severity === "critical" ? "critical" : ""}'>
              <strong>[${f.id}]</strong> (${f.severity}) ${f.title}<br/><span class='meta'>${f.fix || ""}</span>
            </div>`;
          }
        }
        if (data.report) html += `<pre>${escapeHtml(data.report)}</pre>`;
        out.innerHTML = html;
      } catch (err) {
        out.innerHTML = `<p class='finding critical'>${escapeHtml(String(err))}</p>`;
      } finally {
        btn.disabled = false;
      }
    });
    function escapeHtml(s) {
      return s.replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;" }[c]));
    }
  </script>
</body>
</html>
"""
