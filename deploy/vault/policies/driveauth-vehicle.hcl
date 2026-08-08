# Read-only policy for a single vehicle AppRole.
# Mount secrets at: secret/data/driveauth/vehicles/<vehicle_id>
path "secret/data/driveauth/vehicles/{{identity.entity.aliases.auth_approle_*.metadata.vehicle_id}}" {
  capabilities = ["read"]
}

path "secret/metadata/driveauth/vehicles/{{identity.entity.aliases.auth_approle_*.metadata.vehicle_id}}" {
  capabilities = ["read"]
}
