# Compliance checklist (BIPA / GDPR-class)

This is an **engineering readiness checklist**, not legal advice. Obtain counsel
sign-off before collecting biometrics from non-test drivers.

## Technical controls (implemented)

- [x] Explicit consent gate on enrollment (`driveauth/consent.py`, `/register` requires `consent: true`)
- [x] Biometric data policy draft (`docs/biometric-data-policy.md`)
- [x] Per-driver purge API (`driveauth/purge.py`, `POST /api/register/purge`)
- [x] Encrypted templates at rest (Fernet; optional `DRIVEAUTH_KEY_PROTECTOR=tpm`)
- [x] Audit hash chain without raw biometrics (`driveauth/audit_log.py`)
- [x] Fleet telemetry schema forbids biometric fields (`hardware/fleet_telemetry.py`)

## Process / legal (requires counsel)

- [ ] Privacy notice displayed before first capture (jurisdiction-specific text)
- [ ] Data Processing Agreement with fleet operator / OEM
- [ ] Retention schedule signed off (align with `docs/biometric-data-policy.md`)
- [ ] Cross-border transfer assessment (if templates leave vehicle region)
- [ ] Incident response runbook for template breach
- [ ] DPIA / BIPA written consent where applicable

## Sign-off record (fill when complete)

| Item | Owner | Date | Reference |
|------|-------|------|-----------|
| Privacy counsel review | | | |
| Fleet operator DPA | | | |
| Retention schedule | | | |
