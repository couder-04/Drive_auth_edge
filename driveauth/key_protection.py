"""Optional secure-element wrapping for the Fernet template key (Phase 7).

Defense-in-depth on top of Fernet, not a replacement. Default
``SoftwareKeyProtector`` is identity wrap/unwrap — identical to today's
raw ``.bio_key`` on disk. ``TPMKeyProtector`` seals that Fernet key with a
TPM 2.0 primary (via ``tpm2-pytss``) so the on-disk blob is useless without
the chip.

This does **not** close the at-rest gap on hardware that lacks a secure
element — it is an upgrade path, off by default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger("driveauth.key_protection")

# Magic prefix so we can detect TPM-wrapped blobs vs legacy raw Fernet keys.
_TPM_BLOB_MAGIC = b"DASE1\0"  # DriveAuth Secure Element v1


@runtime_checkable
class KeyProtector(Protocol):
    def wrap(self, key_material: bytes) -> bytes:
        """Protect key material for storage. Never raises for soft failures
        in production paths — callers treat Falsey / exceptions as fail-closed."""
        ...

    def unwrap(self, blob: bytes) -> bytes:
        """Recover key material from a wrapped blob."""
        ...


class SoftwareKeyProtector:
    """Today's Fernet-key-on-disk behaviour: wrap/unwrap are identity."""

    def wrap(self, key_material: bytes) -> bytes:
        return bytes(key_material)

    def unwrap(self, blob: bytes) -> bytes:
        return bytes(blob)


class TPMKeyProtector:
    """
    Seal the Fernet key with a TPM 2.0 (tpm2-pytss).

    On hosts without a TPM or without ``tpm2-pytss``, construction raises
    ``RuntimeError`` — callers must opt in explicitly; SoftwareKeyProtector
    remains the default.
    """

    def __init__(
        self,
        *,
        tcti: str | None = None,
        esys_factory=None,
    ):
        """
        ``esys_factory`` is a zero-arg callable returning an ESAPI-like object
        with ``create_primary`` / ``create`` / ``load`` / ``flush_context`` /
        ``unseal`` (injected in unit tests). When omitted, imports tpm2-pytss.
        """
        self._tcti = tcti
        self._esys_factory = esys_factory
        if esys_factory is None:
            try:
                import tpm2_pytss  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "TPMKeyProtector requires tpm2-pytss and a TPM 2.0 device; "
                    "install the board SDK / pip package or keep SoftwareKeyProtector"
                ) from exc

    def wrap(self, key_material: bytes) -> bytes:
        sealed = self._seal(key_material)
        return _TPM_BLOB_MAGIC + sealed

    def unwrap(self, blob: bytes) -> bytes:
        if not blob.startswith(_TPM_BLOB_MAGIC):
            # Legacy raw Fernet key written before TPM opt-in — allow read so
            # migrations can re-wrap; do not claim TPM protection for it.
            logger.warning(
                "TPMKeyProtector: blob lacks SE magic — treating as legacy plaintext key"
            )
            return bytes(blob)
        return self._unseal(blob[len(_TPM_BLOB_MAGIC) :])

    def _esys(self):
        if self._esys_factory is not None:
            return self._esys_factory()
        from tpm2_pytss import ESAPI  # type: ignore

        return ESAPI(self._tcti) if self._tcti else ESAPI()

    def _seal(self, key_material: bytes) -> bytes:
        """
        Minimal seal: create a primary, seal data as a keyedobject, return
        serialised private||public blobs. Exact TSS layout is backend-specific;
        tests inject a fake ESAPI.
        """
        esys = self._esys()
        try:
            if hasattr(esys, "seal"):
                return bytes(esys.seal(key_material))
            # tpm2-pytss-shaped path (simplified; real boards may use NV index).
            primary_handle, _, _, _, _ = esys.create_primary(None, None)
            priv, pub, _, _, _ = esys.create(
                primary_handle, None, sensitive_data=key_material
            )
            esys.flush_context(primary_handle)
            return bytes(priv) + b"\0SEP\0" + bytes(pub)
        except Exception as exc:
            raise RuntimeError(f"TPM seal failed: {type(exc).__name__}") from exc
        finally:
            close = getattr(esys, "close", None) or getattr(esys, "__exit__", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _unseal(self, sealed: bytes) -> bytes:
        esys = self._esys()
        try:
            if hasattr(esys, "unseal_blob"):
                return bytes(esys.unseal_blob(sealed))
            if b"\0SEP\0" not in sealed:
                raise RuntimeError("malformed TPM sealed blob")
            priv, pub = sealed.split(b"\0SEP\0", 1)
            primary_handle, _, _, _, _ = esys.create_primary(None, None)
            obj = esys.load(primary_handle, priv, pub)
            data = esys.unseal(obj)
            esys.flush_context(obj)
            esys.flush_context(primary_handle)
            return bytes(data)
        except Exception as exc:
            raise RuntimeError(f"TPM unseal failed: {type(exc).__name__}") from exc
        finally:
            close = getattr(esys, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def default_protector() -> KeyProtector:
    """Fail-closed default: software identity (today's behaviour)."""
    return SoftwareKeyProtector()


def load_protector(name: str, **kwargs) -> KeyProtector:
    """Factory: ``software`` (default) or ``tpm``."""
    key = (name or "software").strip().lower()
    if key in ("software", "soft", "none", "off"):
        return SoftwareKeyProtector()
    if key in ("tpm", "tpm2", "hardware"):
        return TPMKeyProtector(**kwargs)
    raise ValueError(f"unknown key protector {name!r}; use software|tpm")


KEY_PATH_NAME = ".bio_key"


def read_store_key(store_dir: Path, protector: KeyProtector) -> bytes:
    path = Path(store_dir) / KEY_PATH_NAME
    return protector.unwrap(path.read_bytes())


def write_store_key(store_dir: Path, key_material: bytes, protector: KeyProtector) -> Path:
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    path = store / KEY_PATH_NAME
    path.write_bytes(protector.wrap(key_material))
    return path
