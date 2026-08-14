"""Improved Auth — Stage-2 attack capture + train UI."""


def render_improved_auth() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>DriveAuth — Improved Auth</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #070b12;
      --panel: #0e1624;
      --border: #243247;
      --text: #e7eef8;
      --muted: #8fa3bc;
      --accent: #38bdf8;
      --ok: #34d399;
      --warn: #fbbf24;
      --danger: #f87171;
      --hl-bg: rgba(56, 189, 248, 0.12);
      --hl-border: rgba(56, 189, 248, 0.45);
      --font: "Sora", system-ui, sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font);
      color: var(--text);
      min-height: 100vh;
      background:
        radial-gradient(900px 420px at 12% -10%, rgba(56,189,248,0.14), transparent 55%),
        radial-gradient(700px 380px at 90% 0%, rgba(45,212,191,0.08), transparent 50%),
        var(--bg);
    }
    header {
      display: flex; justify-content: space-between; align-items: flex-end;
      gap: 1rem; padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border);
      background: rgba(8,12,20,0.85); backdrop-filter: blur(10px);
      position: sticky; top: 0; z-index: 20;
    }
    header h1 { font-size: 1.35rem; letter-spacing: -0.02em; }
    header p { color: var(--muted); font-size: 0.9rem; margin-top: 0.2rem; }
    .nav-row { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    a.nav {
      color: var(--muted); text-decoration: none; font-size: 0.85rem;
      border: 1px solid var(--border); padding: 0.4rem 0.7rem; border-radius: 999px;
    }
    a.nav:hover, a.nav.active { color: var(--text); border-color: var(--accent); }
    main { max-width: 1100px; margin: 0 auto; padding: 1.25rem 1.25rem 3rem; }
    .callout {
      background: var(--hl-bg);
      border: 1px solid var(--hl-border);
      border-radius: 14px;
      padding: 1.1rem 1.2rem;
      margin-bottom: 1.25rem;
      line-height: 1.55;
    }
    .callout strong { color: #7dd3fc; }
    .callout .local {
      display: inline-block; margin-top: 0.55rem; padding: 0.35rem 0.65rem;
      border-radius: 8px; background: rgba(52,211,153,0.12);
      border: 1px solid rgba(52,211,153,0.35); color: var(--ok); font-size: 0.9rem;
    }
    .panel {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 14px; padding: 1rem 1.1rem; margin-bottom: 1rem;
    }
    .panel h3 { font-size: 1.05rem; margin-bottom: 0.35rem; }
    .panel .sub { color: var(--muted); font-size: 0.85rem; margin-bottom: 0.75rem; }
    .row { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; }
    label { display: block; font-size: 0.78rem; color: var(--muted); margin-bottom: 0.25rem; }
    input[type=text] {
      background: #0a101a; border: 1px solid var(--border); color: var(--text);
      border-radius: 8px; padding: 0.5rem 0.65rem; min-width: 160px; font: inherit;
    }
    button {
      font: inherit; cursor: pointer; border: none; border-radius: 10px;
      padding: 0.55rem 0.9rem; background: var(--accent); color: #041018; font-weight: 600;
    }
    button.secondary { background: transparent; color: var(--text); border: 1px solid var(--border); }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    button.train {
      width: 100%; padding: 0.9rem 1rem; font-size: 1.05rem;
      background: linear-gradient(90deg, #22d3ee, #34d399); color: #04201a;
    }
    .chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.65rem; }
    .chip {
      font-size: 0.78rem; border: 1px solid var(--border); border-radius: 999px;
      padding: 0.2rem 0.55rem; color: var(--muted); font-family: var(--mono);
    }
    .chip.ok { color: var(--ok); border-color: #166534; }
    .chip.warn { color: var(--warn); border-color: #92400e; }
    .grid2 {
      display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem;
    }
    @media (max-width: 860px) { .grid2 { grid-template-columns: 1fr; } }
    .box {
      border: 1px solid var(--border); border-radius: 12px; padding: 0.85rem;
      background: rgba(8,14,24,0.55); display: flex; flex-direction: column; gap: 0.55rem;
    }
    .box h4 { font-size: 0.95rem; }
    .box .hint { color: var(--muted); font-size: 0.8rem; line-height: 1.4; }
    .box.auto {
      border-style: dashed; opacity: 0.92;
      background: rgba(52, 211, 153, 0.04);
    }
    .count { font-family: var(--mono); font-size: 0.85rem; color: var(--accent); }
    .path-hint {
      font-family: var(--mono); font-size: 0.72rem; color: var(--muted);
      word-break: break-all;
    }
    .cam-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 4/3;
      background: #0a0e14;
      border-radius: 10px;
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .cam-wrap video.preview {
      position: relative;
      z-index: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      background: #000;
      border-radius: 0;
      aspect-ratio: auto;
    }
    /* Same enroll guide as register / capture_own_face.py */
    .face-guide-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      z-index: 2;
      pointer-events: none;
    }
    .face-guide-label {
      position: absolute;
      left: 50%;
      top: calc(45% + 22%);
      transform: translateX(-50%);
      z-index: 3;
      font-size: 0.72rem;
      font-weight: 650;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: rgba(226, 232, 240, 0.95);
      text-shadow: 0 1px 3px rgba(0,0,0,0.9);
      pointer-events: none;
      white-space: nowrap;
    }
    .thumbs, .clips {
      display: flex; flex-wrap: wrap; gap: 0.35rem; min-height: 1.5rem;
    }
    .thumbs img {
      width: 56px; height: 56px; object-fit: cover; border-radius: 6px;
      border: 1px solid var(--border);
    }
    .clips span {
      font-size: 0.72rem; font-family: var(--mono); color: var(--muted);
      border: 1px solid var(--border); border-radius: 6px; padding: 0.15rem 0.4rem;
    }
    .log {
      white-space: pre-wrap; font-family: var(--mono); font-size: 0.78rem;
      color: var(--muted); max-height: 220px; overflow: auto;
      background: #080c14; border-radius: 8px; padding: 0.65rem; border: 1px solid var(--border);
    }
    .phrase {
      font-size: 0.85rem; color: #c7e7ff; background: rgba(56,189,248,0.08);
      border-radius: 8px; padding: 0.45rem 0.55rem; border: 1px solid rgba(56,189,248,0.2);
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Improved Auth</h1>
      <p>Optional Stage-2 hardening — attack samples + train</p>
    </div>
    <div class="nav-row">
      <a class="nav" href="/manual">Manual pipeline</a>
      <a class="nav" href="/standalone">Standalone pay</a>
      <a class="nav" href="/register">Register driver</a>
      <a class="nav active" href="/improved-auth">Improved Auth</a>
      <a class="nav" href="/fleet">Fleet health</a>
    </div>
  </header>

  <main>
    <section class="callout" id="explain">
      <strong>What is this?</strong>
      After you register, identity match is already cosine similarity against your template.
      This page optionally collects <em>attack / hard</em> examples so we can train small on-device
      heads (face PAD + face/voice calibrators) that make accept/reject steadier and catch spoofs.
      <br/>
      <strong>Why collect this?</strong>
      Real spoofs (screen replay, side pose) and hard voice cases (replay, noise, other speaker)
      teach the edge what <em>not</em> to accept for <em>this</em> driver — without changing the core matchers.
      <div class="local">🔒 Stays local on the edge device — not uploaded to a cloud. Don’t worry :)</div>
    </section>

    <section class="panel">
      <h3>Driver</h3>
      <p class="sub">Must already be enrolled on Register (templates present). Attack capture is allowed after lock.</p>
      <div class="row">
        <div>
          <label for="driver_id">Driver ID</label>
          <input id="driver_id" type="text" value="parth" autocomplete="off" />
        </div>
        <button id="btn_refresh" class="secondary" type="button">Refresh status</button>
        <button id="btn_autofill" class="secondary" type="button">Auto-fill blur + silent now</button>
      </div>
      <div class="chips" id="chips"></div>
    </section>

    <section class="panel">
      <h3>Face attack sets</h3>
      <p class="sub">
        Captures POST to the backend and land under
        <code>data/&lt;driver&gt;/face/&lt;split&gt;/</code>.
        Blur is generated automatically on Train / Auto-fill.
      </p>
      <div class="row" style="margin-bottom:0.75rem">
        <button id="btn_cam" class="secondary" type="button">Start camera</button>
      </div>
      <div class="grid2" style="margin-top:0.85rem">
        <div class="box" data-face-split="attack_replay_screen">
          <h4>Replay screen</h4>
          <p class="hint">Hold a phone/laptop showing your face (or a photo) in front of the camera — screen replay attack.</p>
          <p class="path-hint" id="path_face_attack_replay_screen">→ data/…/face/attack_replay_screen/</p>
          <div class="cam-wrap">
            <video class="preview cam-feed" data-cam="attack_replay_screen" autoplay playsinline muted></video>
            <svg class="face-guide-svg" viewBox="0 0 100 75" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <mask id="face-guide-mask-replay">
                  <rect width="100" height="75" fill="white" />
                  <ellipse cx="50" cy="33.75" rx="12.75" ry="15" fill="black" />
                </mask>
              </defs>
              <rect width="100" height="75" fill="rgba(0,0,0,0.32)" mask="url(#face-guide-mask-replay)" />
              <ellipse
                cx="50" cy="33.75" rx="12.75" ry="15"
                fill="none" stroke="#22c55e" stroke-width="2.5"
                vector-effect="non-scaling-stroke"
              />
            </svg>
            <div class="face-guide-label">Place face here</div>
          </div>
          <div class="count" id="cnt_face_attack_replay_screen">0 / 3</div>
          <button type="button" data-snap="attack_replay_screen" disabled>Capture → save</button>
          <div class="thumbs" id="thumbs_attack_replay_screen"></div>
        </div>
        <div class="box" data-face-split="attack_side">
          <h4>Side angle</h4>
          <p class="hint">Turn your head clearly left or right — non-frontal pose (oval is a framing guide only).</p>
          <p class="path-hint" id="path_face_attack_side">→ data/…/face/attack_side/</p>
          <div class="cam-wrap">
            <video class="preview cam-feed" data-cam="attack_side" autoplay playsinline muted></video>
            <svg class="face-guide-svg" viewBox="0 0 100 75" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <mask id="face-guide-mask-side">
                  <rect width="100" height="75" fill="white" />
                  <ellipse cx="50" cy="33.75" rx="12.75" ry="15" fill="black" />
                </mask>
              </defs>
              <rect width="100" height="75" fill="rgba(0,0,0,0.32)" mask="url(#face-guide-mask-side)" />
              <ellipse
                cx="50" cy="33.75" rx="12.75" ry="15"
                fill="none" stroke="#22c55e" stroke-width="2.5"
                vector-effect="non-scaling-stroke"
              />
            </svg>
            <div class="face-guide-label">Place face here</div>
          </div>
          <div class="count" id="cnt_face_attack_side">0 / 3</div>
          <button type="button" data-snap="attack_side" disabled>Capture → save</button>
          <div class="thumbs" id="thumbs_attack_side"></div>
        </div>
        <div class="box auto" data-face-split="attack_blur">
          <h4>Blur (automatic)</h4>
          <p class="hint">We synthesize soft-blur attacks from your enroll faces — you don’t need to capture these.</p>
          <p class="path-hint">→ data/&lt;driver&gt;/face/attack_blur/</p>
          <div class="count" id="cnt_face_attack_blur">0 (auto)</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <h3>Voice attack sets</h3>
      <p class="sub">Enable the mic once, then record into each box. Silent clips are generated automatically.</p>
      <div class="row" style="margin-bottom:0.75rem">
        <button id="btn_mic" class="secondary" type="button">Enable mic</button>
      </div>
      <div class="grid2">
        <div class="box" data-voice-split="attack_replay">
          <h4>Replay (record)</h4>
          <p class="hint">Play a prior recording of your voice from another device into this mic (replay attack).</p>
          <p class="path-hint" id="path_voice_attack_replay">→ data/…/voice/attack_replay/</p>
          <div class="phrase">Hold record while the replay plays (~2.5s).</div>
          <div class="count" id="cnt_voice_attack_replay">0 / 3</div>
          <button type="button" data-rec="attack_replay" disabled>Record → save</button>
          <div class="clips" id="clips_attack_replay"></div>
        </div>
        <div class="box" data-voice-split="noisy">
          <h4>Music + commands</h4>
          <p class="hint">Play music in the background and speak a payment command over it.</p>
          <p class="path-hint" id="path_voice_noisy">→ data/…/voice/noisy/</p>
          <div class="phrase" id="noisy_phrase">Say: “please pay Mom fifty dollars from my checking account”</div>
          <div class="count" id="cnt_voice_noisy">0 / 3</div>
          <button type="button" data-rec="noisy" disabled>Record → save</button>
          <div class="clips" id="clips_noisy"></div>
        </div>
        <div class="box" data-voice-split="attack_other_speaker">
          <h4>Other speaker</h4>
          <p class="hint">Have someone else say a command (or speak in a clearly different voice).</p>
          <p class="path-hint" id="path_voice_attack_other_speaker">→ data/…/voice/attack_other_speaker/</p>
          <div class="phrase">Say: “transfer two hundred dollars to Raj for dinner”</div>
          <div class="count" id="cnt_voice_attack_other_speaker">0 / 3</div>
          <button type="button" data-rec="attack_other_speaker" disabled>Record → save</button>
          <div class="clips" id="clips_attack_other_speaker"></div>
        </div>
        <div class="box auto" data-voice-split="attack_silent">
          <h4>Silent (automatic)</h4>
          <p class="hint">Near-silent clips are generated for you — no recording needed.</p>
          <p class="path-hint">→ data/&lt;driver&gt;/voice/attack_silent/</p>
          <div class="count" id="cnt_voice_attack_silent">0 (auto)</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <h3>Train</h3>
      <p class="sub">
        Runs auto blur + silent, syncs enroll→genuine if needed, then trains
        <code>face_pad</code>, <code>face_calibrator</code>, and <code>voice_calibrator</code>
        for this driver. Templates are not rebuilt.
      </p>
      <button id="btn_train" class="train" type="button" disabled>Train improved auth models</button>
      <div class="log" id="log" style="margin-top:0.75rem">Ready.</div>
    </section>
  </main>

  <script>
    const MIN = 3;
    const state = {
      stream: null,
      audioCtx: null,
      micStream: null,
      micReady: false,
      camReady: false,
      status: null,
    };
    const $ = (id) => document.getElementById(id);
    const log = (msg) => {
      const el = $("log");
      const ts = new Date().toLocaleTimeString();
      el.textContent = `[${ts}] ${msg}\\n` + el.textContent;
    };
    const driverId = () => ($("driver_id").value || "").trim();

    function adminHeaders(extra = {}) {
      return Object.assign({}, extra || {});
    }
    async function api(path, opts = {}) {
      const opts2 = Object.assign({ credentials: "same-origin" }, opts);
      const isForm = opts2.body instanceof FormData;
      opts2.headers = adminHeaders(opts2.headers || {});
      if (!isForm && opts2.body && typeof opts2.body === "string" && !opts2.headers["Content-Type"]) {
        opts2.headers["Content-Type"] = "application/json";
      }
      const res = await fetch(path, opts2);
      if (res.status === 401) {
        const overlay = document.getElementById("driveauth-login");
        if (overlay) overlay.style.display = "flex";
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail || data.error || res.statusText;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      return data;
    }

    function encodeWav(float32, sampleRate) {
      const buffer = new ArrayBuffer(44 + float32.length * 2);
      const view = new DataView(buffer);
      const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
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

    function paintStatus(s) {
      state.status = s;
      const min = s.min_per_box || MIN;
      const id = s.driver_id || driverId();
      const setCnt = (elId, n, auto) => {
        const el = $(elId);
        if (!el) return;
        el.textContent = auto ? `${n} (auto)` : `${n} / ${min}`;
        el.style.color = (auto ? n > 0 : n >= min) ? "var(--ok)" : "var(--warn)";
      };
      setCnt("cnt_face_attack_replay_screen", s.face.attack_replay_screen);
      setCnt("cnt_face_attack_side", s.face.attack_side);
      setCnt("cnt_face_attack_blur", s.face.attack_blur, true);
      setCnt("cnt_voice_attack_replay", s.voice.attack_replay);
      setCnt("cnt_voice_noisy", s.voice.noisy);
      setCnt("cnt_voice_attack_other_speaker", s.voice.attack_other_speaker);
      setCnt("cnt_voice_attack_silent", s.voice.attack_silent, true);

      const setPath = (elId, rel) => {
        const el = $(elId);
        if (el) el.textContent = `→ data/${id}/${rel}/`;
      };
      setPath("path_face_attack_replay_screen", "face/attack_replay_screen");
      setPath("path_face_attack_side", "face/attack_side");
      setPath("path_voice_attack_replay", "voice/attack_replay");
      setPath("path_voice_noisy", "voice/noisy");
      setPath("path_voice_attack_other_speaker", "voice/attack_other_speaker");

      const chips = [];
      chips.push(`<span class="chip ${s.templates.face && s.templates.voice ? "ok" : "warn"}">templates ${s.templates.face && s.templates.voice ? "ready" : "missing"}</span>`);
      chips.push(`<span class="chip ${s.face_user_ok ? "ok" : "warn"}">face attacks</span>`);
      chips.push(`<span class="chip ${s.voice_user_ok ? "ok" : "warn"}">voice attacks</span>`);
      chips.push(`<span class="chip ${s.ready_to_train ? "ok" : "warn"}">${s.ready_to_train ? "ready to train" : "need more samples"}</span>`);
      const st2 = s.stage2 || {};
      for (const k of Object.keys(st2)) {
        chips.push(`<span class="chip ${st2[k].present ? "ok" : ""}">${k}${st2[k].present ? " ✓" : ""}</span>`);
      }
      $("chips").innerHTML = chips.join("");

      const paintFiles = (kind, split, files) => {
        if (kind === "face") {
          const el = $(`thumbs_${split}`);
          if (!el) return;
          el.innerHTML = (files || []).slice(-8).map((name) =>
            `<img src="/api/improved-auth/preview/face/${encodeURIComponent(s.driver_id)}/${encodeURIComponent(split)}/${encodeURIComponent(name)}?t=${Date.now()}" alt="${name}" title="${name}" />`
          ).join("");
        } else {
          const el = $(`clips_${split}`);
          if (!el) return;
          el.innerHTML = (files || []).slice(-8).map((name) => `<span>${name}</span>`).join("");
        }
      };
      paintFiles("face", "attack_replay_screen", (s.face_files || {}).attack_replay_screen);
      paintFiles("face", "attack_side", (s.face_files || {}).attack_side);
      paintFiles("voice", "attack_replay", (s.voice_files || {}).attack_replay);
      paintFiles("voice", "noisy", (s.voice_files || {}).noisy);
      paintFiles("voice", "attack_other_speaker", (s.voice_files || {}).attack_other_speaker);

      $("btn_train").disabled = !s.ready_to_train;
      document.querySelectorAll("[data-snap]").forEach((b) => {
        b.disabled = !state.camReady;
      });
    }

    async function refresh() {
      const id = driverId();
      if (!id) throw new Error("enter a driver id");
      const s = await api(`/api/improved-auth/status?driver_id=${encodeURIComponent(id)}`);
      paintStatus(s);
      return s;
    }

    $("btn_refresh").onclick = async () => {
      try { await refresh(); log("Status refreshed"); }
      catch (e) { log("Error: " + e.message); }
    };

    $("btn_autofill").onclick = async () => {
      try {
        const res = await api("/api/improved-auth/auto-fill", {
          method: "POST",
          body: JSON.stringify({ driver_id: driverId() }),
        });
        log("Auto-fill: " + JSON.stringify(res.prepared || res));
        await refresh();
      } catch (e) { log("Auto-fill error: " + e.message); }
    };

    function bindCameraFeeds(stream) {
      document.querySelectorAll("video.cam-feed").forEach((v) => {
        v.srcObject = stream;
        v.play().catch(() => {});
      });
    }

    $("btn_cam").onclick = async () => {
      try {
        state.stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
          audio: false,
        });
        bindCameraFeeds(state.stream);
        state.camReady = true;
        document.querySelectorAll("[data-snap]").forEach((b) => { b.disabled = false; });
        log("Camera ready — captures save via /api/improved-auth/face → data/<driver>/face/<split>/");
      } catch (e) { log("Camera error: " + e.message); }
    };

    function videoForSplit(split) {
      return document.querySelector(`video.cam-feed[data-cam="${split}"]`)
        || document.querySelector("video.cam-feed");
    }

    async function snapFace(split) {
      if (!state.camReady || !state.stream) throw new Error("start the camera first");
      const v = videoForSplit(split);
      if (!v || !v.videoWidth) throw new Error("camera not streaming yet — wait a moment");
      const canvas = document.createElement("canvas");
      canvas.width = v.videoWidth || 640;
      canvas.height = v.videoHeight || 480;
      canvas.getContext("2d").drawImage(v, 0, 0);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
      if (!blob) throw new Error("failed to encode JPEG");
      const fd = new FormData();
      fd.append("driver_id", driverId());
      fd.append("split", split);
      fd.append("file", blob, `${split}.jpg`);
      const res = await api("/api/improved-auth/face", { method: "POST", body: fd });
      log(`Saved face → data/${res.path}`);
      await refresh();
    }

    document.querySelectorAll("[data-snap]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try { await snapFace(btn.getAttribute("data-snap")); }
        catch (e) { log("Capture error: " + e.message); }
        finally { btn.disabled = !state.camReady; }
      });
    });

    $("btn_mic").onclick = async () => {
      try {
        state.micStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
          video: false,
        });
        state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        state.micReady = true;
        document.querySelectorAll("[data-rec]").forEach((b) => { b.disabled = false; });
        log("Mic ready — recordings save via /api/improved-auth/voice → data/<driver>/voice/<split>/");
      } catch (e) { log("Mic error: " + e.message); }
    };

    async function recordVoice(split, seconds = 2.5) {
      if (!state.micReady || !state.micStream) throw new Error("enable the mic first");
      const ctx = state.audioCtx;
      if (ctx.state === "suspended") await ctx.resume();
      const src = ctx.createMediaStreamSource(state.micStream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [];
      proc.onaudioprocess = (ev) => {
        chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
      };
      src.connect(proc);
      proc.connect(ctx.destination);
      await new Promise((r) => setTimeout(r, seconds * 1000));
      proc.disconnect();
      src.disconnect();
      const len = chunks.reduce((a, c) => a + c.length, 0);
      const merged = new Float32Array(len);
      let off = 0;
      for (const c of chunks) { merged.set(c, off); off += c.length; }
      const blob = encodeWav(merged, ctx.sampleRate);
      const fd = new FormData();
      fd.append("driver_id", driverId());
      fd.append("split", split);
      fd.append("file", blob, `${split}.wav`);
      const res = await api("/api/improved-auth/voice", { method: "POST", body: fd });
      log(`Saved voice → data/${res.path}`);
      await refresh();
    }

    document.querySelectorAll("[data-rec]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try { await recordVoice(btn.getAttribute("data-rec")); }
        catch (e) { log("Record error: " + e.message); }
        finally { btn.disabled = !state.micReady; }
      });
    });

    $("btn_train").onclick = async () => {
      $("btn_train").disabled = true;
      log("Training started… (may take a minute)");
      try {
        const res = await api("/api/improved-auth/train", {
          method: "POST",
          body: JSON.stringify({ driver_id: driverId() }),
        });
        log("Train OK:\\n" + JSON.stringify(res, null, 2));
        await refresh();
      } catch (e) {
        log("Train error: " + e.message);
        await refresh().catch(() => {});
      }
    };

    refresh().catch((e) => log("Status error: " + e.message));
  </script>
</body>
</html>
"""
