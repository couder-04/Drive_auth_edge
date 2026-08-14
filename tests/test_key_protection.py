"""Phase 7 — KeyProtector (software default + mocked TPM)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from driveauth.key_protection import (
    SoftwareKeyProtector,
    TPMKeyProtector,
    configured_protector,
    default_protector,
    load_protector,
)
from driveauth.template_store import TemplateStore, ensure_key, load_embedding, save_embedding


def test_software_protector_is_identity():
    p = SoftwareKeyProtector()
    key = b"fernet-key-bytes-example-32chars!!"
    assert p.wrap(key) == key
    assert p.unwrap(key) == key


def test_software_roundtrip_matches_legacy_fernet(tmp_path: Path):
    """SoftwareKeyProtector must match today's raw .bio_key + Fernet encrypt."""
    from cryptography.fernet import Fernet

    emb = np.random.default_rng(0).normal(size=16).astype(np.float32)
    emb /= np.linalg.norm(emb)

    # Legacy-style path (default protector).
    save_embedding(tmp_path / "a", "voices/d.enc", emb)
    # Explicit SoftwareKeyProtector.
    save_embedding(tmp_path / "b", "voices/d.enc", emb, protector=SoftwareKeyProtector())

    key_a = (tmp_path / "a" / ".bio_key").read_bytes()
    key_b = (tmp_path / "b" / ".bio_key").read_bytes()
    # Both are raw Fernet keys (url-safe base64), unwrap-identity.
    assert SoftwareKeyProtector().unwrap(key_a) == key_a
    assert SoftwareKeyProtector().unwrap(key_b) == key_b

    loaded_a = load_embedding(tmp_path / "a", "voices/d.enc")
    loaded_b = load_embedding(tmp_path / "b", "voices/d.enc")
    assert loaded_a is not None and loaded_b is not None
    np.testing.assert_allclose(loaded_a, loaded_b, atol=1e-6)

    # Decrypt with Fernet directly from on-disk key — legacy consumers.
    f = Fernet(key_a)
    raw = f.decrypt((tmp_path / "a" / "voices" / "d.enc").read_bytes())
    direct = np.frombuffer(raw, dtype=np.float32).copy()
    direct /= np.linalg.norm(direct)
    np.testing.assert_allclose(direct, loaded_a, atol=1e-6)


def test_template_store_construction_default(tmp_path: Path):
    store = TemplateStore(tmp_path)
    assert isinstance(store.protector, SoftwareKeyProtector)
    store.ensure_key()
    assert (tmp_path / ".bio_key").exists()


def test_tpm_protector_roundtrip_with_mock_esys(tmp_path: Path):
    sealed_store: dict[str, bytes] = {}

    class FakeEsys:
        def seal(self, data: bytes) -> bytes:
            sealed_store["d"] = bytes(data)
            return b"SEALED:" + data

        def unseal_blob(self, sealed: bytes) -> bytes:
            assert sealed.startswith(b"SEALED:")
            return sealed[len(b"SEALED:") :]

        def close(self):
            pass

    prot = TPMKeyProtector(esys_factory=FakeEsys)
    key = b"0123456789abcdef0123456789abcdef"
    blob = prot.wrap(key)
    assert blob.startswith(b"DASE1\0")
    assert prot.unwrap(blob) == key

    store = TemplateStore(tmp_path, protector=prot)
    emb = np.ones(8, dtype=np.float32)
    emb /= np.linalg.norm(emb)
    store.save_embedding("faces/x.enc", emb)
    out = store.load_embedding("faces/x.enc")
    assert out is not None
    np.testing.assert_allclose(out, emb, atol=1e-6)


def test_tpm_protector_requires_library_without_factory():
    with pytest.raises(RuntimeError, match="tpm2-pytss"):
        # Force import failure path by not providing factory; if tpm2_pytss is
        # somehow installed this still constructs — skip in that case.
        try:
            import tpm2_pytss  # noqa: F401

            pytest.skip("tpm2-pytss installed in this environment")
        except ImportError:
            TPMKeyProtector()


def test_load_protector_factory():
    assert isinstance(load_protector("software"), SoftwareKeyProtector)
    assert isinstance(default_protector(), SoftwareKeyProtector)


def test_ensure_key_default_unchanged(tmp_path: Path):
    p = ensure_key(tmp_path)
    assert p.name == ".bio_key"
    raw = p.read_bytes()
    # Fernet keys are 44-byte url-safe base64.
    assert len(raw) >= 32


def test_legacy_hmac_pin_still_verifies_and_upgrades(tmp_path: Path, monkeypatch):
    """v1 HMAC-SHA256 PIN blobs must still verify after the PBKDF2 change."""
    import hashlib
    import hmac
    import secrets

    from cryptography.fernet import Fernet

    from driveauth.step_up_fallback import StepUpFallback, parse_pin_blob

    monkeypatch.setattr("driveauth.config.PIN_PBKDF2_ITERATIONS", 100_000)
    pin = "1234"
    key = Fernet.generate_key()
    (tmp_path / ".bio_key").write_bytes(key)
    salt = secrets.token_bytes(16)
    digest = hmac.new(salt, pin.encode("utf-8"), hashlib.sha256).digest()
    pin_path = tmp_path / "pins" / "driver1.enc"
    pin_path.parent.mkdir(parents=True)
    pin_path.write_bytes(Fernet(key).encrypt(salt + digest))

    kind, _, _, _ = parse_pin_blob(salt + digest)
    assert kind == "hmac-sha256"

    fb = StepUpFallback(str(tmp_path), "driver1")
    assert fb._pin_kind == "hmac-sha256"
    assert fb.verify_pin(pin) is True
    assert fb.verify_pin("0000") is False
    # Successful v1 verify re-enrolls as PBKDF2.
    fb2 = StepUpFallback(str(tmp_path), "driver1")
    assert fb2._pin_kind == "pbkdf2-sha256"
    assert fb2.verify_pin(pin) is True


def test_enroll_pin_uses_pbkdf2(tmp_path: Path, monkeypatch):
    from cryptography.fernet import Fernet

    from driveauth.step_up_fallback import StepUpFallback, enroll_pin, parse_pin_blob

    monkeypatch.setattr("driveauth.config.PIN_PBKDF2_ITERATIONS", 100_000)
    assert enroll_pin(str(tmp_path), "driver1", "9876") is True
    raw = Fernet((tmp_path / ".bio_key").read_bytes()).decrypt(
        (tmp_path / "pins" / "driver1.enc").read_bytes()
    )
    kind, _, _, iters = parse_pin_blob(raw)
    assert kind == "pbkdf2-sha256"
    assert iters == 100_000
    assert StepUpFallback(str(tmp_path), "driver1").verify_pin("9876") is True


def test_integrity_defaults_on_in_production(tmp_path: Path, monkeypatch):
    from driveauth.integrity import IntegrityError, integrity_check_enabled, verify_store_integrity

    monkeypatch.setenv("DRIVEAUTH_ENV", "production")
    monkeypatch.delenv("DRIVEAUTH_INTEGRITY_CHECK", raising=False)
    assert integrity_check_enabled() is True
    with pytest.raises(IntegrityError, match="missing"):
        verify_store_integrity(tmp_path)


def test_integrity_defaults_off_outside_production(tmp_path: Path, monkeypatch):
    from driveauth.integrity import integrity_check_enabled, verify_store_integrity

    monkeypatch.delenv("DRIVEAUTH_ENV", raising=False)
    monkeypatch.delenv("DRIVEAUTH_ENVIRONMENT", raising=False)
    monkeypatch.delenv("DRIVEAUTH_INTEGRITY_CHECK", raising=False)
    assert integrity_check_enabled() is False
    ok, reason = verify_store_integrity(tmp_path)
    assert ok and reason == "skipped"


def test_tpm_requested_unavailable_raises(monkeypatch):
    monkeypatch.setattr("driveauth.config.KEY_PROTECTOR", "tpm")
    monkeypatch.delenv("DRIVEAUTH_ALLOW_KEY_PROTECTOR_FALLBACK", raising=False)

    def _boom(**kwargs):
        raise RuntimeError("tpm2-pytss missing")

    monkeypatch.setattr("driveauth.key_protection.TPMKeyProtector", _boom)
    with pytest.raises(RuntimeError, match="ALLOW_KEY_PROTECTOR_FALLBACK"):
        configured_protector()


def test_tpm_requested_unavailable_fallback_opt_in(monkeypatch):
    monkeypatch.setattr("driveauth.config.KEY_PROTECTOR", "tpm")
    monkeypatch.setenv("DRIVEAUTH_ALLOW_KEY_PROTECTOR_FALLBACK", "1")

    def _boom(**kwargs):
        raise RuntimeError("tpm2-pytss missing")

    monkeypatch.setattr("driveauth.key_protection.TPMKeyProtector", _boom)
    p = configured_protector()
    assert isinstance(p, SoftwareKeyProtector)
