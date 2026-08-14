"""High-value payment without real fingerprint hardware.

Without a real stage-3 probe, PolicyEngine must not Accept. It returns
STEP_UP_REQUIRED (otp_mobile) so a legitimate driver can fall back to OTP/PIN
instead of a silent Accept (the old bug) or a silent Reject.
"""

import numpy as np
from driveauth import DriveAuth
from driveauth.types import Decision

auth = DriveAuth.load(store_dir="./example_store", use_mock_matchers=True)

# Simulate vehicle context — moving fast increases risk
auth.update_vehicle_context(speed_kmh=90.0, in_trusted_zone=False, dist_from_home_km=40.0)

audio = np.random.randn(24_000).astype(np.float32) * 0.05
result = auth.authenticate(
    audio_np=audio,
    amount=60_000.0,
    beneficiary_known=False,
    beneficiary="new_merchant",
    action="pay",
)

assert result.decision == Decision.STEP_UP_REQUIRED
assert result.step_up_method == "otp_mobile"
print("High-value payment requires step-up:", result.step_up_method)
print("Policy:", result.policy_rule)
