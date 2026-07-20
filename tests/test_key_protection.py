"""Phase 7 — KeyProtector (software default + mocked TPM)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from driveauth.key_protection import (
    SoftwareKeyProtector,
    TPMKeyProtector,
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
