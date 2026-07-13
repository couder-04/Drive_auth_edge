# Architecture review fixes (v0.2.0)

This release closes the issues raised in the transaction-architecture review.
Each fix is summarised below with the module that owns it.

## 1. Real transaction data now reaches the gate (critical)

Previously both gate layers called `authenticate()` without `amount` /
`beneficiary` / `action`, so `classify_tier` saw `amount=0.0` +
`beneficiary_known=False` and routed **every** payment into `high_value`, and
the risk model's `amount_z` was a constant.

- `driveauth/intent.py` — a fast, deterministic parser extracts
  `(amount, beneficiary, action)` from the utterance at the STT layer. Unknown
  parses fail safe toward `high_value` (more scrutiny), never less.
- `api.intercept()` now parses intent and passes it to `authenticate()`.
- `api.require_auth()` now accepts `amount` / `beneficiary` / `action` so the
  LLM-layer re-gate scores the real transaction (feed it the Gemma parse in
  Nova).
- `DriveAuthResult.amount` carries the scored amount through for audit + profile.

## 2. Staged, risk-driven escalation (was: always-parallel)

- `driveauth/escalation.py` — `EscalationPolicy` builds a per-call probe plan
  (cheapest-friction-first: voice → face → finger) and a `should_stop` rule.
- `DecisionEngine.authenticate()` computes risk first (free), then probes
  modalities one at a time, stopping as soon as the tier bar is met.
- **Security floor:** `should_stop` never stops below the fraud ladder's
  `min_modalities`, and never at all when the plan mandates the full set —
  so single-modality accept is a deliberate, tier-gated decision, not an
  accident of parallelism. Toggle with `DRIVEAUTH_ESCALATION_ENABLED`.

## 3. Timing side-channel mitigation

- `DecisionEngine._pad_timing()` pads total wall-clock to a fixed quantum
  (`DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS`, default off) so "fast single-probe
  accept" vs "slow full escalation" isn't externally observable.

## 4. Second-layer gate no longer re-probes redundantly

- `api.require_auth(..., allow_cached=True)` reuses a fresh STT-layer **accept**
  within `DRIVEAUTH_DECISION_CACHE_TTL_S` — unless the parsed transaction is a
  higher tier than the cached one, in which case it always re-probes. Cached
  step-up/reject are never reused (the step-up flow must actually run).

## 5. Shared IR/DMS camera frame suitability

- `matchers/face.py` now detects and crops an adequately-large frontal face
  before embedding, instead of resizing the whole frame. A DMS-style wide gaze
  frame with a small off-centre face reports `confident=False` (escalation moves
  on) rather than silently producing a weak embedding. Threshold:
  `DRIVEAUTH_FACE_MIN_FRAC`.

## 6. Enrollment / bootstrap / OOD-drift

- `driveauth/profile_store.py` — one `DriverProfile` unifies "profile maturity":
  a driver is mature only with **both** enough transactions **and** recent,
  non-stale history, so a returning-after-a-gap driver or a used car with a new
  owner is treated as unknown, not trusted-on-stale-history.
- New `FraudState.BOOTSTRAP` (below `NORMAL`) overlays extra rigor + an amount
  cap (`DRIVEAUTH_BOOTSTRAP_AMOUNT_CAP`) for immature profiles.
  `FraudStateMachine.effective_state()` ensures suspicion always wins over mere
  novelty (a flagged new driver is `HEIGHTENED`, not downgraded to bootstrap).
- OOD-baseline refresh is gated behind an independently-strong auth
  (`ProfileStore.can_refresh_ood`), closing the same slow-drift surface the
  template-topup guard already closed.

## 7. Operational

- `ProfileStore` writes atomically (`.tmp` + `replace`) and forward-migrates
  older records (`_migrate`), so a rolled-back binary or partial write never
  leaves a half-written schema. Schema version is tracked
  (`PROFILE_SCHEMA_VERSION`).

## Not fully closed here (documented, needs product decision)

- Differential quality-gate failure rates across skin tones / lighting — the
  brightness/sharpness thresholds should be validated on representative data
  rather than assumed neutral. No code can settle this; it needs a test set.
- Bootstrap duration (`BOOTSTRAP_MIN_TXNS` / `BOOTSTRAP_MIN_DAYS`) and the
  constant-time quantum are defaults, not tuned values.
- Certification-path growth from dynamic sensor invocation is inherent to
  staged escalation; `DRIVEAUTH_ESCALATION_ENABLED=0` restores the fully-static
  parallel path if exhaustive-path certification is required.
