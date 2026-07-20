"""Minimal fleet health page (Phase G)."""


def render_fleet() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>DriveAuth Edge — Fleet health</title>
  <style>
    :root {
      --bg: #0b1220;
      --panel: #121a2b;
      --text: #e8eef9;
      --muted: #9aa8c7;
      --accent: #38bdf8;
      --ok: #34d399;
      --bad: #f87171;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #1a2744, var(--bg));
      color: var(--text); min-height: 100vh;
    }
    .wrap { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
    h1 { font-size: 1.35rem; margin: 0; letter-spacing: 0.02em; }
    h1 span { color: var(--accent); }
    .sub { color: var(--muted); font-size: 0.9rem; margin-top: 0.25rem; }
    nav a {
      color: var(--text); text-decoration: none; margin-right: 0.75rem;
      border: 1px solid #243352; padding: 0.35rem 0.7rem; border-radius: 6px;
    }
    nav a.active { border-color: var(--accent); color: var(--accent); }
    .panel {
      margin-top: 1.5rem; background: var(--panel); border: 1px solid #243352;
      border-radius: 10px; padding: 1.25rem;
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.75rem; }
    .metric { background: #0d1526; border-radius: 8px; padding: 0.9rem; }
    .metric .label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; }
    .metric .value { font-size: 1.6rem; margin-top: 0.35rem; font-variant-numeric: tabular-nums; }
    .ok { color: var(--ok); } .bad { color: var(--bad); }
    pre {
      background: #0d1526; padding: 0.9rem; border-radius: 8px; overflow: auto;
      font-size: 0.8rem; color: #c6d4f0;
    }
    p.note { color: var(--muted); font-size: 0.85rem; line-height: 1.45; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>DriveAuth <span>Fleet</span></h1>
        <div class="sub">Auth rates · sensor flags · firmware — no biometric payloads</div>
      </div>
      <nav aria-label="Pipeline pages">
        <a href="/manual">Manual</a>
        <a href="/standalone">Standalone</a>
        <a href="/register">Register</a>
        <a class="active" href="/fleet">Fleet</a>
      </nav>
    </header>
    <section class="panel">
      <p class="note">
        Opt-in telemetry via <code>DRIVEAUTH_FLEET_TELEMETRY_URL</code>.
        This view aggregates local audit decision counts and sensor availability
        flags only — templates, embeddings, and transcripts are never included.
      </p>
      <div class="grid" id="metrics">
        <div class="metric"><div class="label">Accept</div><div class="value" id="m_accept">—</div></div>
        <div class="metric"><div class="label">Reject</div><div class="value" id="m_reject">—</div></div>
        <div class="metric"><div class="label">Step-up</div><div class="value" id="m_step">—</div></div>
        <div class="metric"><div class="label">Accept rate</div><div class="value" id="m_rate">—</div></div>
        <div class="metric"><div class="label">Firmware</div><div class="value" id="m_fw" style="font-size:1rem">—</div></div>
      </div>
      <h3 style="margin-top:1.25rem;font-size:0.95rem;color:var(--muted)">Sensors</h3>
      <div class="grid" id="sensors"></div>
      <h3 style="margin-top:1.25rem;font-size:0.95rem;color:var(--muted)">Last payload</h3>
      <pre id="payload">Loading…</pre>
    </section>
  </div>
  <script>
    async function refresh() {
      const res = await fetch("/api/fleet/health");
      const data = await res.json();
      const a = data.auth || {};
      $("m_accept").textContent = a.accept ?? 0;
      $("m_reject").textContent = a.reject ?? 0;
      $("m_step").textContent = a.step_up ?? 0;
      const rate = a.accept_rate != null ? (100 * a.accept_rate).toFixed(1) + "%" : "—";
      $("m_rate").textContent = rate;
      $("m_fw").textContent = data.firmware_version || "—";
      const sens = $("sensors");
      sens.innerHTML = "";
      const flags = data.sensors || {};
      Object.keys(flags).forEach((k) => {
        const el = document.createElement("div");
        el.className = "metric";
        el.innerHTML = '<div class="label">' + k + '</div><div class="value ' +
          (flags[k] ? "ok" : "bad") + '">' + (flags[k] ? "up" : "down") + "</div>";
        sens.appendChild(el);
      });
      $("payload").textContent = JSON.stringify(data, null, 2);
    }
    function $(id) { return document.getElementById(id); }
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""
