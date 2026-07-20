# Secure boot & application integrity (Phase D)

## What this repo does

At process start, when ``DRIVEAUTH_INTEGRITY_CHECK=1``,
``DriveAuth.load`` calls ``driveauth.integrity.verify_store_integrity``:

1. Load ``integrity_manifest.json`` + ``integrity_manifest.sig`` from the store
2. Verify the Ed25519 signature with ``DRIVEAUTH_INTEGRITY_PUBKEY``
   (default: ``{store}/integrity_ed25519.pub``)
3. Re-hash every listed file (models + ``policy.yaml``) and **refuse to start**
   on any mismatch (fail closed)

Produce the manifest with:

```bash
python scripts/sign_manifest.py \
  --store ./driveauth_store_phase2a \
  --policy driveauth/policy.yaml \
  --write-pubkey
```

Keep the **private** signing key offline (build/signing host only). Vehicles
carry the **public** key + signed manifest.

## What this is not

This phase is an **application-level** integrity check. It does **not**
implement a board secure-boot chain. Full secure boot on the target SoC is a
board-level integration task outside this repository's scope.

A production vehicle stack still needs, at minimum:

| Layer | Typical control | Owner |
|-------|-----------------|-------|
| ROM / fuse | Immutable boot ROM verifies first-stage bootloader | SoC vendor / OEM |
| Bootloader | Verified U-Boot / AB boot with signed FIT/Image | Board BSP |
| Kernel / rootfs | dm-verity (or equivalent) over system partition | Yocto / device image |
| App + models | This repo's signed manifest (above) | DriveAuth Edge |
| Secrets | On-device key provisioning — [`key-provisioning.md`](key-provisioning.md) | Fleet ops |

Without verified bootloader + dm-verity (or equivalent), an attacker with root
on the host can replace the verifier itself. The application check raises the
bar against casual model/policy swap; it does **not** close a compromised-OS
threat. Say so when writing security claims — see
[`security-assumptions.md`](security-assumptions.md).
