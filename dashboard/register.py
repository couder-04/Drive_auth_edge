"""Driver registration UI — capture face + voice into data/<driver>/ then enroll."""

from __future__ import annotations


def render_register() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DriveAuth — Register driver</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a2332;
      --border: #2d3a4f;
      --text: #e8edf4;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --accent-dim: #1e3a5f;
      --ok: #22c55e;
      --warn: #f59e0b;
      --bad: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "SF Pro Text", system-ui, -apple-system, sans-serif;
      background:
        radial-gradient(ellipse 80% 50% at 10% -10%, #1a3a5c 0%, transparent 55%),
        radial-gradient(ellipse 60% 40% at 100% 0%, #1a2a22 0%, transparent 45%),
        var(--bg);
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
      gap: 1rem;
      flex-wrap: wrap;
      backdrop-filter: blur(8px);
      background: rgba(15, 20, 25, 0.75);
    }
    header h1 { font-size: 1.35rem; font-weight: 650; letter-spacing: -0.02em; }
    header p { color: var(--muted); font-size: 0.85rem; }
    a.nav {
      color: var(--accent);
      text-decoration: none;
      font-size: 0.9rem;
      border: 1px solid var(--border);
      padding: 0.45rem 0.85rem;
      border-radius: 8px;
      background: var(--panel);
    }
    a.nav:hover { border-color: var(--accent); }
    main {
      max-width: 980px;
      margin: 0 auto;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .hero {
      padding: 0.25rem 0 0.5rem;
    }
    .hero h2 {
      font-size: 1.6rem;
      font-weight: 650;
      letter-spacing: -0.03em;
      margin-bottom: 0.35rem;
    }
    .hero p { color: var(--muted); max-width: 42rem; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.15rem 1.25rem;
    }
    .panel h3 {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 0.75rem;
    }
    .row {
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
      align-items: end;
    }
    label {
      display: block;
      font-size: 0.8rem;
      color: var(--muted);
      margin-bottom: 0.35rem;
    }
    input[type="text"] {
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 8px;
      padding: 0.55rem 0.75rem;
      font-size: 1rem;
      min-width: 220px;
    }
    input:focus, button:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
    button {
      border: none;
      border-radius: 8px;
      padding: 0.55rem 1rem;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      background: var(--accent);
      color: white;
    }
    button.secondary {
      background: var(--accent-dim);
      color: var(--text);
      border: 1px solid var(--border);
    }
    button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    button.danger { background: #7f1d1d; }
    .grid2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
    }
    @media (max-width: 800px) {
      .grid2 { grid-template-columns: 1fr; }
    }
    .preview {
      width: 100%;
      aspect-ratio: 4/3;
      background: #0a0e14;
      border-radius: 10px;
      border: 1px solid var(--border);
      object-fit: cover;
      display: block;
    }
    .thumbs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-top: 0.75rem;
      min-height: 56px;
    }
    .thumbs img {
      width: 56px;
      height: 56px;
      object-fit: cover;
      border-radius: 6px;
      border: 1px solid var(--border);
    }
    .clips {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      margin-top: 0.75rem;
      font-size: 0.85rem;
      color: var(--muted);
    }
    .meter {
      height: 8px;
      background: #0a0e14;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 0.75rem;
      border: 1px solid var(--border);
    }
    .meter > span {
      display: block;
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), #38bdf8);
      transition: width 0.25s ease;
    }
    .status-line {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.5rem;
    }
    .chip {
      font-size: 0.75rem;
      padding: 0.25rem 0.55rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
      background: rgba(0,0,0,0.25);
    }
    .chip.ok { color: var(--ok); border-color: #166534; }
    .chip.warn { color: var(--warn); border-color: #92400e; }
    .chip.bad { color: var(--bad); border-color: #7f1d1d; }
    .log {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.78rem;
      color: var(--muted);
      white-space: pre-wrap;
      max-height: 160px;
      overflow: auto;
      background: #0a0e14;
      border-radius: 8px;
      padding: 0.75rem;
      border: 1px solid var(--border);
    }
    .phrase {
      margin: 0.5rem 0 0.75rem;
      padding: 0.65rem 0.8rem;
      background: rgba(59, 130, 246, 0.08);
      border-left: 3px solid var(--accent);
      border-radius: 0 8px 8px 0;
      font-size: 1.05rem;
    }
    .recording {
      animation: pulse 1.1s ease-in-out infinite;
      background: var(--bad) !important;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.7; }
    }
    #home-map {
      width: 100%;
      height: 260px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0a0e14;
      margin-top: 0.5rem;
    }
    .home-meta { margin-top: 0.5rem; font-size: 0.85rem; color: var(--muted); }
    .nav-row { display: flex; flex-wrap: wrap; gap: 0.45rem; }
    .driver-list { display: flex; flex-direction: column; gap: 0.45rem; margin-top: 0.5rem; }
    .driver-row {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 0.65rem;
      align-items: center;
      padding: 0.65rem 0.75rem;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: rgba(0,0,0,0.22);
    }
    @media (max-width: 700px) {
      .driver-row { grid-template-columns: 1fr; }
    }
    .driver-row .name {
      font-weight: 650;
      letter-spacing: -0.02em;
    }
    .driver-row .meta {
      font-size: 0.78rem;
      color: var(--muted);
      margin-top: 0.15rem;
    }
    .driver-row .status {
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.28rem 0.55rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
      white-space: nowrap;
    }
    .driver-row .status.enrolled { color: var(--ok); border-color: #166534; }
    .driver-row.locked-row {
      opacity: 0.78;
      border-style: dashed;
    }
    .driver-row .btn-pick.locked-pick {
      background: transparent;
      color: var(--muted);
    }
    .panel.edit-locked {
      position: relative;
    }
    .panel.edit-locked::after {
      content: attr(data-lock);
      position: absolute;
      inset: 0;
      z-index: 3;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 1rem;
      font-size: 0.85rem;
      font-weight: 650;
      color: var(--warn);
      background: rgba(15, 20, 25, 0.72);
      border-radius: 12px;
      pointer-events: none;
    }
    #lock_banner {
      display: none;
      margin-top: 0.65rem;
      padding: 0.55rem 0.75rem;
      border-radius: 8px;
      border: 1px solid #92400e;
      background: rgba(245, 158, 11, 0.1);
      color: var(--warn);
      font-size: 0.85rem;
    }
    #lock_banner.on { display: block; }
    .driver-row .status.ready_to_enroll { color: var(--accent); border-color: #1e3a5f; }
    .driver-row .status.need_home,
    .driver-row .status.capturing,
    .driver-row .status.partial_templates { color: var(--warn); border-color: #92400e; }
    .driver-row .status.empty { color: var(--muted); }
    .driver-row button { padding: 0.4rem 0.75rem; font-size: 0.85rem; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>DriveAuth</h1>
      <p>New driver registration — face + voice</p>
    </div>
    <div class="nav-row">
      <a class="nav" href="/manual">Manual pipeline</a>
      <a class="nav" href="/standalone">Standalone pay</a>
      <a class="nav" href="/fleet">Fleet health</a>
    </div>
  </header>

  <main>
    <section class="hero">
      <h2>Register a driver</h2>
      <p>
        Capture enroll samples in the browser. Files land in
        <code>data/&lt;driver_id&gt;/{face,voice}/enroll/</code>, then
        enrollment writes templates into the Phase 2a store.
      </p>
    </section>

    <section class="panel">
      <h3>Registered drivers</h3>
      <p style="color:var(--muted);font-size:0.85rem;margin-bottom:0.35rem">
        Enrolled drivers are <strong>locked</strong> (view only). Continue a capturing
        driver, or use the next default ID below to register someone new.
      </p>
      <div class="driver-list" id="driver_list">Loading…</div>
      <div class="row" style="margin-top:0.65rem">
        <button id="btn_drivers_refresh" class="secondary" type="button">Refresh list</button>
      </div>
    </section>

    <section class="panel">
      <h3>1 · Driver</h3>
      <div class="row">
        <div>
          <label for="driver_id">Driver ID</label>
          <input id="driver_id" type="text" value="" placeholder="driver1" autocomplete="off" />
        </div>
        <button id="btn_init" type="button">Create folders</button>
        <button id="btn_refresh" class="secondary" type="button">Refresh status</button>
      </div>
      <div class="status-line" id="chips"></div>
      <div id="lock_banner">This driver is enrolled and locked. Switch to a capturing driver or create a new one.</div>
      <div class="meter" aria-hidden="true"><span id="progress"></span></div>
    </section>

    <section class="grid2">
      <div class="panel" id="panel_face">
        <h3>2 · Face (need 5)</h3>
        <video id="cam" class="preview" autoplay playsinline muted></video>
        <div class="row" style="margin-top:0.75rem">
          <button id="btn_cam" class="secondary" type="button">Start camera</button>
          <button id="btn_snap" type="button" disabled>Capture face</button>
        </div>
        <div class="thumbs" id="face_thumbs"></div>
      </div>

      <div class="panel" id="panel_voice">
        <h3>3 · Voice (need 5)</h3>
        <p class="phrase" id="phrase">Say: “pay Mom fifty”</p>
        <div class="row">
          <button id="btn_mic" class="secondary" type="button">Enable mic</button>
          <button id="btn_rec" type="button" disabled>Hold to record · 2.5s</button>
        </div>
        <div class="clips" id="voice_clips"></div>
      </div>
    </section>

    <section class="panel" id="panel_home">
      <h3>4 · Home (required)</h3>
      <p style="color:var(--muted);font-size:0.85rem;margin-bottom:0.5rem">
        Pin this driver’s home on the map before enroll. Linked to the driver
        profile and used to derive <code>in_trusted_zone</code> during authorization
        (raw distance is telemetry only — not a risk feature).
      </p>
      <div class="row">
        <button id="btn_home_geo" class="secondary" type="button">Use my location</button>
        <button id="btn_home_save" type="button" disabled>Save home pin</button>
      </div>
      <div id="home-map"></div>
      <div class="home-meta" id="home_meta">No pin yet — select home on the map to unlock enroll</div>
    </section>

    <section class="panel" id="panel_register">
      <h3>5 · Register</h3>
      <div class="row">
        <button id="btn_enroll" type="button" disabled>Enroll into store</button>
        <button id="btn_clear" class="secondary danger" type="button">Clear enroll samples</button>
      </div>
      <p style="margin-top:0.75rem;color:var(--muted);font-size:0.85rem" id="enroll_hint">
        Needs 5 face + 5 voice samples <strong>and</strong> a saved home pin.
        Models: <code>python scripts/phase2a_setup.py</code>.
      </p>
      <div class="log" id="log" style="margin-top:0.75rem">Ready.</div>
    </section>
  </main>

  <script>
    const PHRASES = [
      "pay Mom fifty",
      "transfer two hundred to Raj",
      "open navigation",
      "pay Starbucks one fifty",
      "confirm payment now",
      "send five thousand home",
    ];

    const state = {
      stream: null,
      audioCtx: null,
      micStream: null,
      recording: false,
      driverIdTouched: false,
      locked: false,
      camReady: false,
      micReady: false,
    };
    const homeState = { map: null, marker: null, lat: null, lon: null, ready: false, saving: false };

    const $ = (id) => document.getElementById(id);
    const log = (msg) => {
      const el = $("log");
      const ts = new Date().toLocaleTimeString();
      el.textContent = `[${ts}] ${msg}\\n` + el.textContent;
    };

    function driverId() {
      return ($("driver_id").value || "").trim();
    }

    /** Next default id: driver&lt;max numeric suffix in list + 1&gt;. Empty → driver1. */
    function nextDriverId(rows) {
      let maxN = 0;
      for (const d of rows || []) {
        const id = String(d.driver_id || d.name || "");
        const m = /^driver(\\d+)$/i.exec(id);
        if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
      }
      return `driver${maxN + 1}`;
    }

    function setDefaultDriverId(rows, { force = false } = {}) {
      const suggested = nextDriverId(rows);
      const input = $("driver_id");
      if (force || !state.driverIdTouched || !input.value.trim()) {
        input.value = suggested;
        state.driverIdTouched = false;
      }
      return suggested;
    }

    $("driver_id").addEventListener("input", () => {
      state.driverIdTouched = true;
    });

    function encodeWav(float32, sampleRate) {
      const buffer = new ArrayBuffer(44 + float32.length * 2);
      const view = new DataView(buffer);
      const writeStr = (off, s) => {
        for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
      };
      writeStr(0, "RIFF");
      view.setUint32(4, 36 + float32.length * 2, true);
      writeStr(8, "WAVE");
      writeStr(12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeStr(36, "data");
      view.setUint32(40, float32.length * 2, true);
      let offset = 44;
      for (let i = 0; i < float32.length; i++, offset += 2) {
        let s = Math.max(-1, Math.min(1, float32[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      return new Blob([buffer], { type: "audio/wav" });
    }

    function adminHeaders(extra = {}) {
      const headers = Object.assign({}, extra || {});
      if (window.__DRIVEAUTH_ADMIN_KEY__) {
        headers["X-API-Key"] = window.__DRIVEAUTH_ADMIN_KEY__;
      }
      return headers;
    }

    async function api(path, opts = {}) {
      const opts2 = Object.assign({}, opts);
      const isForm = (typeof FormData !== "undefined") && opts2.body instanceof FormData;
      opts2.headers = adminHeaders(opts2.headers || {});
      if (!isForm && opts2.body && typeof opts2.body === "string" && !opts2.headers["Content-Type"]) {
        opts2.headers["Content-Type"] = "application/json";
      }
      const res = await fetch(path, opts2);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail || data.error || res.statusText;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      return data;
    }

    function applyEditLock(locked, driverLabel) {
      state.locked = !!locked;
      const lockMsg = locked
        ? `${driverLabel || "Driver"} is enrolled · locked (view only)`
        : "";
      ["panel_face", "panel_voice", "panel_home", "panel_register"].forEach((id) => {
        const el = $(id);
        if (!el) return;
        el.classList.toggle("edit-locked", !!locked);
        if (locked) el.setAttribute("data-lock", lockMsg);
        else el.removeAttribute("data-lock");
      });
      const banner = $("lock_banner");
      if (banner) {
        banner.classList.toggle("on", !!locked);
        if (locked) {
          banner.textContent =
            `${driverLabel || "This driver"} is enrolled and locked. ` +
            "Continue a capturing driver, or create a new Driver ID.";
        }
      }
      $("btn_init").disabled = !!locked;
      $("btn_enroll").disabled = true; // re-enabled below when unlocked + ready
      $("btn_clear").disabled = !!locked;
      $("btn_home_save").disabled = !!locked || homeState.lat == null;
      $("btn_home_geo").disabled = !!locked;
      $("btn_cam").disabled = !!locked;
      $("btn_snap").disabled = !!locked || !state.camReady;
      $("btn_mic").disabled = !!locked;
      $("btn_rec").disabled = !!locked || !state.micReady;
    }

    function renderStatus(s) {
      const chips = $("chips");
      const faceOk = s.face_count >= s.min_face;
      const voiceOk = s.voice_count >= s.min_voice;
      const homeOk = !!s.home_set;
      const locked = !!s.locked || !!(s.templates && s.templates.face && s.templates.voice);
      chips.innerHTML = [
        `<span class="chip">data: ${s.data_dir}</span>`,
        `<span class="chip ${faceOk ? "ok" : "warn"}">face ${s.face_count}/${s.min_face}</span>`,
        `<span class="chip ${voiceOk ? "ok" : "warn"}">voice ${s.voice_count}/${s.min_voice}</span>`,
        `<span class="chip ${homeOk ? "ok" : "warn"}">home ${homeOk ? "set" : "required"}</span>`,
        `<span class="chip ${locked ? "ok" : ""}">${locked ? "🔒 enrolled · locked" : "editable"}</span>`,
        `<span class="chip ${s.face_model_present ? "ok" : "bad"}">face model</span>`,
        `<span class="chip ${s.voice_model_present ? "ok" : "bad"}">voice model</span>`,
        `<span class="chip ${s.templates.face && s.templates.voice ? "ok" : ""}">templates ${
          s.templates.face && s.templates.voice ? "enrolled" : "pending"
        }</span>`,
      ].join("");

      const total = s.min_face + s.min_voice;
      const done = Math.min(s.face_count, s.min_face) + Math.min(s.voice_count, s.min_voice);
      $("progress").style.width = `${Math.round((100 * done) / total)}%`;

      applyEditLock(locked, s.driver_id);

      const hint = $("enroll_hint");
      if (locked) {
        hint.innerHTML =
          "Enrolled drivers cannot be modified. Use the next Driver ID or continue a capturing row.";
      } else if (!homeOk) {
        hint.innerHTML = "Pin and <strong>save home</strong> on the map before enroll is enabled.";
      } else if (!(faceOk && voiceOk)) {
        hint.innerHTML = "Needs 5 face + 5 voice samples. Models: <code>python scripts/phase2a_setup.py</code>.";
      } else {
        hint.innerHTML = "Ready — enroll writes templates into the Phase 2a store.";
      }
      if (!locked) {
        $("btn_enroll").disabled = !s.ready_to_register;
      }

      if (homeOk && s.home_lat != null && s.home_lon != null) {
        homeState.lat = s.home_lat;
        homeState.lon = s.home_lon;
        $("home_meta").textContent =
          `Saved home: ${Number(s.home_lat).toFixed(5)}, ${Number(s.home_lon).toFixed(5)}`;
        if (!locked) $("btn_home_save").disabled = false;
        if (homeState.map && window.google) {
          setHomePin(s.home_lat, s.home_lon, { skipMeta: true });
        }
      }

      $("face_thumbs").innerHTML = (s.face_files || [])
        .map((name) => `<img src="/api/register/preview/face/${encodeURIComponent(s.driver_id)}/${encodeURIComponent(name)}" alt="${name}" title="${name}" />`)
        .join("");
      $("voice_clips").innerHTML = (s.voice_files || [])
        .map((name, i) => `<div>${i + 1}. ${name}</div>`)
        .join("") || "<div>No clips yet</div>";

      const nextPhrase = PHRASES[Math.min(s.voice_count, PHRASES.length - 1)];
      $("phrase").textContent = locked
        ? "Enrolled · face / voice locked"
        : `Say: “${nextPhrase}”`;
    }

    async function refresh() {
      const id = driverId();
      if (!id) return;
      const s = await api(`/api/register/status?driver_id=${encodeURIComponent(id)}`);
      renderStatus(s);
      return s;
    }

    $("btn_init").onclick = async () => {
      if (state.locked) {
        log("Enrolled driver is locked — create a new Driver ID instead");
        return;
      }
      try {
        const id = driverId();
        await api("/api/register/init", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ driver_id: id }),
        });
        log(`Created folders for ${id}`);
        await refresh();
      } catch (e) {
        log("Init failed: " + e.message);
      }
    };

    $("btn_refresh").onclick = () => refresh().catch((e) => log(e.message));

    $("btn_cam").onclick = async () => {
      if (state.locked) return;
      try {
        if (state.stream) {
          state.stream.getTracks().forEach((t) => t.stop());
          state.stream = null;
        }
        state.stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        });
        $("cam").srcObject = state.stream;
        state.camReady = true;
        $("btn_snap").disabled = false;
        log("Camera ready");
      } catch (e) {
        log("Camera error: " + e.message);
      }
    };

    $("btn_snap").onclick = async () => {
      if (state.locked) return;
      try {
        const video = $("cam");
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
        const fd = new FormData();
        fd.append("driver_id", driverId());
        fd.append("file", blob, "capture.jpg");
        const res = await api("/api/register/face", { method: "POST", body: fd });
        log(`Saved face ${res.path}`);
        await refresh();
      } catch (e) {
        log("Face capture failed: " + e.message);
      }
    };

    $("btn_mic").onclick = async () => {
      if (state.locked) return;
      try {
        state.micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
        state.audioCtx = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 16000,
        });
        state.micReady = true;
        $("btn_rec").disabled = false;
        log("Microphone ready");
      } catch (e) {
        log("Mic error: " + e.message);
      }
    };

    async function recordClip(seconds = 2.5) {
      if (state.locked) throw new Error("enrolled driver is locked");
      if (!state.micStream || !state.audioCtx) throw new Error("Enable mic first");
      if (state.recording) return;
      state.recording = true;
      $("btn_rec").classList.add("recording");
      $("btn_rec").textContent = "Recording…";

      const ctx = state.audioCtx;
      if (ctx.state === "suspended") await ctx.resume();
      const source = ctx.createMediaStreamSource(state.micStream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [];
      const target = Math.floor(ctx.sampleRate * seconds);

      await new Promise((resolve) => {
        processor.onaudioprocess = (e) => {
          const input = e.inputBuffer.getChannelData(0);
          chunks.push(new Float32Array(input));
          const total = chunks.reduce((n, c) => n + c.length, 0);
          if (total >= target) {
            processor.disconnect();
            source.disconnect();
            resolve();
          }
        };
        const mute = ctx.createGain();
        mute.gain.value = 0;
        source.connect(processor);
        processor.connect(mute);
        mute.connect(ctx.destination);
      });

      const total = chunks.reduce((n, c) => n + c.length, 0);
      const merged = new Float32Array(total);
      let off = 0;
      for (const c of chunks) {
        merged.set(c, off);
        off += c.length;
      }
      const trimmed = merged.slice(0, target);
      const blob = encodeWav(trimmed, ctx.sampleRate);

      state.recording = false;
      $("btn_rec").classList.remove("recording");
      $("btn_rec").textContent = "Hold to record · 2.5s";

      const fd = new FormData();
      fd.append("driver_id", driverId());
      fd.append("file", blob, "capture.wav");
      const res = await api("/api/register/voice", { method: "POST", body: fd });
      log(`Saved voice ${res.path}`);
      await refresh();
    }

    $("btn_rec").onclick = () => {
      recordClip().catch((e) => {
        state.recording = false;
        $("btn_rec").classList.remove("recording");
        $("btn_rec").textContent = "Hold to record · 2.5s";
        log("Voice capture failed: " + e.message);
      });
    };

    $("btn_enroll").onclick = async () => {
      if (state.locked) {
        log("Enrolled driver is locked");
        return;
      }
      $("btn_enroll").disabled = true;
      log("Enrolling… this may take a minute on first ECAPA load");
      try {
        const res = await api("/api/register/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            driver_id: driverId(),
            consent: true,
            consent_notes: "dashboard /register explicit enroll click",
          }),
        });
        log(
          `Enrolled ${res.driver_id}: voice=${res.voice_samples} face=${res.face_samples}\\n` +
            `  → ${res.store_dir}/${res.voice_template}\\n` +
            `  → ${res.store_dir}/${res.face_template}`
        );
        state.driverIdTouched = false;
        const rows = await loadDrivers({ suggestId: false });
        setDefaultDriverId(rows, { force: true });
        log("Next default Driver ID: " + $("driver_id").value);
        await refresh();
      } catch (e) {
        log("Enroll failed: " + e.message);
        $("btn_enroll").disabled = false;
      }
    };

    $("btn_clear").onclick = async () => {
      if (state.locked) {
        log("Enrolled driver is locked — cannot clear samples");
        return;
      }
      if (!confirm("Delete enroll face/voice files for this driver?")) return;
      try {
        await api("/api/register/clear", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ driver_id: driverId() }),
        });
        log("Cleared enroll samples");
        await refresh();
      } catch (e) {
        log("Clear failed: " + e.message);
      }
    };

    /* ── Home Maps picker ─────────────────────────────────────────── */
    function setHomePin(lat, lon, opts = {}) {
      homeState.lat = lat;
      homeState.lon = lon;
      if (!opts.skipMeta) {
        $("home_meta").textContent = `Pin: ${lat.toFixed(5)}, ${lon.toFixed(5)} — saving…`;
      }
      $("btn_home_save").disabled = false;
      if (homeState.map && window.google) {
        const pos = { lat, lng: lon };
        if (!homeState.marker) {
          homeState.marker = new google.maps.Marker({
            position: pos, map: homeState.map, draggable: true,
          });
          homeState.marker.addListener("dragend", (e) => {
            setHomePin(e.latLng.lat(), e.latLng.lng());
          });
        } else {
          homeState.marker.setPosition(pos);
        }
        homeState.map.panTo(pos);
      }
      if (!opts.skipSave && !opts.skipMeta) {
        saveHomePin().catch((e) => log("Home save failed: " + e.message));
      }
    }

    async function saveHomePin() {
      if (state.locked) {
        log("Enrolled driver is locked — home cannot be changed");
        return;
      }
      if (homeState.lat == null || homeState.lon == null) return;
      if (homeState.saving) return;
      const id = driverId();
      if (!id) {
        log("Set a Driver ID before saving home");
        return;
      }
      homeState.saving = true;
      try {
        const res = await api("/api/register/home", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            driver_id: id,
            lat: homeState.lat,
            lon: homeState.lon,
          }),
        });
        log(`Home saved for ${res.driver_id}: ${res.home_lat}, ${res.home_lon}`);
        $("home_meta").textContent =
          `Saved home: ${Number(res.home_lat).toFixed(5)}, ${Number(res.home_lon).toFixed(5)}`;
        await refresh();
        await loadDrivers();
      } finally {
        homeState.saving = false;
      }
    }

    async function initHomeMap() {
      const cfg = await api("/api/standalone/config");
      const key = cfg.google_maps_api_key || "";
      if (!key) {
        $("home_meta").textContent = "Set GOOGLE_MAPS_API_KEY in secrets.env to enable the map picker.";
        return;
      }
      await new Promise((resolve, reject) => {
        if (window.google && window.google.maps) { resolve(); return; }
        const s = document.createElement("script");
        s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}`;
        s.async = true;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error("Google Maps failed to load"));
        document.head.appendChild(s);
      });
      const center = { lat: 12.9716, lng: 77.5946 };
      homeState.map = new google.maps.Map($("home-map"), {
        center, zoom: 12, mapTypeControl: false, streetViewControl: false,
        styles: [{ elementType: "geometry", stylers: [{ color: "#1a2332" }] }],
      });
      homeState.map.addListener("click", (e) => {
        setHomePin(e.latLng.lat(), e.latLng.lng());
      });
      homeState.ready = true;
      $("home_meta").textContent = "Click the map to drop a home pin.";
      log("Google Maps ready for home pin");
    }

    $("btn_home_geo").onclick = () => {
      if (!navigator.geolocation) {
        log("Geolocation not available");
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => setHomePin(pos.coords.latitude, pos.coords.longitude),
        (err) => log("Geo failed: " + err.message),
        { enableHighAccuracy: true, timeout: 12000 }
      );
    };

    $("btn_home_save").onclick = () => {
      saveHomePin().catch((e) => log("Home save failed: " + e.message));
    };

    async function loadDrivers({ suggestId = true } = {}) {
      const el = $("driver_list");
      try {
        const rows = await api("/api/register/drivers");
        if (!rows.length) {
          el.innerHTML = `<div class="chip warn">No drivers yet — create a Driver ID below.</div>`;
          if (suggestId) setDefaultDriverId([], { force: !state.driverIdTouched });
          return rows;
        }
        el.innerHTML = rows.map((d) => {
          const faceT = d.templates && d.templates.face;
          const voiceT = d.templates && d.templates.voice;
          const locked = !!d.locked || (faceT && voiceT);
          const action = locked ? "View" : (d.status === "capturing" || d.status === "need_home" || d.status === "ready_to_enroll" || d.status === "partial_templates" ? "Continue" : "Select");
          return `
            <div class="driver-row ${locked ? "locked-row" : ""}" data-id="${d.driver_id}">
              <div>
                <div class="name">${d.name || d.driver_id}${locked ? " 🔒" : ""}</div>
                <div class="meta">
                  face ${d.face_count}/${d.min_face} · voice ${d.voice_count}/${d.min_voice}
                  · home ${d.home_set ? "✓" : "–"}
                  · templates: voice ${voiceT ? "✓" : "–"} / face ${faceT ? "✓" : "–"}
                </div>
              </div>
              <span class="status ${d.status}">${locked ? "Locked · enrolled" : (d.status_label || d.status)}</span>
              <button type="button" class="secondary btn-pick ${locked ? "locked-pick" : ""}" data-id="${d.driver_id}" data-locked="${locked ? "1" : "0"}">${action}</button>
            </div>`;
        }).join("");
        el.querySelectorAll(".btn-pick").forEach((btn) => {
          btn.onclick = () => {
            state.driverIdTouched = true;
            $("driver_id").value = btn.dataset.id;
            refresh().catch((e) => log(e.message));
            log(
              btn.dataset.locked === "1"
                ? "Viewing locked enrolled driver " + btn.dataset.id
                : "Selected driver " + btn.dataset.id
            );
          };
        });
        if (suggestId) setDefaultDriverId(rows);
        return rows;
      } catch (e) {
        el.textContent = "Failed to load drivers: " + e.message;
        if (suggestId && !$("driver_id").value.trim()) {
          setDefaultDriverId([], { force: true });
        }
        return [];
      }
    }

    $("btn_drivers_refresh").onclick = () =>
      loadDrivers({ suggestId: !state.driverIdTouched });

    // Suggest next id from the table first; avoid refresh() on a blank id.
    loadDrivers({ suggestId: true })
      .then(() => {
        if (driverId()) return refresh();
      })
      .catch((e) => log(e.message));
    initHomeMap().catch((e) => {
      $("home_meta").textContent = "Maps unavailable: " + e.message;
      log("Maps: " + e.message);
    });
  </script>
</body>
</html>
"""
