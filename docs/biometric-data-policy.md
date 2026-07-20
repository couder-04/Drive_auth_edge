# Biometric data policy (Phase E)

## What we collect

Under a normal enrollment, DriveAuth Edge stores:

| Artifact | Location | Purpose |
|----------|----------|---------|
| Voice embedding | `voices/{id}.enc` (Fernet) | Speaker match |
| Face embedding | `faces/{id}.enc` (Fernet) | Face match |
| Optional finger template | `fingers/{id}.enc` | Stage-3 finger |
| OOD baselines | `ood_stats/*_{id}.npz` | Drift / OOD gates |
| Consent record | `consent/{id}.json` | Explicit enrollment gate |
| Profile stats | `profiles/{id}.json` | Risk maturity / home — **not** biometrics |

Raw enroll WAVs/JPGs under `data/{id}/` are capture inputs; production
deployments should delete or minimize them after template creation.

## Consent gate

`enroll_driver(..., require_consent=True)` (default) refuses to run without
`driveauth.consent.record_consent(...)`. The dashboard `/api/register/complete`
endpoint requires `consent: true` in the JSON body and writes the consent
record before enrollment.

## Retention defaults

| Data | Default retention | Notes |
|------|-------------------|-------|
| Encrypted templates + OOD | Until `purge_driver` or vehicle decommission | No auto-expiry in code |
| Consent record | Until purge | Kept with templates |
| Audit log | Append-only; **not** rewritten on purge | Scores/metadata only — no templates |
| Capture samples (`data/`) | Operator-controlled | `purge_driver(..., remove_sample_files=True)` optional |

## Deletion guarantee

`driveauth.purge.purge_driver(store, driver_id)` removes templates, OOD
npz files, profile, contacts, and consent. Tests assert
`biometric_residue(...) == []` after purge.

Audit history is intentionally preserved for integrity (Phase B hash chain).
Those rows contain decision metadata and bucketed scores, not recoverable
embeddings.

## Legal sign-off required

**This document and the consent module are not legal advice and do not certify
compliance.** Before enrolling non-test drivers, obtain counsel review against
applicable biometric statutes (e.g. BIPA, GDPR/UK GDPR, state privacy laws).
Code can enforce an explicit consent record; it cannot certify that the notice,
purpose limitation, retention, or DPIA obligations are met for your deployment.
