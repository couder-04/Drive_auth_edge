# Security assumptions

What DriveAuth Edge **assumes**, what it **enforces**, and what it **does not claim**.
Read this before treating benchmarks or demos as production biometric assurance.

Companion docs: [trust-risk-separation.md](../architecture/trust-risk-separation.md) ·
[integration.md](integration.md) · [review-fixes.md](review-fixes.md) ·
[phase6.md](../phases/phase6.md)

---

## 1. Threat model (in scope)

| Actor / scenario | Goal | DriveAuth response (intended) |
|------------------|------|-------------------------------|
| Unauthorized cabin user | Approve a payment as the enrolled driver | Voice → Face → Finger ladder must fail → `REJECT` (or guest `STEP_UP` for PIN) |
| Replay / presentation attack | Pass face or voice with screen / recording | QualityGate + Stage-2 face PAD + OOD flags degrade scores; fail-closed on weak probes |
| OOD / sensor spoof drift | Slowly poison enrollment baselines | OOD refresh gated on strong auth (`ProfileStore.can_refresh_ood`) |
| Risky but genuine txn | Abuse legitimate session (novel payee, remote GPS, high speed) | Risk ceiling / fraud ladder → hard `REJECT` or raised ladder rigor |
| Timing observer | Infer early-stop ACCEPT vs full ladder from latency | Optional wall-clock pad (`DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS`) |
| Missing / crashed sensor | Force ACCEPT via unavailable modality | Unavailable modality does not contribute; fail-closed when required probes fail |

Out of scope for this release (product / platform responsibility):

- Physical theft of the enrolled driver’s phone used as OTP second factor
- Compromise of the host OS, model store encryption keys, Vault token, or dashboard process
- Network MITM on Nova ↔ Edge IPC (assumes trusted in-vehicle channel)
- Certification exhaustiveness of every staged-escalation path (toggle parallel probes if required)

---

## 2. Architectural assumptions

These are **design invariants**, not optional heuristics.

1. **Trust ≠ Risk.** GPS, speed, amount, beneficiary novelty, and CAN behavior enter **Risk only**. They must never raise a biometric Trust score.
2. **Accept/Reject is ladder-driven.** Voice → Face → stage-3 decides identity acceptance. Stage-3 defaults to fingerprint (`finger_only`); policy may enable `finger_or_otp` / `otp_only` so Bluetooth OTP to the driver's registered paired phone is an alternate lane (OR, not AND). Policy applies irreversible hard gates (fraud lock, risk ceiling) and guest PIN handling — it does not invent a fourth biometric beyond that stage-3 OR.
3. **Fail closed.** Missing audio/face/finger when needed, missing OOD baselines for a scored modality, matcher crash/timeout, Bluetooth OTP undeliverable / MAC mismatch, and risk ≥ hard ceiling → deny / escalate, never silent ACCEPT.
4. **No silent mock fallback.** When `DRIVEAUTH_USE_MOCK` is off, unready voice/face raise unless `DRIVEAUTH_ALLOW_MOCK_FALLBACK=1` is set explicitly. Prefer `python scripts/bootstrap.py`.
5. **Dashboard admin auth.** Mutating HTTP routes require `DRIVEAUTH_DASHBOARD_API_KEY` (Bearer or X-API-Key). `DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1` is localhost-demo only.
6. **Deterministic policy.** Thresholds live in `policy.yaml` / `DRIVEAUTH_*`. Changing rules does not require retraining heads.
7. **Audit without biometrics.** `AuditLog` stores decision metadata and scores, not raw voice/face/finger templates.
8. **Payment OTP ≠ ladder OTP.** Cellular/HTTP `otp_mobile` (`OTPStepUp` + `HTTPProviderDelivery`) remains a payment step-up fallback. Identity-ladder Bluetooth OTP (`BluetoothOTPDelivery`) is a separate `OTPStepUp` instance with independent challenge state, enabled only when `LADDER_STAGE3_MODE` is `otp_only` or `finger_or_otp`.
---

## 2b. Mocked vs real (hardware surface)

| Component | Status | Notes |
|-----------|--------|-------|
| Voice / face matchers | Mock or ONNX | Unchanged default |
| Finger capture daemon (`hardware/finger_daemon.py`) | **Real protocol** | Unix `SCAN\\n` → 256×256 bytes; UART via `PyFingerprintAdapter` (optional extra) or `ManualFingerSensor` |
| Finger match / templates | Partial | `FingerMatcher` decrypts Fernet `fingers/*.enc`; optional `KeyProtector` (default `SoftwareKeyProtector` = Fernet key on disk). `TPMKeyProtector` seals that key when a TPM 2.0 + `tpm2-pytss` is present — **off by default; gap not closed without the chip** |
| `ManualScores(finger=…)` dashboard path | Mock stand-in | Still works; does not require the daemon |
| Payment `otp_mobile` HTTP OTP | Real HTTP client | Unchanged (`HTTPProviderDelivery`) |
| Ladder Bluetooth OTP (MAP) | Stubbed BlueZ path | Unit-tested with injected `map_send`; real MAP needs head-unit OBEX agent |
| Ladder Bluetooth OTP (BLE GATT) | **Reference impl** | Car: `hardware/ble_gatt_server.py` (BlueZ D-Bus peripheral); phone: `companion/ble_otp_pwa/` Web Bluetooth PWA. Fixed UUIDs in `docs/integration.md`. Unit-tested with mocked BlueZ; phone flow is manual-only. |
| Paired-MAC gate | **Real check** | Refuses delivery unless paired MAC matches `contacts/{id}.bt_mac` |
| IR / RGB / mic capture (`hardware/ir_capture.py` et al.) | **Real service API** | OpenCV / inject backends; unit-tested shapes (112² crop, 16 kHz mono) |
| IR liveness (`hardware/ir_liveness.py`) | Heuristic ensemble | Reflectance-only by default (`DRIVEAUTH_IR_LIVENESS_ENABLED`); optional Liveness v2 via `DRIVEAUTH_IR_LIVENESS_ENSEMBLE=1` (reflectance + blink/micro-motion + moiré). **Not** ISO/IEC 30107-3 certified; Stage-2 PAD logreg still separate |
| Hailo face (`hardware/hailo_face.py`) | Optional | `DRIVEAUTH_FACE_BACKEND=hailo` + `.hef`; fail-closed without device; IR liveness stays on CPU |
| Actuation (`hardware/actuation.py`) | **Real API** | Relay defaults open; closes only on fresh ACCEPT; optional `RPi.GPIO` |
| GPS/CAN ingest (`hardware/telematics.py`) | **Real API** | Sanitizes then calls `update_vehicle_context`; malformed frames skipped |
| CAN/GPS logger (`hardware/can_logger.py`) | **Harness** | Writes txn + behavioral CSVs matching synthetic schemas; needs a live bus / pilot fleet — does not invent real data |

### Phase A note — pluggable secrets (env default; Vault wired; HSM stub)

`driveauth/secrets.py` exposes a `SecretsProvider` protocol (`get(key) -> str | None`).
Default `EnvFileSecretsProvider` preserves today's `secrets.env` behaviour.
`VaultSecretsProvider` reads HashiCorp Vault KV v2 via a swappable HTTP client
(no secrets baked into the image). `HSMSecretsProvider` is an **interface stub** —
`get()` raises until a real PKCS#11 / vendor backend is injected.
**Not closed:** fleet secret ops (Vault policy, token rotation) and any claim of
HSM-backed secrets without the hardware. Process: [`key-provisioning.md`](key-provisioning.md).

### Phase B–I note — production hardening (code + process; hardware gaps remain)

| Phase | Landed | Still open without external work |
|-------|--------|----------------------------------|
| **B** Audit hash-chain + optional remote sink (`DRIVEAUTH_AUDIT_REMOTE_URL`) | Detects local rewrite when chain verified / remote enabled | Remote sink ops; owner who also controls the sink |
| **C** Actuation watchdog | Forces relay open on stale heartbeat | Real GPIO timing on vehicle HW |
| **D** Signed manifest integrity | App-level fail-closed check | Full SoC secure boot / dm-verity — [`secure-boot.md`](secure-boot.md) |
| **E** Consent + `purge_driver` | Enrollment gate + deletion API | **Legal** BIPA/GDPR-class sign-off — [`biometric-data-policy.md`](biometric-data-policy.md) |
| **F** Signed OTA + rollback | `OTAClient` + `build_update_package.py` | Fleet signing infra, staged rollout |
| **G** Fleet telemetry | Opt-in rates/sensors/firmware only | Pilot fleet endpoint + ops |
| **H** CI workflows | `.github/workflows/ci.yml` + HIL stub | Self-hosted runner for real BT/Hailo |
| **I** Score buckets in audit | Drift/fairness **data collection only** | Diverse field dataset + analysis — **does not** close skin-tone validation |

### Phase 7 note — secure-element key protection (optional, off by default)

`driveauth/key_protection.py` adds a `KeyProtector` layer around the Fernet
template key (`.bio_key`). Default `SoftwareKeyProtector` is identity
wrap/unwrap — **today's behaviour, zero change**. `TPMKeyProtector` (tpm2-pytss)
seals that key so the on-disk blob is unusable without the chip.
**Not solved:** deployments without a TPM/ATECC-class element still store a
usable Fernet key on disk; this is an upgrade path, not a closed TEE gap.

### Phase 10 note — real data collection harness (synthetic gap still open)

`can_logger.py` + `--real-data-dir` on the risk/behavioral trainers make real
logs drop-in usable. **Still open:** models remain trained only on synthetic
data until a pilot fleet produces logs and a bakeoff/train run reports
`n_real > 0`. See [`data-collection.md`](data-collection.md).

### Phase 8 note — Liveness v2 (heuristic ensemble, not certified PAD)

Liveness v2 is a stronger heuristic ensemble; still not independently
certified anti-spoofing. Certification requires third-party PAD testing
against ISO/IEC 30107-3, which is out of scope.

What landed: weighted combination of (a) existing IR reflectance, (b) short-burst
blink / micro-motion, (c) FFT moiré / screen-grid check. Default remains
reflectance-only so integrators see no behaviour change until they opt in.
**Not closed:** presentation-attack robustness claims; synthetic unit tests
only exercise each signal, not a PAD corpus.

### Phase 9 note — BLE GATT companion (reference, not a certified channel)

Shipped the real GATT peripheral + Web Bluetooth PWA so the documented UUID
contract is executable end-to-end. **Not closed:** production assurance still
depends on BlueZ LE stability on the head unit, HTTPS hosting for the PWA,
and the paired-MAC gate — Web Bluetooth itself is not a security boundary.

### Phase 0 note — `dist_from_home` retired as a risk feature

`RiskModel` no longer includes a scaled `dist_from_home` feature
(`clip01(dist_from_home_km / 50)` with a `far_from_home` reason at 0.6 ≈ 30 km).
That threshold sat far above the synthetic trainer’s 3–15 km trusted-zone
radii, so ordinary commute distances looked anomalous, and the signal
duplicated `out_of_zone` (same Haversine in `geo.py`). **Closed for the
model/feature schema:** `out_of_zone` is the sole geo-anomaly input.
`RiskContext.dist_from_home_km` and CSV `dist_from_home_km` remain as raw
telemetry. Do not re-add a `/50`-scaled feature without re-aligning the
reason threshold to the training zone distribution.

## 3. Trust boundary

```
┌─────────────────────────────────────────────────────────┐
│ Trusted: DriveAuth process + encrypted profile store    │
│          (enroll templates, OOD stats, fraud state)     │
├─────────────────────────────────────────────────────────┤
│ Assumed honest inputs when live:                        │
│   mic · camera · finger SDK · GPS/CAN telematics        │
│ Stand-ins (`ManualScores`, dashboard sliders) are for   │
│ demo/integration only — not a security control.         │
├─────────────────────────────────────────────────────────┤
│ Untrusted: cabin occupants, utterances, payees,         │
│            replay media, adversarial GPS claims         │
└─────────────────────────────────────────────────────────┘
```

**Assumption:** the vehicle integrator wires real sensors into the same
`ModalityResult(score∈[0,1])` / `update_vehicle_context` / `update_behavioral`
APIs. Until then, demos using mocks or manual scores **do not** prove field FAR/FRR.

---

## 4. Assumed environment

| Assumption | Implication if violated |
|------------|-------------------------|
| Single enrolled primary driver per store profile | Multi-driver households need separate profiles / guest PIN |
| Edge host is not attacker-controlled | Model swap / threshold edit defeats policy |
| Enrollment samples are from the legitimate driver | Compromised enroll → persistent false ACCEPT |
| GPS/CAN come from vehicle telematics, not cabin UI alone | Spoofable dashboard GPS skews Risk only (Trust still biometric) |
| Nova calls `update_vehicle_context` before payment auth | Stale speed/GPS understates Risk |
| Python 3.11+ runtime with intended `DRIVEAUTH_*` env | Wrong store / mock flags silently weaken demos |

---

## 5. Controls that exist today

| Control | Where | Default / note |
|---------|-------|----------------|
| Biometric ladder + per-modality bars | `escalation.py` · `policy.yaml` | voice ≥ 0.72 · face ≥ 0.70 · finger ≥ 0.70 |
| Fraud ladder rigor / lock | `fraud_state.py` | Bootstrap amount cap; lock → REJECT |
| Risk hard ceiling | `policy_engine.py` | `DRIVEAUTH_RISK_REJECT` (default 0.80) |
| Face PAD + calibrators | Stage-2 ONNX heads | Bypass with `DRIVEAUTH_STAGE2_RAW=1` (eval only). **Per-driver** under `faces/{id}/` and `voices/{id}/` (legacy store-root heads still load with a WARNING). Retraining one driver cannot overwrite another |
| Face PAD effectiveness | `face_pad.json` `loo_auc` | If LOO AUC ≤ 0.55 (chance), `FaceMatcher` **disables** the PAD gate at load and logs an error — onnx may still be on disk but is not treated as protection |
| OOD detector | `ood_detector.py` | Missing baseline → OOD / fail closed |
| OOD refresh gate | `profile_store.can_refresh_ood` | Requires independently strong auth |
| Decision cache limits | `api.require_auth` | No reuse of REJECT/STEP_UP; tier/fraud/profile epoch checked |
| Timing pad | `DecisionEngine._pad_timing` | **Off** unless `DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS` > 0 |
| Atomic profile writes | `profile_store.py` | `.tmp` + replace; schema migration |
| Pluggable secrets | `secrets.py` | Default env file; optional Vault KV v2; HSM stub only |
| Audit hash-chain | `audit_log.py` | `prev_hash`/`entry_hash`; optional remote sink |
| Actuation watchdog | `hardware/actuation.py` | Force-open on stale heartbeat |
| App integrity check | `integrity.py` | Opt-in via `DRIVEAUTH_INTEGRITY_CHECK=1` |
| Consent + purge | `consent.py` · `purge.py` | Required before enroll; deletion API |
| Fleet telemetry | `hardware/fleet_telemetry.py` | Opt-in; no biometric fields |

Evidence: `tests/test_security_sprint1.py`, `tests/test_production.py`,
`tests/test_phase5_failure_modes.py`, `tests/test_secrets.py`,
`tests/test_hardening.py`, Sprint 6 ablations in `phases/phase6.md`.

---

## 6. Explicit non-claims (honesty bar)

Do **not** market or paper these as proven:

| Claim to avoid | Reality |
|----------------|---------|
| “Production FAR/FRR certified” | Current bio numbers are small Phase-3 / Stage-2 eval sets; face EER/ROC still weak vs voice |
| “Behavioral biometrics production-ready” | Bake-off winner trained on **synth CAN**; re-bake required on recorder dumps |
| “Fingerprint verification shipping” | Daemon + UART adapter land in Phase 1; production claims still need vendor SDK captures + FAR/FRR on-device |
| “Deepfake / ASVspoof complete” | Voice anti-spoof is quality + calibrator depth, not a full countermeasure suite |
| “PAD stops all replays” | Hand-crafted PAD features + optional IR reflectance / Liveness v2 heuristic ensemble; APCER reported in Phase 6 — **not** ISO/IEC 30107-3 certification |
| “PAD works without usable crops” | Haar-miss center-crop fallbacks (esp. `attack_side`) can collapse PAD LOO to ~0.50. Train with `--exclude-fallback-crops`. Driver7 after exclusion: LOO ≈ **0.81** (enabled). If LOO ≤ 0.55, gate stays **disabled** — do not market disabled PAD as protection |
| “Constant-time by default” | Timing pad is opt-in; default `constant_time_ms: 0` |
| “OTP comparison proves superiority” | `otp_only` FAR=0 in benches **assumes** OTP channel security; ladder BT OTP additionally assumes paired-MAC binding + MAP/BLE integrity |
| “Hailo face certified” | `HailoFaceMatcher` is a swappable backend; latency/accuracy claims require on-device HEF benchmarks |
| Apply `phase2b_suggested.env` blindly | **Cuts ladder voice 0.72→0.58 and face 0.70→0.36** so weak calibrated scores can ACCEPT — does not raise match quality. Dashboard, API (`DriveAuth.load`), and `driveauth.security` emit a loud WARNING (stock vs deployed + delta + reason). Do not leave sourced in production shells. Demo mode is for UX demos only |

### Demo vs production thresholds

| Bar | Stock (`policy.yaml`) | Demo (`phase2b_suggested.env`) |
|-----|----------------------|--------------------------------|
| Ladder voice / face / finger | 0.72 / 0.70 / 0.70 | 0.58 / 0.36 / 0.70 |
| Trust micro / std / high / reject | 0.70 / 0.78 / 0.85 / 0.48 | 0.554 / 0.584 / 0.614 / 0.419 |

Production should keep stock bars unless re-calibrated on fleet data with documented FAR/FRR. Lowering bars never substitutes for better enrollment or models.

---

## 7. Dataset & evaluation assumptions

- **Genuine vs attack labels** in `data/driver1/` are correct for the enrolled identity.
- **OOD** voice (TTS) and face (other-id) are reasonable negatives for Stage-1 reject rates — not a full impostor population.
- **Risk AUC ≈ 0.9955** is on the 50k synthetic/synthetic-labelled txn split used for training — not live card fraud.
- **Sprint 6 system FAR/FRR** uses ladder bars and, for finger, proxy scores when HW is absent (`staged_full_proxy`).
- Shipping bars may yield FRR=1 on current eval sets by design (security over UX); see early-stop vs security-floor ablation.

---

## 8. Residual risks & open product decisions

From [review-fixes.md](review-fixes.md) and roadmap deferred items:

1. **Per-driver Stage-2 bio heads (shipped)** — `faces/{id}/face_pad.onnx` (+ calibrator) and `voices/{id}/voice_calibrator.onnx`. Legacy store-root heads still load with a WARNING; migrate with `scripts/migrate_stage2_per_driver.py` then retrain per driver. Migrated-only copies report `mode=per_driver_migrated` / `needs_retrain` until independent fit. See [`stage2-per-driver.md`](stage2-per-driver.md).
2. **Fairness / quality gates** — brightness and blur thresholds unvalidated across skin tones and cabin lighting. Phase I only adds bucketed score logging so a later analysis *can* detect correlated failures; **it does not close this gap** until a diverse field dataset exists and is reviewed.
3. **Bootstrap duration** — `BOOTSTRAP_MIN_TXNS` / days are defaults, not fleet-tuned.
4. **Certification path growth** — staged probes widen the state space; set `DRIVEAUTH_ESCALATION_ENABLED=0` for static parallel probes if required.
5. **Nova GPS wiring** — until live, Risk underestimates location/speed anomalies.
6. **Store encryption / secure element** — default remains Fernet key on disk (`SoftwareKeyProtector`). Optional `TPMKeyProtector` is an upgrade path; the at-rest gap stays open until hardware-backed protection is enabled on a real SE. Product API secrets can move to Vault via `SecretsProvider`; `HSMSecretsProvider` remains a stub without hardware (see [`key-provisioning.md`](key-provisioning.md)).
7. **Secure boot** — application manifest check is opt-in; board verified-boot / dm-verity remain OEM integration ([`secure-boot.md`](secure-boot.md)).
8. **Biometric legal compliance** — consent records are a code gate, not a BIPA/GDPR certification ([`biometric-data-policy.md`](biometric-data-policy.md)).
9. **Driver7 voice separation** — calibrated genuine mean ~0.55 still sits below stock ladder 0.72 (and near demo 0.58). Needs more/cleaner enrollment WAVs, not lower thresholds.

---

## 9. Checklist for integrators

Before calling a deployment “secure”:

- [ ] Real voice + own-face enrolled; re-run `calibrate_bio_thresholds.py` and keep bars conservative
- [ ] Finger SDK emitting live `ModalityResult` (no dashboard stand-ins in prod)
- [ ] Real CAN windows → re-run `train_behavioral_bakeoff.py` → re-enroll behavioral
- [ ] Nova telematics calls `update_vehicle_context` every auth
- [ ] Enable timing pad if network/IPC observers are in scope
- [ ] Confirm `DRIVEAUTH_USE_MOCK=0` and Stage-2 heads loaded (PAD/calibrators on)
- [ ] Provision secrets per [`key-provisioning.md`](key-provisioning.md) (on-device `.bio_key`; no secrets in image)
- [ ] Run `pytest` + `scripts/phase6_benchmark.py` on the target store after any threshold change

---

## 10. Posts / narrative framing (Phase 7)

Ready-to-publish drafts: [`public-posts.md`](public-posts.md) (LinkedIn + Medium/Substack).

When writing public posts or papers, lead with:

1. **Problem** — cabin MFA and OTP are high-friction and weak against present attackers.
2. **Separation** — Trust / Risk / Confidence + deterministic policy (auditability).
3. **Ladder** — early-stop UX with an explicit security floor / hard Risk gates.
4. **Honesty** — Section 6 non-claims; HW-gated finger/CAN; synth limits.
5. **Evidence** — link Phase 6 table, security tests, this document.

Venue note (roadmap): CCS/NDSS-style framing only if the contribution leads with timing/OOD-drift/security-floor analysis; IV/ITSC fit the systems + automotive story better.
