# Secure-boot + dm-verity rollout plan (TODO 16)

Application-level integrity is implemented today (`driveauth/integrity.py`,
`scripts/sign_manifest.py`). This document is the **OEM/BSP rollout plan** for
board-level verified boot — code in this repo cannot fuse chips or sign bootloaders.

## Phase 0 — Current (app manifest only)

- [x] Ed25519 signed store manifest at startup (`DRIVEAUTH_INTEGRITY_CHECK=1`)
- [x] Documented non-claim in `docs/secure-boot.md`

**Limitation:** root on the host can replace the verifier. Do not claim full
secure boot until Phases 1–3 are done on target hardware.

## Phase 1 — Boot chain (BSP / OEM)

| Step | Owner | Deliverable |
|------|-------|-------------|
| 1.1 | SoC vendor | Boot ROM verifies first-stage loader (eFuse keys) |
| 1.2 | BSP | Signed U-Boot / AB slots with rollback index |
| 1.3 | BSP | FIT image or signed kernel + initramfs |
| 1.4 | QA | JTAG/fuse policy doc; recovery USB image for bricked units |

**Exit gate:** device refuses unsigned bootloader; rollback counter tested.

## Phase 2 — Root filesystem integrity

| Step | Owner | Deliverable |
|------|-------|-------------|
| 2.1 | Yocto/image | dm-verity hash tree for `/` or `/usr` partition |
| 2.2 | Yocto/image | `/data` on separate writable partition (store + enroll) |
| 2.3 | Fleet ops | OTA updates sign new rootfs; A/B switch with health probe |
| 2.4 | QA | Tamper test: modified root block → boot failure or recovery |

**Exit gate:** `veritysetup status` OK; modified bit flips block read.

## Phase 3 — Application + secrets

| Step | Owner | Deliverable |
|------|-------|-------------|
| 3.1 | DriveAuth | Signed manifest covers models + `policy.yaml` (existing) |
| 3.2 | Fleet ops | Offline manifest signing key; CI publishes sig to OTA bundle |
| 3.3 | Fleet ops | `DRIVEAUTH_KEY_PROTECTOR=tpm` on units with TPM/ATECC |
| 3.4 | Fleet ops | Vault/AppRole per vehicle (`docs/vault-operations.md`) |

**Exit gate:** OTA cannot swap models without valid manifest; TPM unseal tested.

## Phase 4 — Operations

- Key ceremony for manifest signing (HSM or air-gapped host)
- Incident runbook: revoke compromised signing key, push new pubkey via OTA
- Compliance mapping: link to `docs/compliance-checklist.md`

## Verification checklist (before marketing claims)

- [ ] Bootloader signature verified on cold boot
- [ ] dm-verity active on system partition
- [ ] `/data` survives OTA without wiping enroll/templates
- [ ] App manifest fail-closed on tampered ONNX
- [ ] TPM seal/unseal for `.bio_key` on production units
