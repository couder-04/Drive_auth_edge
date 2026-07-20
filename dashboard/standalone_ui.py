"""Standalone Pay panel HTML/CSS/JS injected into the main dashboard."""

from __future__ import annotations


def panel_css() -> str:
    return """
    .pay-standalone {
      border: 1px solid rgba(56, 189, 248, 0.35);
      border-radius: 16px;
      padding: 1.1rem 1.15rem 1.2rem;
      margin-bottom: 1.1rem;
      background:
        linear-gradient(145deg, rgba(56,189,248,0.08), transparent 50%),
        rgba(14, 22, 36, 0.9);
    }
    .pay-standalone > header {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      flex-wrap: wrap;
      align-items: flex-start;
      margin-bottom: 0.85rem;
      border: none;
      padding: 0;
      background: none;
    }
    .pay-standalone h2 {
      font-size: 1.05rem;
      margin: 0;
      letter-spacing: -0.02em;
    }
    .pay-standalone .sub {
      color: var(--muted);
      font-size: 0.78rem;
      margin-top: 0.2rem;
    }
    .pay-grid {
      display: grid;
      grid-template-columns: 1.1fr 1fr 1fr;
      gap: 0.85rem;
    }
    @media (max-width: 1100px) {
      .pay-grid { grid-template-columns: 1fr; }
    }
    .pay-card {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.75rem 0.8rem;
      background: rgba(6, 10, 16, 0.45);
    }
    .pay-card h3 {
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--sky);
      margin: 0 0 0.55rem;
    }
    .slot-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.45rem;
    }
    .slot {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.4rem 0.5rem;
      background: rgba(0,0,0,0.2);
      transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
    }
    .slot.ask {
      border-color: rgba(251,191,36,0.75);
      background: rgba(251,191,36,0.12);
      box-shadow: 0 0 0 1px rgba(251,191,36,0.25);
    }
    .slot label {
      display: block;
      font-size: 0.62rem;
      color: var(--faint);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin: 0 0 0.15rem;
    }
    .slot input, .pay-card select {
      width: 100%;
      background: transparent;
      border: none;
      color: var(--text);
      font-family: var(--mono);
      font-size: 0.9rem;
      padding: 0;
    }
    .pay-card select {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.4rem 0.5rem;
      background: rgba(0,0,0,0.25);
      margin-bottom: 0.5rem;
    }
    #pay-transcript {
      font-family: var(--mono);
      font-size: 0.78rem;
      color: var(--muted);
      min-height: 2.4em;
      margin: 0.4rem 0 0.55rem;
    }
    #pay-prompt {
      font-size: 0.8rem;
      color: var(--stepup);
      min-height: 1.2em;
      margin-bottom: 0.45rem;
    }
    #pay-map {
      width: 100%;
      height: 180px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #060a10;
      margin: 0.4rem 0;
    }
    #pay-cam {
      width: 100%;
      aspect-ratio: 4/3;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #060a10;
      object-fit: cover;
    }
    .pay-actions { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
    .pay-actions button {
      border: none;
      border-radius: 8px;
      padding: 0.45rem 0.75rem;
      font-weight: 650;
      font-size: 0.8rem;
      cursor: pointer;
      background: var(--sky);
      color: #041018;
    }
    .pay-actions button.secondary {
      background: rgba(255,255,255,0.06);
      color: var(--text);
      border: 1px solid var(--border);
    }
    .pay-actions button:disabled { opacity: 0.45; cursor: not-allowed; }
    .pay-actions button.recording {
      background: var(--reject);
      color: white;
      animation: pulse-dot 1s ease-in-out infinite;
    }
    #pay-dist {
      font-family: var(--mono);
      font-size: 0.72rem;
      color: var(--muted);
    }
    .pay-badge {
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 0.25rem 0.55rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .pay-badge.on { color: var(--cyan); border-color: rgba(45,212,191,0.45); }
    .pay-badge.warn { color: var(--stepup); border-color: rgba(251,191,36,0.45); }
    .pay-card.locked {
      position: relative;
      opacity: 0.55;
      pointer-events: none;
    }
    .pay-card.locked::after,
    .pay-face-body.locked::after {
      content: attr(data-lock);
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 1rem;
      font-size: 0.78rem;
      font-weight: 650;
      letter-spacing: 0.02em;
      color: var(--stepup);
      background: rgba(6, 10, 16, 0.72);
      border-radius: 12px;
      pointer-events: none;
    }
    .pay-face-body {
      position: relative;
      border-radius: 10px;
    }
    .pay-face-body.locked {
      opacity: 0.7;
      pointer-events: none;
      min-height: 140px;
    }
    .pay-face-body.locked #pay-cam-start,
    .pay-face-body.locked #pay-cam-snap,
    .finger-wrap.locked-inline #pay-finger {
      opacity: 0.35;
      cursor: not-allowed !important;
    }
    .pay-card .lock-note {
      font-size: 0.7rem;
      color: var(--faint);
      margin-top: 0.35rem;
    }
    .finger-wrap {
      position: relative;
      margin-top: 0.65rem;
      border-radius: 10px;
      min-height: 64px;
    }
    .finger-wrap.locked-inline {
      opacity: 0.85;
      pointer-events: none;
    }
    .finger-wrap.locked-inline::after {
      content: attr(data-lock);
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 0.5rem;
      font-size: 0.72rem;
      font-weight: 650;
      letter-spacing: 0.02em;
      color: var(--stepup);
      background: rgba(6, 10, 16, 0.78);
      border-radius: 10px;
      pointer-events: none;
      z-index: 2;
    }
    """


def panel_html() -> str:
    return """
    <section class="pay-standalone" id="pay-standalone">
      <header>
        <div>
          <h2>Pay · standalone</h2>
          <div class="sub">
            Voice + location first → face unlocks on threshold miss → finger unlocks on step-up
          </div>
        </div>
        <div style="display:flex;gap:0.4rem;align-items:center;flex-wrap:wrap">
          <span class="pay-badge" id="pay-or-badge">OpenRouter</span>
          <span class="pay-badge" id="pay-maps-badge">Maps</span>
        </div>
      </header>
      <div class="pay-grid">
        <div class="pay-card">
          <h3>1 · Speak payment</h3>
          <label style="font-size:0.72rem;color:var(--muted)">Driver</label>
          <select id="pay-driver"></select>
          <div id="pay-transcript">Transcript will appear here…</div>
          <div id="pay-prompt"></div>
          <div class="slot-grid">
            <div class="slot" data-field="amount"><label>Amount</label><input id="pay-amount" type="number" step="1" value="" placeholder="—" /></div>
            <div class="slot" data-field="beneficiary"><label>Beneficiary</label><input id="pay-beneficiary" type="text" value="" placeholder="—" /></div>
            <div class="slot" data-field="action"><label>Action</label><input id="pay-action" type="text" value="pay" /></div>
            <div class="slot" data-field="currency"><label>Currency</label><input id="pay-currency" type="text" value="INR" /></div>
          </div>
          <div class="pay-actions">
            <button type="button" id="pay-rec">Hold / click to talk</button>
            <button type="button" class="secondary" id="pay-intent-refresh">Re-parse text</button>
          </div>
          <audio id="pay-tts" style="display:none"></audio>
        </div>
        <div class="pay-card">
          <h3>2 · Location (required)</h3>
          <div id="pay-map"></div>
          <div id="pay-dist">Pin location on the map before authorize</div>
          <div class="pay-actions">
            <button type="button" class="secondary" id="pay-geo">Browser GPS</button>
            <button type="button" class="secondary" id="pay-clear-gps">Clear pin</button>
          </div>
          <div class="finger-wrap locked-inline" id="pay-finger-wrap" data-lock="Fingerprint locked · wait for face escalate">
            <label style="display:block;font-size:0.72rem;color:var(--muted)">
              Finger (manual until HW) <span id="pay-finger-val">—</span>
            </label>
            <input id="pay-finger" type="range" min="0" max="1" step="0.01" value="0.85" style="width:100%" disabled aria-disabled="true" />
            <div class="lock-note" id="pay-finger-note">Locked until face also fails the accept bar.</div>
          </div>
        </div>
        <div class="pay-card" id="pay-face-card" data-lock="Face locked · authorize with voice + location first">
          <h3>3 · Face (escalation)</h3>
          <div id="pay-face-lock" class="pay-face-body locked" data-lock="Face locked · authorize with voice + location first">
            <video id="pay-cam" autoplay playsinline muted></video>
            <div class="pay-actions">
              <button type="button" class="secondary" id="pay-cam-start" disabled aria-disabled="true">Start camera · locked</button>
              <button type="button" class="secondary" id="pay-cam-snap" disabled aria-disabled="true">Snap face · locked</button>
            </div>
          </div>
          <canvas id="pay-face-canvas" style="display:none"></canvas>
          <div class="pay-actions" style="margin-top:0.75rem">
            <button type="button" id="pay-run" disabled>Authorize payment</button>
          </div>
          <p style="margin:0.5rem 0 0;font-size:0.7rem;color:var(--faint)" id="pay-auth-hint">
            First run: voice + location only. Ladder lights only unlocked rungs.
          </p>
        </div>
      </div>
    </section>
    """


def panel_script() -> str:
    return r"""
    /* ── Standalone Pay ───────────────────────────────────────────── */
    const pay = {
      cfg: null,
      wavBlob: null,
      faceBlob: null,
      gps: { lat: null, lon: null },
      map: null,
      marker: null,
      stream: null,
      camStream: null,
      recording: false,
      audioCtx: null,
      micStream: null,
      unlock: { face: false, finger: false },
    };

    function encodeWavPay(float32, sampleRate) {
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

    function applyIntentSlots(intent) {
      if (!intent) return;
      if (intent.amount != null && intent.amount !== "") {
        document.getElementById("pay-amount").value = intent.amount || "";
      }
      if (intent.beneficiary != null) {
        document.getElementById("pay-beneficiary").value = intent.beneficiary || "";
      }
      if (intent.action) document.getElementById("pay-action").value = intent.action;
      if (intent.currency) document.getElementById("pay-currency").value = intent.currency;
      if (intent.transcript) {
        document.getElementById("pay-transcript").textContent = intent.transcript;
      }
      updatePayReady();
    }

    function resetPayUnlock() {
      pay.unlock = { face: false, finger: false };
      pay.faceBlob = null;
      const prompt = document.getElementById("pay-prompt");
      if (prompt) prompt.dataset.needFace = "0";
      applyPayUnlockUI();
    }

    function applyPayUnlockUI() {
      const faceBody = document.getElementById("pay-face-lock");
      const camStart = document.getElementById("pay-cam-start");
      const camSnap = document.getElementById("pay-cam-snap");
      if (pay.unlock.face) {
        faceBody.classList.remove("locked");
        faceBody.removeAttribute("data-lock");
        camStart.disabled = false;
        camSnap.disabled = false;
        camStart.setAttribute("aria-disabled", "false");
        camSnap.setAttribute("aria-disabled", "false");
        camStart.textContent = "Start camera";
        camSnap.textContent = "Snap face";
      } else {
        faceBody.classList.add("locked");
        faceBody.setAttribute("data-lock", "Camera locked · unlocks when voice escalates");
        camStart.disabled = true;
        camSnap.disabled = true;
        camStart.setAttribute("aria-disabled", "true");
        camSnap.setAttribute("aria-disabled", "true");
        camStart.textContent = "Start camera · locked";
        camSnap.textContent = "Snap face · locked";
        // Drop any prior capture if face is locked again.
        pay.faceBlob = null;
        if (pay.camStream) {
          try { pay.camStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
          pay.camStream = null;
          const cam = document.getElementById("pay-cam");
          if (cam) cam.srcObject = null;
        }
      }

      const fingerWrap = document.getElementById("pay-finger-wrap");
      const finger = document.getElementById("pay-finger");
      const fingerNote = document.getElementById("pay-finger-note");
      if (pay.unlock.finger) {
        fingerWrap.classList.remove("locked-inline");
        fingerWrap.removeAttribute("data-lock");
        finger.disabled = false;
        finger.setAttribute("aria-disabled", "false");
        document.getElementById("pay-finger-val").textContent = finger.value;
        fingerNote.textContent = "Set a mock fingerprint score, then authorize again.";
      } else {
        fingerWrap.classList.add("locked-inline");
        fingerWrap.setAttribute("data-lock", "Fingerprint locked · wait for face escalate");
        finger.disabled = true;
        finger.setAttribute("aria-disabled", "true");
        finger.value = "0.85";
        document.getElementById("pay-finger-val").textContent = "—";
        fingerNote.textContent = "Locked until face also fails the accept bar.";
      }
      updatePayReady();
    }

    function updatePayReady() {
      const amt = Number(document.getElementById("pay-amount").value || 0);
      const ben = (document.getElementById("pay-beneficiary").value || "").trim();
      const hasGps = pay.gps.lat != null && pay.gps.lon != null;
      const prompt = document.getElementById("pay-prompt");
      let ok = amt > 0 && !!ben && !!pay.wavBlob && hasGps;
      if (pay.unlock.face && !pay.faceBlob && prompt && prompt.dataset.needFace === "1") {
        ok = false;
      }
      document.getElementById("pay-run").disabled = !ok;
      const hint = document.getElementById("pay-auth-hint");
      if (!hasGps) {
        hint.textContent = "Pin a location (vs enrolled home) before authorize.";
      } else if (pay.unlock.face && !pay.faceBlob) {
        hint.textContent = "Voice below bar — snap a face, then authorize again.";
      } else if (pay.unlock.finger) {
        hint.textContent = "Face stepped up — set finger score, then authorize again.";
      } else {
        hint.textContent = "First run: voice + location only. Ladder lights only unlocked rungs.";
      }
    }

    async function playTts(b64, mime) {
      if (!b64) return;
      const audio = document.getElementById("pay-tts");
      audio.src = `data:${mime || "audio/mpeg"};base64,${b64}`;
      try { await audio.play(); } catch (_) { /* autoplay may block */ }
    }

    function setPayGps(lat, lon) {
      pay.gps.lat = lat;
      pay.gps.lon = lon;
      document.getElementById("pay-dist").textContent =
        `GPS ${lat.toFixed(5)}, ${lon.toFixed(5)} — distance vs driver home on authorize`;
      if (pay.map && window.google) {
        const pos = { lat, lng: lon };
        if (!pay.marker) {
          pay.marker = new google.maps.Marker({ position: pos, map: pay.map, draggable: true });
          pay.marker.addListener("dragend", (e) => setPayGps(e.latLng.lat(), e.latLng.lng()));
        } else {
          pay.marker.setPosition(pos);
        }
        pay.map.panTo(pos);
      }
      updatePayReady();
    }

    async function ensurePayMap() {
      if (!pay.cfg || !pay.cfg.google_maps_api_key) return;
      if (!(window.google && window.google.maps)) {
        await new Promise((resolve, reject) => {
          const s = document.createElement("script");
          s.src = "https://maps.googleapis.com/maps/api/js?key=" +
            encodeURIComponent(pay.cfg.google_maps_api_key);
          s.async = true;
          s.onload = () => resolve();
          s.onerror = () => reject(new Error("Maps load failed"));
          document.head.appendChild(s);
        });
      }
      if (pay.map) return;
      pay.map = new google.maps.Map(document.getElementById("pay-map"), {
        center: { lat: 12.9716, lng: 77.5946 },
        zoom: 12,
        mapTypeControl: false,
        streetViewControl: false,
      });
      pay.map.addListener("click", (e) => setPayGps(e.latLng.lat(), e.latLng.lng()));
    }

    function highlightAskField(field) {
      document.querySelectorAll(".slot[data-field]").forEach((el) => {
        el.classList.toggle("ask", !!field && el.dataset.field === field);
      });
      if (field) {
        const input = document.getElementById(
          field === "amount" ? "pay-amount"
          : field === "beneficiary" ? "pay-beneficiary"
          : field === "action" ? "pay-action"
          : field === "currency" ? "pay-currency" : null
        );
        if (input) input.focus();
      }
    }

    async function handleIntentResponse(data) {
      applyIntentSlots(data.intent || {});
      const promptEl = document.getElementById("pay-prompt");
      const field = data.ask_field || null;
      highlightAskField(data.status === "need_input" ? field : null);
      if (data.status === "need_input") {
        const col = field ? ` [${field}]` : "";
        promptEl.textContent = "TTS" + col + ": " + (data.prompt || "Need more info");
        await playTts(data.tts_audio_b64, data.tts_mime);
      } else if (data.status === "ready") {
        promptEl.textContent = "Slots ready — pin location, then authorize.";
      } else if (data.status === "not_payment") {
        promptEl.textContent = "Not a payment utterance — try “pay Mom 50”.";
      } else if (data.status === "error") {
        promptEl.textContent = "Error: " + (data.error || "unknown");
      } else {
        promptEl.textContent = data.status || "";
      }
      updatePayReady();
    }

    async function recordPayClip(seconds = 3.5) {
      if (pay.recording) return;
      pay.recording = true;
      resetPayUnlock();
      const btn = document.getElementById("pay-rec");
      btn.classList.add("recording");
      btn.textContent = "Listening…";
      try {
        if (!pay.micStream) {
          pay.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        }
        const ctx = pay.audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        pay.audioCtx = ctx;
        if (ctx.state === "suspended") await ctx.resume();
        const source = ctx.createMediaStreamSource(pay.micStream);
        const processor = ctx.createScriptProcessor(4096, 1, 1);
        const chunks = [];
        const target = Math.floor(ctx.sampleRate * seconds);
        await new Promise((resolve) => {
          processor.onaudioprocess = (e) => {
            chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
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
        for (const c of chunks) { merged.set(c, off); off += c.length; }
        pay.wavBlob = encodeWavPay(merged.slice(0, target), ctx.sampleRate);

        const fd = new FormData();
        fd.append("file", pay.wavBlob, "pay.wav");
        fd.append("amount", document.getElementById("pay-amount").value || "0");
        fd.append("beneficiary", document.getElementById("pay-beneficiary").value || "");
        fd.append("action", document.getElementById("pay-action").value || "pay");
        fd.append("currency", document.getElementById("pay-currency").value || "INR");
        const res = await adminFetch("/api/standalone/transcribe", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || res.statusText);
        await handleIntentResponse(data);
      } catch (e) {
        document.getElementById("pay-prompt").textContent = "STT failed: " + e.message;
      } finally {
        pay.recording = false;
        btn.classList.remove("recording");
        btn.textContent = "Hold / click to talk";
        updatePayReady();
      }
    }

    function applyEscalationUnlock(data) {
      const pipe = data.pipeline || {};
      const next = pipe.next_unlock;
      const prompt = document.getElementById("pay-prompt");
      prompt.dataset.needFace = "0";
      if (next === "face") {
        // Camera unlocks here; fingerprint stays locked until face escalates.
        pay.unlock.face = true;
        pay.unlock.finger = false;
        prompt.dataset.needFace = "1";
        prompt.textContent =
          "Escalated at Voice — Start camera is unlocked. Snap face, then Authorize again. Fingerprint stays locked.";
      } else if (next === "finger") {
        pay.unlock.face = true;
        pay.unlock.finger = true;
        prompt.textContent =
          "Escalated at Face — fingerprint slider unlocked. Set a score, then Authorize again.";
      } else if (data.decision === "ACCEPT") {
        prompt.textContent = "Accepted.";
      } else if (data.decision === "STEP_UP_REQUIRED") {
        pay.unlock.face = true;
        pay.unlock.finger = true;
        prompt.textContent =
          "Step-up required — fingerprint slider unlocked. Set a score and re-authorize.";
      } else if (data.decision === "REJECT") {
        prompt.textContent = "Rejected — ladder exhausted.";
      }
      applyPayUnlockUI();
    }

    async function runStandaloneAuth() {
      const amt = Number(document.getElementById("pay-amount").value || 0);
      const ben = (document.getElementById("pay-beneficiary").value || "").trim();
      if (!pay.wavBlob || !(amt > 0) || !ben) {
        document.getElementById("pay-prompt").textContent = "Need amount, beneficiary, and a voice clip.";
        return;
      }
      if (pay.gps.lat == null || pay.gps.lon == null) {
        document.getElementById("pay-prompt").textContent =
          "Location required — pin the map or use browser GPS.";
        return;
      }
      if (pay.unlock.face && !pay.faceBlob) {
        document.getElementById("pay-prompt").textContent =
          "Face unlocked — snap a face before re-authorizing.";
        return;
      }
      resetPipelineVisual();
      setLivePill("running", "Standalone auth");
      document.getElementById("path-summary").textContent = "Live ECAPA authorize…";
      const fd = new FormData();
      fd.append("driver_id", document.getElementById("pay-driver").value || "driver1");
      fd.append("amount", String(amt));
      fd.append("beneficiary", ben);
      fd.append("action", document.getElementById("pay-action").value || "pay");
      fd.append("currency", document.getElementById("pay-currency").value || "INR");
      fd.append("beneficiary_known", "true");
      fd.append("audio", pay.wavBlob, "pay.wav");
      if (pay.unlock.face && pay.faceBlob) fd.append("face", pay.faceBlob, "face.jpg");
      if (pay.unlock.finger) {
        fd.append("finger", document.getElementById("pay-finger").value || "0.85");
      }
      fd.append("gps_lat", String(pay.gps.lat));
      fd.append("gps_lon", String(pay.gps.lon));
      fd.append("gps_accuracy_m", "25");
      const res = await adminFetch("/api/standalone/auth", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById("pay-prompt").textContent =
          "Auth failed: " + (data.detail || res.statusText);
        setLivePill("idle", "Idle");
        return;
      }
      if (data.dist_from_home_km != null) {
        document.getElementById("pay-dist").textContent =
          `zone ${data.in_trusted_zone ? "trusted" : "outside"} · dist_from_home_km=${Number(data.dist_from_home_km).toFixed(2)} (telemetry)`;
      }
      showResult(data);
      await animatePipeline(data.pipeline);
      highlightSourcesFromResult(data, {});
      loadAudit();
      loadStatus();
      applyEscalationUnlock(data);
    }

    async function initStandalonePay() {
      try {
        pay.cfg = await (await fetch("/api/standalone/config")).json();
      } catch (e) {
        return;
      }
      const orBadge = document.getElementById("pay-or-badge");
      const mapsBadge = document.getElementById("pay-maps-badge");
      if (pay.cfg.openrouter) {
        orBadge.textContent = "OpenRouter · on";
        orBadge.classList.add("on");
      } else {
        orBadge.textContent = "OpenRouter · missing key";
        orBadge.classList.add("warn");
      }
      if (pay.cfg.google_maps_api_key) {
        mapsBadge.textContent = "Maps · on";
        mapsBadge.classList.add("on");
        ensurePayMap().catch(() => {
          mapsBadge.textContent = "Maps · load error";
          mapsBadge.classList.add("warn");
        });
      } else {
        mapsBadge.textContent = "Maps · missing key";
        mapsBadge.classList.add("warn");
      }
      const sel = document.getElementById("pay-driver");
      const drivers = pay.cfg.drivers || [];
      sel.innerHTML = (drivers.length ? drivers : [{ driver_id: pay.cfg.default_driver || "driver1" }])
        .map(d => `<option value="${d.driver_id}">${d.driver_id}${d.home_set ? " · home" : ""}</option>`)
        .join("");
      if (pay.cfg.default_driver) sel.value = pay.cfg.default_driver;
      sel.addEventListener("change", () => resetPayUnlock());

      ["pay-amount", "pay-beneficiary"].forEach(id => {
        document.getElementById(id).addEventListener("input", updatePayReady);
      });
      document.getElementById("pay-rec").onclick = () => recordPayClip();
      document.getElementById("pay-intent-refresh").onclick = async () => {
        const transcript = document.getElementById("pay-transcript").textContent || "";
        const res = await adminFetch("/api/standalone/intent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            transcript,
            amount: Number(document.getElementById("pay-amount").value || 0),
            beneficiary: document.getElementById("pay-beneficiary").value || "",
            action: document.getElementById("pay-action").value || "pay",
            currency: document.getElementById("pay-currency").value || "INR",
          }),
        });
        const data = await res.json();
        await handleIntentResponse(data);
      };
      document.getElementById("pay-geo").onclick = () => {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(
          (pos) => setPayGps(pos.coords.latitude, pos.coords.longitude),
          (err) => { document.getElementById("pay-dist").textContent = err.message; },
          { enableHighAccuracy: true, timeout: 12000 }
        );
      };
      document.getElementById("pay-clear-gps").onclick = () => {
        pay.gps = { lat: null, lon: null };
        document.getElementById("pay-dist").textContent = "GPS cleared — pin required";
        if (pay.marker) { pay.marker.setMap(null); pay.marker = null; }
        updatePayReady();
      };
      document.getElementById("pay-cam-start").onclick = async () => {
        if (!pay.unlock.face) return;
        pay.camStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user" }, audio: false,
        });
        document.getElementById("pay-cam").srcObject = pay.camStream;
      };
      document.getElementById("pay-cam-snap").onclick = () => {
        if (!pay.unlock.face) return;
        const video = document.getElementById("pay-cam");
        const canvas = document.getElementById("pay-face-canvas");
        if (!video.videoWidth) return;
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        canvas.toBlob((blob) => {
          pay.faceBlob = blob;
          document.getElementById("pay-prompt").dataset.needFace = "0";
          document.getElementById("pay-prompt").textContent = "Face snap captured — authorize again.";
          updatePayReady();
        }, "image/jpeg", 0.92);
      };
      document.getElementById("pay-finger").oninput = (e) => {
        if (!pay.unlock.finger) {
          e.target.value = "0.85";
          return;
        }
        document.getElementById("pay-finger-val").textContent = e.target.value;
      };
      document.getElementById("pay-run").onclick = () => runStandaloneAuth();
      applyPayUnlockUI();
      updatePayReady();
    }
    """
