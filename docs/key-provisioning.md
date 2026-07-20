# Per-vehicle key provisioning

How cryptographic material for DriveAuth Edge is created, stored, and rotated
**on the vehicle**, without ever embedding secrets in a build server artifact or
a shared OS image.

Companion: [`driveauth/secrets.py`](../driveauth/secrets.py) ·
[`driveauth/key_protection.py`](../driveauth/key_protection.py) ·
[`docs/security-assumptions.md`](security-assumptions.md)

---

## What this document covers

| Material | Purpose | Where it lives |
|----------|---------|----------------|
| Fernet template key (`.bio_key`) | Encrypt voice/face/finger embeddings at rest | Per-vehicle store dir; optionally TPM-sealed |
| Product API secrets (`OPENROUTER_*`, Maps, Vault token) | Standalone / fleet integrations | `SecretsProvider` (env file, Vault, or future HSM) |
| Manifest signing key (Phase D) | Integrity of `policy.yaml` + models | Offline signing host — **not** on every vehicle image |

This process does **not** replace a hardware security module. Without a TPM /
ATECC / PKCS#11 token, the Fernet key is still recoverable from disk if the
host is compromised. See Phase 7 notes in `security-assumptions.md`.

---

## Invariants (non-negotiable)

1. **No secrets in the image.** Docker / Yocto / SD-card images ship code and
   empty placeholders only. `secrets.env` is gitignored and listed in
   `.dockerignore`. CI must never echo secret values.
2. **Keys are born on-device.** The Fernet `.bio_key` is generated on first boot
   of that vehicle’s store directory — not copied from a factory USB stick that
   also went into other vehicles, and not baked by the build server.
3. **One vehicle ↔ one identity store.** Cloning a store directory between
   vehicles clones biometrics and keys; treat that as a security incident.
4. **Never log values.** `driveauth.secrets` logs counts and paths only.
   `tests/test_secrets.py` greps for accidental secret logging.

---

## First-boot sequence (per vehicle)

Run once on the head unit after flashing a clean image:

```bash
# 1. Create the vehicle store (empty). Pick a path that survives OTA.
export DRIVEAUTH_STORE=/var/driveauth/store
mkdir -p "$DRIVEAUTH_STORE"

# 2. Generate the Fernet template key ON THIS DEVICE.
#    ensure_key() creates .bio_key if missing; do not scp an existing key.
python - <<'PY'
from pathlib import Path
from driveauth.template_store import ensure_key
from driveauth.key_protection import load_protector
import os

store = Path(os.environ["DRIVEAUTH_STORE"])
# Optional: DRIVEAUTH_KEY_PROTECTOR=tpm when a TPM 2.0 + tpm2-pytss is present.
prot = load_protector()
ensure_key(store, protector=prot)
print("created", store / ".bio_key")  # path only — never print key bytes
PY

# 3. Provision product secrets WITHOUT putting them in the image.
#    Prefer Vault (or your cloud SM) over a long-lived secrets.env on disk.
export DRIVEAUTH_SECRETS_PROVIDER=vault
export DRIVEAUTH_VAULT_ADDR=https://vault.fleet.example:8200
export DRIVEAUTH_VAULT_TOKEN=...   # short-lived, from your join/bootstrap flow
export DRIVEAUTH_VAULT_MOUNT=secret
export DRIVEAUTH_VAULT_PATH=driveauth/vehicles/${VEHICLE_ID}

# Dev / lab only — EnvFile remains the default:
#   cp secrets.env.example /var/driveauth/secrets.env
#   export DRIVEAUTH_SECRETS_FILE=/var/driveauth/secrets.env
#   export DRIVEAUTH_SECRETS_PROVIDER=env

# 4. Enroll the driver only after consent (Phase E) and on this store.
```

After step 2, `.bio_key` exists only on that filesystem. Rebuilds and OTA
packages must **not** overwrite it; treat the store volume as durable state
separate from the application image (see Railway `/data` volume pattern in
`docs/standalone.md`).

---

## Provider selection

| `DRIVEAUTH_SECRETS_PROVIDER` | Class | When to use |
|------------------------------|-------|-------------|
| `env` (default) | `EnvFileSecretsProvider` | Lab, laptop demo, single-vehicle bring-up |
| `vault` | `VaultSecretsProvider` | Fleet: secrets live in HashiCorp Vault KV v2; HTTP client is swappable for tests / alternate SDKs |
| `hsm` | `HSMSecretsProvider` | **Stub only** until a PKCS#11 / vendor backend is injected — `get()` raises without a backend |

Cloud secret managers (AWS Secrets Manager, GCP Secret Manager, Azure Key Vault)
can sit behind the same `VaultHttpClient`-style adapter: implement
`(method, url, headers, body) -> (status, body)` or wrap the vendor SDK in a
tiny `SecretsProvider` and pass it via `set_secrets_provider(...)`.

---

## HSM / TPM honesty bar

| Layer | Status |
|-------|--------|
| `SoftwareKeyProtector` | Default — Fernet key bytes on disk |
| `TPMKeyProtector` | Optional seal of `.bio_key` when TPM 2.0 hardware + `tpm2-pytss` exist |
| `HSMSecretsProvider` | Interface stub — **not** a working HSM integration |

Shipping `HSMSecretsProvider` in-tree does **not** mean vehicles have HSM-backed
secrets. Closing that risk requires selecting hardware, injecting a real
backend, and validating attestation in a pilot fleet — work this repository
cannot manufacture from software alone.

---

## Rotation & retirement

- **API tokens / Vault:** rotate in Vault (or the cloud SM); vehicles pick up
  new values on next process start / cache refresh. Do not commit rotated
  values into git.
- **Fernet `.bio_key`:** rotation implies re-encrypting every template under
  `voices/`, `faces/`, `fingers/`. Prefer re-enrollment on a fresh store over
  ad-hoc key swap unless you have a tested rewrap tool.
- **Vehicle decommission:** wipe the store volume (secure erase if the media
  supports it), revoke the Vault path / AppRole for that `VEHICLE_ID`, and
  destroy any HSM slots bound to the unit.

---

## Checklist before calling a vehicle “provisioned”

- [ ] Image contains no `secrets.env` and no `.bio_key`
- [ ] `.bio_key` created on-device after first boot (path logged, value never logged)
- [ ] `DRIVEAUTH_SECRETS_PROVIDER` points at Vault (or equivalent) for fleet units
- [ ] Vault/AppRole scoped to that vehicle path only
- [ ] TPM protector enabled **if** the SoC has a usable TPM (otherwise document the residual disk-key risk)
- [ ] Store volume excluded from image OTA overlays
