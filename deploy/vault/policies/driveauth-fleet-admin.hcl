# Fleet admin — create/revoke vehicle tokens, rotate secrets.
path "secret/data/driveauth/vehicles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/driveauth/vehicles/*" {
  capabilities = ["list", "read", "delete"]
}

path "auth/approle/role/driveauth-vehicle-*/token" {
  capabilities = ["create", "update"]
}

path "auth/token/revoke" {
  capabilities = ["update"]
}
