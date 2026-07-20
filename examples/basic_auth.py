"""Basic authentication example.

For live mic capture on-device, replace the silence buffer with::

    from hardware.mic_capture import MicArrayCapture, NumpyAudioBackend
    mic = MicArrayCapture(backend=NumpyAudioBackend(audio))  # or real backend
    mic.start()
    audio = mic.capture(seconds=1.5)
"""

import numpy as np

from driveauth import DriveAuth

audio = np.zeros(16_000, dtype=np.float32)  # 1s silence — mock matcher ignores content

auth = DriveAuth.load(store_dir="./example_store", use_mock_matchers=True)
result = auth.authenticate(audio_np=audio, amount=99.0, beneficiary_known=True)

print(result.decision.value)
print(f"trust={result.trust_score:.2f} risk={result.risk_score:.2f} conf={result.confidence_score:.2f}")
