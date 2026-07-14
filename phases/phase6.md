# Phase 6 — Benchmarking (Sprint 6)

**Status:** ✅ Done (2026-07-15)
**Exit:** Sprint 6 table populated + ablations filled.

Artifacts: [`phase6_sprint6.json`](phase6_sprint6.json) · `python scripts/phase6_benchmark.py`

## Sprint 6 summary table

| Category | Metric | Value | Source / notes |
|---|---|---|---|
| Biometrics · voice | EER | 0.2154 | thr=0.58 FAR=0.2308 FRR=0.2 |
| Biometrics · voice | ROC-AUC | 0.8866 | threshold sweep on Stage-2 scores |
| Biometrics · face | EER | 0.3989 | thr=0.501 FAR=0.3478 FRR=0.45 |
| Biometrics · face | ROC-AUC | 0.6522 | PAD-gated scores (reject→0) |
| PAD | APCER / BPCER | 0.3478 / 0.0 | `face_pad.json` thr=0.47 |
| PAD | Attack reject (ops) | 0.6522 | matcher path on attack set |
| Risk | Val ROC-AUC | 0.9955 | LightGBM→ONNX · 50k txns |
| Risk | Acc / P / R / F1 | 0.9669 / 0.9324 / 0.9507 / 0.9415 | @0.5 on stratified val |
| Risk | Brier | 0.026071 | calibration sidecar |
| Intent | Parse / slot acc | 0.9 / 1.0 | fixed 10-utt harness |
| Latency · Mac 2a | micro p95 | 37.6 ms | `phase2a-mac.txt` |
| Latency · Thor 2a | micro / high p95 | 7.7 / 9.2 ms | `phase2a-thor.txt` · CUDA |
| Behavioral (synth) | Winner AUC | 1.0 | lstm — Trained on current behavioral windows (likely synth). Re-bak |
| OOD Stage 1 | Voice / face reject | 1.0 / 1.0 | `phase2a_ood_eval.json` |

## System comparison (vs OTP / static MFA / single-modality / staged)

Bars: voice≥0.72 · face≥0.7 · finger≥0.7 (proxy).

| System | FAR | FRR | Genuine accept | Notes |
|---|---|---|---|---|
| `otp_only` | 0.0 | 1.0 | 0.0 | Always STEP_UP; bio never Accepts. FAR below assumes OTP channel secure. |
| `voice_only` | 0.0 | 1.0 | 0.0 | Accept iff voice ≥ 0.72 |
| `face_only` | 0.0 | 1.0 | 0.0 | Accept iff face ≥ 0.7 |
| `finger_only_proxy` | 0.0 | 0.0 | 1.0 | HW-gated — FingerNet not enrolled; genuine=0.90 / attack=0.20 stand-in |
| `static_mfa_voice_and_face` | 0.0 | 1.0 | 0.0 | Accept iff voice ≥ 0.72 AND face ≥ 0.7 |
| `staged_voice_face` | 0.0 | 1.0 | 0.0 | Voice→Face ladder; no finger (current shipping without ManualScores finger) |
| `staged_full_proxy` | 0.0 | 0.0 | 1.0 | Finger scores are ManualScores-style proxies until HW |

### At eval-set FAR≈0 voice bar (voice≥0.63 · face≥0.7 · **not shipped**)

| System | FAR | FRR | Genuine accept |
|---|---|---|---|
| `voice_only` | 0.0 | 0.7 | 0.3 |
| `static_mfa_voice_and_face` | 0.0 | 1.0 | 0.0 |
| `staged_voice_face` | 0.0 | 0.7 | 0.3 |
| `staged_full_proxy` | 0.0 | 0.0 | 1.0 |

## Ablations

### A1 — Early-stop vs security floor

| Setting | Variant | FAR | FRR | Early-stop voice rate |
|---|---|---|---|---|
| Shipping bars | Staged early-stop | 0.0 | 1.0 | 0.0 |
| Shipping bars | Force full MFA (AND) | 0.0 | 1.0 | 0 |
| Balanced voice bar (0.525) | Staged early-stop | 0.1111 | 0.05 | 0.95 |
| Balanced voice bar | Force full MFA (AND) | 0.0 | 1.0 | 0 |
| Balanced | Δ (early − full) | 0.1111 | -0.95 | — |

_Early-stop improves UX (lower FRR) when voice clears the bar; security floor = static AND requires both modalities. Shipping bars yield FAR=0/FRR=1 for both — use balanced-bar row._

### A2 — Ladder voice-bar sweep (face bar fixed)

| Voice bar | FAR | FRR | Early-stop voice rate |
|---|---|---|---|
| 0.500 | 0.1111 | 0.0 | 1.0 |
| 0.525 | 0.1111 | 0.05 | 0.95 |
| 0.550 | 0.1111 | 0.05 | 0.95 |
| 0.575 | 0.0833 | 0.15 | 0.85 |
| 0.600 | 0.0556 | 0.3 | 0.7 |
| 0.625 | 0.0278 | 0.6 | 0.4 |
| 0.650 | 0.0 | 0.9 | 0.1 |
| 0.675 | 0.0 | 1.0 | 0.0 |
| 0.700 | 0.0 | 1.0 | 0.0 |
| 0.725 | 0.0 | 1.0 | 0.0 |
| 0.750 | 0.0 | 1.0 | 0.0 |
| 0.775 | 0.0 | 1.0 | 0.0 |
| 0.800 | 0.0 | 1.0 | 0.0 |
| 0.825 | 0.0 | 1.0 | 0.0 |
| 0.850 | 0.0 | 1.0 | 0.0 |

### A3 — Stage-2 heads (PAD+calibrators) vs raw 2a

| | Voice EER | Face EER | Face attack mean | PAD attack reject |
|---|---|---|---|---|
| Stage 2 | 0.2154 | 0.3989 | 0.1763 | 0.6522 |
| Raw 2a | 0.2154 | 0.3957 | 0.4975 | 0 (no PAD) |

## Caveats (paper-facing)

- Face genuine scores sit near ~0.50 after calibration — ladder face bar 0.70 yields high FRR without finger; do **not** ship `phase2b_suggested.env` yet.
- Finger metrics use ManualScores proxies until FingerNet + sensor HW.
- Behavioral bake-off AUC is on **synth CAN** — re-bake on recorder dumps before citing as production FAR/FRR.
- Risk head trained on synthetic 50k txns; retrain at ~5k real labels.
- OTP-only FAR=0 assumes a secure cellular OTP channel (not measured here).

## Re-run

```bash
python scripts/phase6_benchmark.py
python scripts/phase6_benchmark.py --offline   # tables from cached JSON only
```
