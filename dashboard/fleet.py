"""Fleet health page (Phase G) + local perf panel — aligned with Manual UI."""


def render_fleet() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>DriveAuth Edge — Fleet health</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg0: #060a10;
      --bg1: #0b1220;
      --panel: rgba(14, 22, 36, 0.82);
      --panel-solid: #0e1624;
      --border: #243247;
      --border-bright: #35506e;
      --text: #e7eef8;
      --muted: #8fa3bc;
      --faint: #5d7290;
      --cyan: #2dd4bf;
      --sky: #38bdf8;
      --accept: #34d399;
      --reject: #f87171;
      --stepup: #fbbf24;
      --glow: 0 0 40px rgba(45, 212, 191, 0.12);
      --radius: 14px;
      --font: "Sora", system-ui, sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font);
      color: var(--text);
      min-height: 100vh;
      background:
        radial-gradient(ellipse 900px 420px at 12% -8%, rgba(45, 212, 191, 0.16), transparent 55%),
        radial-gradient(ellipse 700px 380px at 92% 0%, rgba(56, 189, 248, 0.12), transparent 50%),
        linear-gradient(180deg, var(--bg1), var(--bg0));
      line-height: 1.5;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(143, 163, 188, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(143, 163, 188, 0.045) 1px, transparent 1px);
      background-size: 48px 48px;
      mask-image: radial-gradient(ellipse 80% 70% at 50% 30%, black, transparent);
      z-index: 0;
    }
    .wrap { position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; padding: 0 1.5rem 2.5rem; }
    header {
      padding: 1.1rem 0;
      border-bottom: 1px solid rgba(36, 50, 71, 0.9);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      backdrop-filter: blur(14px);
      background: rgba(6, 10, 16, 0.7);
      position: sticky;
      top: 0;
      z-index: 20;
      margin: 0 -1.5rem;
      padding-left: 1.5rem;
      padding-right: 1.5rem;
    }
    .brand { display: flex; align-items: center; gap: 0.85rem; }
    .logo {
      width: 42px; height: 42px;
      border-radius: 12px;
      background:
        linear-gradient(145deg, rgba(45,212,191,0.35), rgba(56,189,248,0.15)),
        var(--panel-solid);
      border: 1px solid rgba(45, 212, 191, 0.35);
      display: grid; place-items: center;
      box-shadow: var(--glow);
      font-family: var(--mono);
      font-weight: 600;
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      color: var(--cyan);
    }
    header h1 {
      font-size: 1.2rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.15;
    }
    header h1 span { color: var(--cyan); }
    header .sub { color: var(--muted); font-size: 0.78rem; margin-top: 0.15rem; }
    .nav-tabs { display: flex; flex-wrap: wrap; gap: 0.45rem; }
    .nav-link {
      color: var(--sky);
      text-decoration: none;
      font-size: 0.82rem;
      font-weight: 500;
      border: 1px solid var(--border);
      padding: 0.42rem 0.8rem;
      border-radius: 999px;
      background: var(--panel);
      transition: border-color 0.2s, background 0.2s;
    }
    .nav-link:hover { border-color: var(--sky); background: rgba(56,189,248,0.08); }
    .nav-link.active {
      border-color: rgba(45, 212, 191, 0.55);
      color: var(--cyan);
      background: rgba(45, 212, 191, 0.1);
    }
    .panel {
      margin-top: 1.25rem;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem;
      backdrop-filter: blur(8px);
    }
    .panel h2 {
      font-size: 0.95rem;
      font-weight: 600;
      letter-spacing: -0.02em;
      margin-bottom: 0.35rem;
    }
    .panel h3 {
      margin-top: 1.35rem;
      margin-bottom: 0.65rem;
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }
    .panel h3:first-of-type { margin-top: 1rem; }
    p.note {
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.45;
      margin-bottom: 1rem;
    }
    p.note code, .meta code {
      font-family: var(--mono);
      font-size: 0.75rem;
      color: #c4d4f0;
      background: rgba(0,0,0,0.3);
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.75rem;
    }
    .metric {
      background: rgba(13, 21, 38, 0.85);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.9rem;
    }
    .metric .label {
      color: var(--muted);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .metric .value {
      font-size: 1.45rem;
      margin-top: 0.35rem;
      font-variant-numeric: tabular-nums;
      font-family: var(--mono);
      font-weight: 500;
    }
    .metric .value.sm { font-size: 0.95rem; word-break: break-all; }
    .ok { color: var(--accept); }
    .bad { color: var(--reject); }
    .warn { color: var(--stepup); }
    .meta {
      margin-top: 1rem;
      font-size: 0.78rem;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem 1.25rem;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      font-size: 0.72rem;
      font-family: var(--mono);
    }
    .chip.up { border-color: rgba(52,211,153,0.4); color: var(--accept); }
    .chip.down { border-color: rgba(248,113,113,0.4); color: var(--reject); }
    table.recent {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
      font-family: var(--mono);
    }
    table.recent th {
      text-align: left;
      color: var(--muted);
      font-weight: 500;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.45rem 0.5rem;
      border-bottom: 1px solid var(--border);
    }
    table.recent td {
      padding: 0.5rem;
      border-bottom: 1px solid rgba(36, 50, 71, 0.6);
      font-variant-numeric: tabular-nums;
      color: #c4d4f0;
    }
    table.recent tr:last-child td { border-bottom: none; }
    table.recent .empty {
      color: var(--faint);
      text-align: center;
      padding: 1.25rem 0.5rem;
      font-family: var(--font);
    }
    details.raw {
      margin-top: 1.25rem;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: rgba(13, 21, 38, 0.6);
      overflow: hidden;
    }
    details.raw summary {
      cursor: pointer;
      padding: 0.75rem 1rem;
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--sky);
      list-style: none;
      user-select: none;
    }
    details.raw summary::-webkit-details-marker { display: none; }
    details.raw summary::before {
      content: "▸ ";
      color: var(--faint);
      font-family: var(--mono);
    }
    details.raw[open] summary::before { content: "▾ "; }
    details.raw pre {
      margin: 0;
      padding: 0 1rem 1rem;
      overflow: auto;
      font-size: 0.72rem;
      font-family: var(--mono);
      color: #c6d4f0;
      max-height: 320px;
    }
    .refresh-hint {
      font-size: 0.72rem;
      color: var(--faint);
      margin-top: 0.75rem;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="brand">
        <div class="logo">DA</div>
        <div>
          <h1>DriveAuth <span>Fleet</span></h1>
          <div class="sub">Auth rates · sensor flags · inference latency — no biometric payloads</div>
        </div>
      </div>
      <nav class="nav-tabs" aria-label="Pipeline pages">
        <a class="nav-link" href="/manual">Manual pipeline</a>
        <a class="nav-link" href="/standalone">Standalone pay</a>
        <a class="nav-link" href="/register">Register driver</a>
        <a class="nav-link active" href="/fleet">Fleet health</a>
      </nav>
    </header>

    <section class="panel">
      <h2>Local fleet snapshot</h2>
      <p class="note">
        Opt-in remote telemetry via <code>DRIVEAUTH_FLEET_TELEMETRY_URL</code>.
        Local perf CSV is always-on (<code>DRIVEAUTH_PERF_LOG</code>) and separate
        from the security audit log.
      </p>
      <div class="meta" id="health-meta">
        <span>Vehicle <code id="m_vehicle">—</code></span>
        <span>Firmware <code id="m_fw">—</code></span>
      </div>
      <h3>Auth outcomes</h3>
      <div class="grid" id="metrics">
        <div class="metric"><div class="label">Accept</div><div class="value ok" id="m_accept">—</div></div>
        <div class="metric"><div class="label">Reject</div><div class="value bad" id="m_reject">—</div></div>
        <div class="metric"><div class="label">Step-up</div><div class="value warn" id="m_step">—</div></div>
        <div class="metric"><div class="label">Accept rate</div><div class="value" id="m_rate">—</div></div>
      </div>
      <h3>Sensors</h3>
      <div class="grid" id="sensors"></div>
    </section>

    <section class="panel">
      <h2>Inference latency</h2>
      <div class="meta" id="perf-meta">
        <span>Perf <code id="p_enabled">—</code></span>
        <span>Recent decisions <code id="p_count">—</code></span>
        <span>Log <code id="p_path">—</code></span>
      </div>
      <h3>Average ms (recent)</h3>
      <div class="grid" id="latency">
        <div class="metric"><div class="label">Voice</div><div class="value" id="l_voice">—</div></div>
        <div class="metric"><div class="label">Face</div><div class="value" id="l_face">—</div></div>
        <div class="metric"><div class="label">Finger</div><div class="value" id="l_finger">—</div></div>
        <div class="metric"><div class="label">Liveness</div><div class="value" id="l_live">—</div></div>
        <div class="metric"><div class="label">Total</div><div class="value" id="l_total">—</div></div>
        <div class="metric"><div class="label">Face backend</div><div class="value sm" id="l_backend">—</div></div>
      </div>
      <h3>Host utilization</h3>
      <div class="grid" id="util">
        <div class="metric"><div class="label">CPU %</div><div class="value" id="u_cpu">—</div></div>
        <div class="metric"><div class="label">RAM %</div><div class="value" id="u_ram">—</div></div>
        <div class="metric"><div class="label">RAM used MB</div><div class="value" id="u_mb">—</div></div>
      </div>
      <h3>Recent decisions</h3>
      <div style="overflow-x:auto">
        <table class="recent" id="recent-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Decision</th>
              <th>Voice</th>
              <th>Face</th>
              <th>Finger</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody id="recent-body">
            <tr><td colspan="6" class="empty">No recent decision rows yet — run an auth on Manual or Standalone.</td></tr>
          </tbody>
        </table>
      </div>
      <details class="raw">
        <summary>Raw health + perf payload</summary>
        <pre id="payload">Loading…</pre>
      </details>
      <p class="refresh-hint">Auto-refreshes every 5s</p>
    </section>
  </div>
  <script>
    function $(id) { return document.getElementById(id); }
    function fmtMs(v) {
      if (v == null || v === "") return "—";
      const n = Number(v);
      return Number.isFinite(n) ? n.toFixed(1) : "—";
    }
    function fmtNum(v) {
      if (v == null || v === "") return "—";
      const n = Number(v);
      return Number.isFinite(n) ? n.toFixed(1) : "—";
    }
    function shortTs(ts) {
      if (!ts) return "—";
      const s = String(ts);
      return s.length > 19 ? s.slice(11, 19) + "Z" : s;
    }
    function decisionClass(d) {
      const x = String(d || "").toLowerCase();
      if (x === "accept") return "ok";
      if (x === "reject") return "bad";
      if (x.includes("step")) return "warn";
      return "";
    }
    function renderRecent(rows) {
      const body = $("recent-body");
      if (!rows || !rows.length) {
        body.innerHTML = '<tr><td colspan="6" class="empty">No recent decision rows yet — run an auth on Manual or Standalone.</td></tr>';
        return;
      }
      body.innerHTML = rows.slice().reverse().map((r) => {
        const cls = decisionClass(r.decision);
        return "<tr>" +
          "<td>" + shortTs(r.ts) + "</td>" +
          '<td class="' + cls + '">' + (r.decision || "—") + "</td>" +
          "<td>" + fmtMs(r.voice_ms) + "</td>" +
          "<td>" + fmtMs(r.face_ms) + "</td>" +
          "<td>" + fmtMs(r.finger_ms) + "</td>" +
          "<td>" + fmtMs(r.total_ms) + "</td>" +
          "</tr>";
      }).join("");
    }
    async function refresh() {
      const [healthRes, perfRes] = await Promise.all([
        fetch("/api/fleet/health"),
        fetch("/api/fleet/perf"),
      ]);
      const data = await healthRes.json();
      const perf = await perfRes.json();
      const a = data.auth || {};
      $("m_accept").textContent = a.accept ?? 0;
      $("m_reject").textContent = a.reject ?? 0;
      $("m_step").textContent = a.step_up ?? 0;
      const rate = a.accept_rate != null ? (100 * a.accept_rate).toFixed(1) + "%" : "—";
      $("m_rate").textContent = rate;
      $("m_fw").textContent = data.firmware_version || "—";
      $("m_vehicle").textContent = data.vehicle_id || "—";
      const sens = $("sensors");
      sens.innerHTML = "";
      const flags = data.sensors || {};
      Object.keys(flags).forEach((k) => {
        const el = document.createElement("div");
        el.className = "metric";
        const up = !!flags[k];
        el.innerHTML =
          '<div class="label">' + k + '</div>' +
          '<div class="value ' + (up ? "ok" : "bad") + '">' +
          '<span class="chip ' + (up ? "up" : "down") + '">' + (up ? "up" : "down") + "</span></div>";
        sens.appendChild(el);
      });
      const lat = (perf.latency_ms_avg) || {};
      $("l_voice").textContent = fmtMs(lat.voice);
      $("l_face").textContent = fmtMs(lat.face);
      $("l_finger").textContent = fmtMs(lat.finger);
      $("l_live").textContent = fmtMs(lat.liveness);
      $("l_total").textContent = fmtMs(lat.total);
      $("l_backend").textContent = perf.face_backend || "—";
      $("p_enabled").textContent = perf.enabled === false ? "off" : "on";
      $("p_count").textContent = perf.decisions_recent != null ? String(perf.decisions_recent) : "—";
      $("p_path").textContent = perf.path || "—";
      const util = perf.utilization || {};
      $("u_cpu").textContent = fmtNum(util.cpu_pct);
      $("u_ram").textContent = fmtNum(util.ram_pct);
      $("u_mb").textContent = fmtNum(util.ram_used_mb);
      renderRecent(perf.recent || []);
      $("payload").textContent = JSON.stringify({ health: data, perf: perf }, null, 2);
    }
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""
