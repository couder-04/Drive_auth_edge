# Vault operations (TODO 17)

Policy files: `deploy/vault/policies/`. Code: `driveauth/secrets.py`
(`VaultSecretsProvider`).

## Bootstrap (once per fleet)

```bash
vault secrets enable -path=secret kv-v2   # if not already
vault policy write driveauth-vehicle deploy/vault/policies/driveauth-vehicle.hcl
vault policy write driveauth-fleet-admin deploy/vault/policies/driveauth-fleet-admin.hcl

vault kv put secret/driveauth/vehicles/vehicle_01 \
  OPENROUTER_API_KEY=... \
  DRIVEAUTH_DASHBOARD_API_KEY=...
```

## Per-vehicle AppRole

```bash
VEHICLE=vehicle_01
vault auth enable approle || true
vault write auth/approle/role/driveauth-${VEHICLE} \
  token_policies=driveauth-vehicle \
  token_ttl=24h token_max_ttl=720h \
  secret_id_ttl=0

vault write auth/approle/role/driveauth-${VEHICLE}/custom_metadata vehicle_id=${VEHICLE}

ROLE_ID=$(vault read -field=role_id auth/approle/role/driveauth-${VEHICLE}/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/driveauth-${VEHICLE}/secret-id)
```

On the vehicle (preferred over long-lived root token):

```bash
DRIVEAUTH_SECRETS_PROVIDER=vault
DRIVEAUTH_VAULT_ADDR=https://vault.example:8200
DRIVEAUTH_VAULT_ROLE_ID=<role_id>
DRIVEAUTH_VAULT_SECRET_ID=<secret_id>
DRIVEAUTH_VAULT_MOUNT=secret
DRIVEAUTH_VAULT_PATH=driveauth/vehicles/vehicle_01
```

Legacy static token still works: `DRIVEAUTH_VAULT_TOKEN=…`.

## Token rotation (every 90 days recommended)

1. Issue new AppRole `secret_id` for the vehicle.
2. Deploy new id via OTA env or secure provisioning USB.
3. Revoke old accessor: `vault token revoke <accessor>`.
4. Audit: `vault list auth/token/accessors`.

## Decommission

1. `vault kv metadata delete secret/driveauth/vehicles/<id>`
2. Revoke all tokens for that AppRole.
3. Wipe `/data` volume on device (see `driveauth/purge.py`).

## Local dev

```bash
docker compose -f docker-compose.vault.yml up -d
export DRIVEAUTH_VAULT_ADDR=http://127.0.0.1:8200
export DRIVEAUTH_VAULT_TOKEN=root
export DRIVEAUTH_SECRETS_PROVIDER=vault
```
