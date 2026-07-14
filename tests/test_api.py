import tempfile
from pathlib import Path


from driveauth import DriveAuth
from driveauth.fraud_state import FraudState, FraudStateMachine
from driveauth.types import Decision
from testsupport import good_audio, mature


def test_bootstrap_requires_stepup_for_new_driver():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    result = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert result.decision == Decision.STEP_UP_REQUIRED
    assert result.fraud_state == "bootstrap"


def test_driveauth_accept_when_profile_mature():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    result = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert result.decision == Decision.ACCEPT
    assert result.trust_score > 0.8
    # Mock embeddings must match seeded OOD dims (was 128-d face vs 512-d baseline).
    assert not result.ood_flags.get("face")
    assert not any("ood" in e for e in result.explanations)


def test_mock_ood_embedding_dims_align():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    face = auth._engine._m.face.score_frame(auth._engine._m.face.capture_frame())
    voice = auth._engine._m.voice.score(good_audio())
    assert face.embedding is not None and face.embedding.shape == (512,)
    assert voice.embedding is not None and voice.embedding.shape == (192,)
    assert auth._engine._ood.face._mean is not None
    assert auth._engine._ood.face._mean.shape == face.embedding.shape
    assert auth._engine._ood.voice._mean.shape == voice.embedding.shape


def test_bootstrap_amount_cap():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    result = auth.authenticate(
        audio_np=good_audio(), amount=99999.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert result.decision in (Decision.STEP_UP_REQUIRED, Decision.REJECT)


def test_second_layer_reuses_cached_decision():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    first = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert first.decision == Decision.ACCEPT
    second = auth.require_auth(tier="payment", amount=50.0, beneficiary_known=True)
    assert second is first


def test_second_layer_reprobe_on_higher_tier():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    first = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    second = auth.require_auth(tier="payment", amount=90000.0, beneficiary_known=False)
    assert second is not first


def test_fraud_ladder_escalates():
    store = tempfile.mkdtemp()
    path = Path(store) / "fraud" / "ladder.json"
    fsm = FraudStateMachine(path, "driver1")
    assert fsm.state == FraudState.NORMAL
    fsm.record_soft_flag("test")
    assert fsm.state == FraudState.ELEVATED
    fsm.record_soft_flag("test2")
    assert fsm.state == FraudState.HEIGHTENED


def test_suspicion_wins_over_bootstrap():
    store = tempfile.mkdtemp()
    fsm = FraudStateMachine(Path(store) / "fraud" / "ladder.json", "driver1")
    fsm.record_soft_flag("a")
    fsm.record_soft_flag("b")
    assert fsm.effective_state(profile_mature=False) == FraudState.HEIGHTENED
