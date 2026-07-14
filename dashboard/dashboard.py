"""Dashboard HTML UI — served by :mod:`dashboard.app`."""

from __future__ import annotations


def render_dashboard() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DriveAuth Edge Dashboard</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a2332;
      --border: #2d3a4f;
      --text: #e8edf4;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --manual: #a78bfa;
      --accept: #22c55e;
      --stepup: #f59e0b;
      --reject: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "SF Pro Text", system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      min-height: 100vh;
    }
    header {
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
    }
    header h1 { font-size: 1.25rem; font-weight: 600; }
    header p { color: var(--muted); font-size: 0.85rem; }
    .badge {
      display: inline-block;
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      background: var(--panel);
      border: 1px solid var(--border);
    }
    main {
      display: grid;
      grid-template-columns: 280px 320px 1fr;
      gap: 1rem;
      padding: 1rem 1.5rem 2rem;
      max-width: 1600px;
      margin: 0 auto;
    }
    @media (max-width: 1100px) {
      main { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 720px) {
      main { grid-template-columns: 1fr; }
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem;
    }
    .panel.manual {
      border-color: #5b4a8a;
      box-shadow: inset 0 0 0 1px rgba(167, 139, 250, 0.15);
    }
    .panel h2 {
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 0.35rem;
    }
    .panel .hint {
      font-size: 0.72rem;
      color: var(--muted);
      margin-bottom: 0.75rem;
      line-height: 1.4;
    }
    .panel.manual h2 { color: var(--manual); }
    label {
      display: block;
      font-size: 0.8rem;
      color: var(--muted);
      margin: 0.55rem 0 0.25rem;
    }
    input, select {
      width: 100%;
      padding: 0.45rem 0.6rem;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--text);
      font-size: 0.9rem;
    }
    input[type="range"] { padding: 0; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
    .checkbox-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-top: 0.5rem;
    }
    .checkbox-row input { width: auto; }
    button {
      cursor: pointer;
      border: none;
      border-radius: 6px;
      padding: 0.55rem 0.9rem;
      font-size: 0.85rem;
      font-weight: 600;
      margin-top: 0.75rem;
      margin-right: 0.4rem;
    }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-secondary { background: var(--border); color: var(--text); }
    .btn-danger { background: #7f1d1d; color: #fecaca; }
    .scores {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .score-card {
      background: var(--bg);
      border-radius: 8px;
      padding: 0.85rem;
      text-align: center;
    }
    .score-card .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; }
    .score-card .value { font-size: 1.75rem; font-weight: 700; margin-top: 0.2rem; }
    .bar-wrap {
      height: 8px;
      background: var(--border);
      border-radius: 4px;
      margin-top: 0.5rem;
      overflow: hidden;
    }
    .bar { height: 100%; border-radius: 4px; transition: width 0.3s; }
    .decision-banner {
      padding: 1rem;
      border-radius: 8px;
      text-align: center;
      font-size: 1.1rem;
      font-weight: 700;
      margin-bottom: 1rem;
      letter-spacing: 0.04em;
    }
    .decision-ACCEPT { background: rgba(34,197,94,0.15); color: var(--accept); border: 1px solid var(--accept); }
    .decision-STEP_UP_REQUIRED { background: rgba(245,158,11,0.15); color: var(--stepup); border: 1px solid var(--stepup); }
    .decision-REJECT { background: rgba(239,68,68,0.15); color: var(--reject); border: 1px solid var(--reject); }
    .meta { font-size: 0.85rem; color: var(--muted); }
    .meta dt { font-weight: 600; color: var(--text); margin-top: 0.5rem; }
    .meta dd { margin-left: 0; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.35rem; }
    .tag {
      font-size: 0.72rem;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .audit-list { max-height: 280px; overflow-y: auto; font-size: 0.78rem; }
    .audit-item {
      padding: 0.5rem 0;
      border-bottom: 1px solid var(--border);
    }
    .audit-item:last-child { border-bottom: none; }
    .scenario-btn {
      display: block;
      width: 100%;
      text-align: left;
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      margin-top: 0.35rem;
    }
    .scenario-btn:hover { border-color: var(--accent); }
    #status-bar { font-size: 0.8rem; color: var(--muted); }
    .contract {
      font-size: 0.78rem;
      color: var(--muted);
    }
    .contract h3 {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text);
      margin: 0.75rem 0 0.35rem;
    }
    .contract table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 0.25rem;
    }
    .contract th, .contract td {
      text-align: left;
      padding: 0.3rem 0.4rem;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    .contract th { color: var(--muted); font-weight: 600; width: 32%; }
    .contract code {
      font-size: 0.72rem;
      color: #c4d4f0;
    }
    .col-stack { display: flex; flex-direction: column; gap: 1rem; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>DriveAuth Edge</h1>
      <p>Trust / Risk / Confidence pipeline tester</p>
    </div>
    <div id="status-bar">Loading…</div>
  </header>

  <main>
    <!-- Col 1: real transaction / Nova payment fields -->
    <div class="col-stack">
      <section class="panel">
        <h2>Transaction (Nova → DriveAuth)</h2>
        <p class="hint">Payment fields Nova parses from the utterance / tool call.</p>
        <label>Amount (INR)</label>
        <input id="amount" type="number" value="150" min="0" step="1" />
        <label>Beneficiary</label>
        <input id="beneficiary" type="text" value="Starbucks" />
        <label>Action</label>
        <input id="action" type="text" value="pay" />
        <label>Currency</label>
        <input id="currency" type="text" value="INR" />
        <label>Channel</label>
        <input id="channel" type="text" value="dashboard" />
        <div class="checkbox-row">
          <input id="beneficiary_known" type="checkbox" checked />
          <label for="beneficiary_known" style="margin:0">Known beneficiary</label>
        </div>
        <div class="checkbox-row">
          <input id="is_guest" type="checkbox" />
          <label for="is_guest" style="margin:0">Guest mode</label>
        </div>
      </section>

      <section class="panel">
        <h2>Actions</h2>
        <button class="btn-primary" onclick="runAuth()">Run authenticate()</button>
        <button class="btn-secondary" onclick="loadStatus()">Refresh status</button>
        <button class="btn-secondary" onclick="resetSession()">Reset session</button>
        <hr style="border:none;border-top:1px solid var(--border);margin:0.75rem 0" />
        <button class="btn-secondary" onclick="fraudFlag()">+ Soft fraud flag</button>
        <button class="btn-secondary" onclick="fraudClean()">Record clean</button>
        <button class="btn-danger" onclick="fraudReset()">Reset fraud ladder</button>
      </section>

      <section class="panel">
        <h2>Presets</h2>
        <div id="scenarios"></div>
      </section>
    </div>

    <!-- Col 2: manual stand-ins for sensors Nova will own later -->
    <div class="col-stack">
      <section class="panel manual">
        <h2>Manual stand-ins → auto later</h2>
        <p class="hint">
          These mimic sensors / matchers Nova will feed automatically
          (mic, camera, fingerprint, CAN, GPS). Same values, different source.
        </p>

        <h2 style="margin-top:0.5rem;color:var(--manual)">Biometric match scores</h2>
        <p class="hint">Later: ECAPA / ArcFace / FingerNet emit <code>ModalityResult.score ∈ [0,1]</code>.</p>
        <label>Voice <span id="voice-val">0.92</span></label>
        <input id="voice" type="range" min="0" max="1" step="0.01" value="0.92" />
        <label>Face <span id="face-val">0.88</span></label>
        <input id="face" type="range" min="0" max="1" step="0.01" value="0.88" />
        <label>Finger <span id="finger-val">0.85</span></label>
        <input id="finger" type="range" min="0" max="1" step="0.01" value="0.85" />
        <label>Behavioral <span id="behavioral-val">0.95</span></label>
        <input id="behavioral" type="range" min="0" max="1" step="0.01" value="0.95" />

        <h2 style="margin-top:1rem;color:var(--manual)">GPS (vehicle / telematics)</h2>
        <p class="hint">Later: Nova GPS thread → <code>update_vehicle_context(gps_lat=…)</code>. Home distance derived if home learned.</p>
        <div class="row">
          <div>
            <label>gps_lat</label>
            <input id="gps_lat" type="number" step="0.0001" placeholder="optional" />
          </div>
          <div>
            <label>gps_lon</label>
            <input id="gps_lon" type="number" step="0.0001" placeholder="optional" />
          </div>
        </div>
        <label>gps_accuracy_m</label>
        <input id="gps_accuracy_m" type="number" value="50" min="0" step="1" />
        <label>dist_from_home_km <span style="opacity:.7">(override if no home yet)</span></label>
        <input id="dist_home" type="number" value="0" min="0" step="0.1" />
        <div class="checkbox-row">
          <input id="trusted_zone" type="checkbox" checked />
          <label for="trusted_zone" style="margin:0">in_trusted_zone</label>
        </div>

        <h2 style="margin-top:1rem;color:var(--manual)">Vehicle / CAN</h2>
        <p class="hint">Later: CAN recorder → <code>update_behavioral({…})</code> + speed/ignition on context.</p>
        <label>speed_kmh</label>
        <input id="speed" type="number" value="0" min="0" />
        <div class="checkbox-row">
          <input id="ignition_on" type="checkbox" checked />
          <label for="ignition_on" style="margin:0">ignition_on</label>
        </div>
        <div class="checkbox-row">
          <input id="tunnel" type="checkbox" />
          <label for="tunnel" style="margin:0">is_tunnel</label>
        </div>
      </section>
    </div>

    <!-- Col 3: results + Nova contract -->
    <div class="col-stack">
      <section class="panel">
        <h2>Nova ↔ DriveAuth contract</h2>
        <div class="contract">
          <h3>Inputs Nova must supply</h3>
          <table>
            <tr><th>Field</th><td><code>audio_np</code> — float32 mono ~16 kHz (STT mic buffer)</td></tr>
            <tr><th>Payment</th><td><code>amount</code>, <code>beneficiary</code>, <code>action</code>, <code>currency</code>, <code>channel</code>, <code>beneficiary_known</code>, <code>is_guest</code></td></tr>
            <tr><th>Or utterance</th><td><code>intercept(transcript, audio_np, …)</code> — DriveAuth parses amount/beneficiary itself</td></tr>
            <tr><th>Vehicle</th><td><code>update_vehicle_context(gps_lat, gps_lon, gps_accuracy_m, speed_kmh, ignition_on, is_tunnel, …)</code></td></tr>
            <tr><th>CAN (optional)</th><td><code>update_behavioral({steering_torque_nm, brake_pressure_bar, throttle_pct, …})</code></td></tr>
            <tr><th>Face frame</th><td>Inject BGR still / live cam via FaceMatcher when not using mocks</td></tr>
            <tr><th>Finger / pad</th><td>HW module → same <code>ModalityResult(score∈[0,1])</code> (manual sliders here until then)</td></tr>
          </table>
          <h3>Outputs DriveAuth returns</h3>
          <table>
            <tr><th>decision</th><td><code>ACCEPT</code> | <code>STEP_UP_REQUIRED</code> | <code>REJECT</code> (legacy: pass / step_up / deny)</td></tr>
            <tr><th>scores</th><td><code>trust_score</code>, <code>risk_score</code>, <code>confidence_score</code></td></tr>
            <tr><th>routing</th><td><code>tier</code>, <code>policy_rule</code>, <code>fraud_state</code>, <code>step_up_method</code></td></tr>
            <tr><th>debug</th><td><code>explanations[]</code>, <code>modality_scores</code>, <code>ood_flags</code>, <code>active_thresholds</code></td></tr>
            <tr><th>intercept()</th><td>string <code>"pass"</code> | <code>"step_up"</code> | <code>"deny"</code> for STT worker queues</td></tr>
          </table>
        </div>
      </section>

      <section class="panel">
        <h2>Result</h2>
        <div id="decision-banner" class="decision-banner decision-ACCEPT">—</div>
        <div class="scores">
          <div class="score-card">
            <div class="label">Trust</div>
            <div class="value" id="trust-val">—</div>
            <div class="bar-wrap"><div class="bar" id="trust-bar" style="width:0;background:var(--accept)"></div></div>
          </div>
          <div class="score-card">
            <div class="label">Risk</div>
            <div class="value" id="risk-val">—</div>
            <div class="bar-wrap"><div class="bar" id="risk-bar" style="width:0;background:var(--reject)"></div></div>
          </div>
          <div class="score-card">
            <div class="label">Confidence</div>
            <div class="value" id="conf-val">—</div>
            <div class="bar-wrap"><div class="bar" id="conf-bar" style="width:0;background:var(--accent)"></div></div>
          </div>
        </div>
        <dl class="meta">
          <dt>Tier</dt><dd id="tier">—</dd>
          <dt>Policy rule</dt><dd id="policy">—</dd>
          <dt>Step-up</dt><dd id="stepup">—</dd>
          <dt>Legacy (Nova)</dt><dd id="legacy">—</dd>
          <dt>Explanations</dt>
          <dd><div class="tags" id="explanations"></div></dd>
          <dt>Modality scores</dt>
          <dd><pre id="modalities" style="font-size:0.75rem;overflow:auto;margin-top:0.25rem"></pre></dd>
        </dl>
      </section>

      <section class="panel">
        <h2>Audit log</h2>
        <div class="audit-list" id="audit-list">No events yet.</div>
      </section>
    </div>
  </main>

  <script>
    function bindRange(id, labelId) {
      const el = document.getElementById(id);
      const lbl = document.getElementById(labelId);
      el.addEventListener("input", () => { lbl.textContent = el.value; });
    }
    ["voice","face","finger","behavioral"].forEach(k => bindRange(k, k + "-val"));

    function numOrNull(id) {
      const raw = document.getElementById(id).value;
      if (raw === "" || raw == null) return null;
      const v = parseFloat(raw);
      return Number.isFinite(v) ? v : null;
    }

    function payloadFromForm() {
      return {
        amount: parseFloat(document.getElementById("amount").value) || 0,
        beneficiary: document.getElementById("beneficiary").value,
        beneficiary_known: document.getElementById("beneficiary_known").checked,
        is_guest: document.getElementById("is_guest").checked,
        action: document.getElementById("action").value || "pay",
        currency: document.getElementById("currency").value || "INR",
        channel: document.getElementById("channel").value || "dashboard",
        mock_scores: {
          voice: parseFloat(document.getElementById("voice").value),
          face: parseFloat(document.getElementById("face").value),
          finger: parseFloat(document.getElementById("finger").value),
          behavioral: parseFloat(document.getElementById("behavioral").value),
        },
        context: {
          speed_kmh: parseFloat(document.getElementById("speed").value) || 0,
          in_trusted_zone: document.getElementById("trusted_zone").checked,
          dist_from_home_km: parseFloat(document.getElementById("dist_home").value) || 0,
          is_tunnel: document.getElementById("tunnel").checked,
          ignition_on: document.getElementById("ignition_on").checked,
          gps_lat: numOrNull("gps_lat"),
          gps_lon: numOrNull("gps_lon"),
          gps_accuracy_m: parseFloat(document.getElementById("gps_accuracy_m").value) || 50,
        },
      };
    }

    function applyPayload(p) {
      document.getElementById("amount").value = p.amount;
      document.getElementById("beneficiary").value = p.beneficiary || "";
      document.getElementById("beneficiary_known").checked = !!p.beneficiary_known;
      document.getElementById("is_guest").checked = !!p.is_guest;
      if (p.action) document.getElementById("action").value = p.action;
      if (p.currency) document.getElementById("currency").value = p.currency;
      if (p.channel) document.getElementById("channel").value = p.channel;
      const m = p.mock_scores || {};
      ["voice","face","finger","behavioral"].forEach(k => {
        if (m[k] != null) {
          document.getElementById(k).value = m[k];
          document.getElementById(k + "-val").textContent = m[k];
        }
      });
      const c = p.context || {};
      document.getElementById("speed").value = c.speed_kmh ?? 0;
      document.getElementById("dist_home").value = c.dist_from_home_km ?? 0;
      document.getElementById("trusted_zone").checked = c.in_trusted_zone !== false;
      document.getElementById("tunnel").checked = !!c.is_tunnel;
      document.getElementById("ignition_on").checked = c.ignition_on !== false;
      document.getElementById("gps_lat").value = c.gps_lat ?? "";
      document.getElementById("gps_lon").value = c.gps_lon ?? "";
      document.getElementById("gps_accuracy_m").value = c.gps_accuracy_m ?? 50;
    }

    function showResult(r) {
      const banner = document.getElementById("decision-banner");
      banner.textContent = r.decision;
      banner.className = "decision-banner decision-" + r.decision;

      function setScore(id, barId, val) {
        const pct = Math.round((val || 0) * 100);
        document.getElementById(id).textContent = (val ?? 0).toFixed(3);
        document.getElementById(barId).style.width = pct + "%";
      }
      setScore("trust-val", "trust-bar", r.trust_score);
      setScore("risk-val", "risk-bar", r.risk_score);
      setScore("conf-val", "conf-bar", r.confidence_score);

      document.getElementById("tier").textContent = r.tier;
      document.getElementById("policy").textContent = r.policy_rule;
      document.getElementById("stepup").textContent = r.step_up_method || "—";
      document.getElementById("legacy").textContent = r.legacy_decision || "—";

      const tags = document.getElementById("explanations");
      tags.innerHTML = (r.explanations || []).map(e => `<span class="tag">${e}</span>`).join("");
      document.getElementById("modalities").textContent = JSON.stringify(r.modality_scores, null, 2);
    }

    async function runAuth() {
      const res = await fetch("/api/authenticate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadFromForm()),
      });
      showResult(await res.json());
      loadAudit();
      loadStatus();
    }

    async function loadStatus() {
      const s = await (await fetch("/api/status")).json();
      const maturity = s.profile_mature ? "mature" : (s.profile_maturity || "bootstrap");
      document.getElementById("status-bar").innerHTML =
        `Store: <code>${s.store_dir}</code> · Fraud: <span class="badge">${s.fraud_state}</span> · Profile: <span class="badge">${maturity}</span>`;
    }

    async function loadAudit() {
      const entries = await (await fetch("/api/audit")).json();
      const el = document.getElementById("audit-list");
      if (!entries.length) { el.textContent = "No events yet."; return; }
      el.innerHTML = entries.map(e => `
        <div class="audit-item">
          <strong>${e.decision}</strong> · ${e.tier} · trust ${e.trust_score} · risk ${e.risk_score}
          <br><span style="color:var(--muted)">${e.ts} · ${e.policy_rule}</span>
        </div>`).join("");
    }

    async function loadScenarios() {
      const list = await (await fetch("/api/scenarios")).json();
      document.getElementById("scenarios").innerHTML = list.map(s =>
        `<button class="scenario-btn" onclick='applyScenario(${JSON.stringify({request: s.request, profile: s.profile || "mature"})})'>${s.label}</button>`
      ).join("");
    }

    async function ensureProfile(mode) {
      const path = mode === "bootstrap" ? "/api/profile/bootstrap" : "/api/profile/mature";
      await fetch(path, { method: "POST" });
    }

    async function applyScenario(s) {
      await ensureProfile(s.profile || "mature");
      applyPayload(s.request);
      await runAuth();
    }

    async function fraudFlag() {
      await fetch("/api/fraud/soft-flag", { method: "POST" });
      loadStatus();
    }
    async function fraudClean() {
      await fetch("/api/fraud/clean", { method: "POST" });
      loadStatus();
    }
    async function fraudReset() {
      await fetch("/api/fraud/reset", { method: "POST" });
      loadStatus();
    }
    async function resetSession() {
      await fetch("/api/reset?mature=true", { method: "POST" });
      loadStatus();
      loadAudit();
    }

    loadStatus();
    loadAudit();
    loadScenarios();
  </script>
</body>
</html>"""
