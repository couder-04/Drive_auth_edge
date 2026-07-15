# DriveAuth Edge — demo video (Phase 8)

**Length:** 5–8 minutes  
**Aspect:** 16:9 · 1080p  
**Primary use:** IV submission supplementary / README / LinkedIn  
**Companion GIF:** [`docs/demo.gif`](../demo.gif) (short loop until this cut ships)

**Goal:** Explain the cabin MFA problem, show Trust/Risk separation + ladder live, flash security honesty, close with Thor latency and repo link.

---

## Shot list (timeline)

| # | Time | Visual | Audio (VO) |
|---|------|--------|------------|
| 1 | 0:00–0:40 | Title card → cabin / phone OTP stock or B-roll → crossed-out OTP | “You’re driving. OTP is the wrong MFA.” Problem: hands, eyes, tunnels, passenger attackers. |
| 2 | 0:40–1:30 | Architecture animation: three score boxes → policy → ACCEPT/STEP_UP/REJECT | Trust = who. Risk = how unusual. Confidence = can we trust this capture. Never fuse GPS into Trust. |
| 3 | 1:30–2:00 | Ladder diagram Voice→Face→Finger with early-stop branch | Soft voice path for UX; security floor is still available as full AND MFA. |
| 4 | 2:00–4:00 | **Live dashboard** `/manual` or `/standalone` | Walk three presets: micro ACCEPT · escalate to face · REJECT / STEP_UP. Call out staircase UI + audit. |
| 5 | 4:00–4:45 | Optional attack vignettes (dashboard sliders: low voice, screen-like face) | Replay / weak capture → escalate or reject. Point at PAD / confidence without overclaiming. |
| 6 | 4:45–5:30 | Metrics slide: Phase 6 table + Thor p95 7.7 ms | Edge latency on NVIDIA Thor; Risk AUC; early-stop ablation one sentence. |
| 7 | 5:30–6:15 | Honesty slide (non-claims) | Finger HW still gated. Synth CAN not fleet-ready. Shipping bars prioritize security. Link security-assumptions. |
| 8 | 6:15–7:00 | Repo + QR / URL · optional Thor board photo | github.com/couder-04/Drive_auth_edge · “open policy, open eval.” |
| 9 | 7:00–end | End card | Title + contact / IV 2027 preprint note when available. |

Trim toward 5:00 by cutting #5 and shortening #6 if needed; extend to 8:00 with standalone mic→STT→pay flow and Thor boot clip.

---

## VO script (tight cut ≈6:00)

**[0:00]** In-car payments are here — charging, tolls, fleet payouts — but phone OTP was never designed for a moving cabin. You’re eyes-forward. Hands busy. And the attacker might be sitting next to you.

**[0:40]** DriveAuth Edge is an offline biometric authorization stack for vehicles. Three scores, kept apart on purpose. Trust asks: is this the enrolled driver — biometrics only. Risk asks: is this transaction unusual — amount, GPS, speed, behaviour. Confidence asks: should we believe our own scores on this capture?

**[1:20]** A deterministic policy — YAML thresholds, not another black-box fusion head — maps those scores to Accept, Step-up, or Reject. Auditors can read and change the rules without retraining models.

**[1:45]** Biometrics escalate Voice, then Face, then Finger. Strong voice can early-stop for UX. Weak scores climb the ladder. Hard risk ceilings and fraud locks still win.

**[2:10]** Here’s the live dashboard. Micro payment, enrolled voice — Accept. Lower voice — we escalate to face. Push biometrics and risk the wrong way — Reject or Step-up. The staircase and audit log show every probe.

**[4:00]** We measured Sprint-six benchmarks: voice and face EER, PAD attack reject, risk ROC near 0.996 on our txn set, and on NVIDIA Thor, Phase-two-A micro latency under ten milliseconds p95.

**[4:50]** What we don’t claim yet: production fingerprint FAR/FRR without the sensor, behavioural biometrics on synthetic CAN as fleet-ready, or certified presentation-attack detection. Those limits are written down in our security assumptions.

**[5:40]** DriveAuth Edge is open source — architecture, policy, ONNX heads, and tests including timing pads and OOD-drift gates. Link in the description. Thanks for watching.

---

## Capture checklist

### Software (required)
- [ ] `driveauth-dashboard` on `:8765` with enrolled `driver1` (live, `DRIVEAUTH_USE_MOCK=0`)
- [ ] Screen record 1080p (QuickTime / OBS): `/manual` presets micro · low voice · reject
- [ ] Optional: `/standalone` one successful pay with Maps pin (if keys present)
- [ ] Export stills: architecture mermaid → PNG; Phase 6 tables → clean slide

### Hardware (optional but strong for IV)
- [ ] Thor board clip: `nvidia-smi` + dashboard or CLI demo
- [ ] Overlay p95 from `phases/phase2a-thor.txt`

### Edit
- [ ] Burn-in captions for ACCEPT / STEP_UP / REJECT
- [ ] Lower-third: “Trust ≠ Risk” when architecture appears
- [ ] End card URL + `docs/security-assumptions.md` mention
- [ ] No music that fights VO; keep cabin ambience quiet

### Publish
- [ ] Upload YouTube (unlisted OK until paper)  
- [ ] Paste URL into [`phases/phase8.md`](../../phases/phase8.md) submission log  
- [ ] Link from README Demo section  
- [ ] 15–30 s cutdown for LinkedIn (reuse Phase 7 posts)

---

## Suggested filenames

```text
docs/paper/DriveAuth_Edge_demo_full.mp4      # 5–8 min (git-lfs or external host)
docs/paper/DriveAuth_Edge_demo_short.mp4     # ≤30 s social
docs/demo.gif                                # keep regenerating via scripts/capture_dashboard_demo_gif.py
```

Do **not** commit multi-hundred-MB MP4s without LFS / release assets — prefer YouTube + README link.

---

## One-session capture plan (≈90 min)

1. Boot store + dashboard; verify three presets.  
2. OBS: 3 takes of each preset (pick cleanest).  
3. Export architecture + metrics slides (Keynote/PPT or HTML).  
4. Record VO in one pass with script on second screen.  
5. Rough cut same day; polish thumbnails later.  
