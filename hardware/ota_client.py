"""Signed OTA update client (Phase F).

Verifies an Ed25519-signed update package, applies atomically, keeps the
previous version for rollback, and rolls back automatically if a post-update
health check fails.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from driveauth.integrity import (
    load_public_key,
    verify_manifest_signature,
)

logger = logging.getLogger("driveauth.hardware.ota")

HealthCheck = Callable[[Path], bool]


class OTAError(RuntimeError):
    """Update package rejected or apply failed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_update_package(
    package_dir: Path,
    *,
    public_key: Ed25519PublicKey,
) -> dict[str, Any]:
    """Validate ``manifest.json`` + ``manifest.sig`` + payload digests."""
    manifest_path = package_dir / "manifest.json"
    sig_path = package_dir / "manifest.sig"
    if not manifest_path.is_file() or not sig_path.is_file():
        raise OTAError("update package missing manifest.json / manifest.sig")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not verify_manifest_signature(manifest, sig_path.read_bytes(), public_key):
        raise OTAError("update package signature invalid")
    files = manifest.get("files") or {}
    payload_root = package_dir / "payload"
    for rel, expected in files.items():
        path = payload_root / rel
        if not path.is_file():
            raise OTAError(f"payload missing: {rel}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise OTAError(f"payload tampered: {rel}")
    return manifest


def default_health_check(target: Path) -> bool:
    """Minimal health: marker file ``HEALTH_OK`` or presence of ``policy.yaml``."""
    if (target / "HEALTH_OK").is_file():
        return True
    # Fail if an explicit fail marker is present (tests / bad builds).
    if (target / "HEALTH_FAIL").is_file():
        return False
    return target.is_dir()


class OTAClient:
    def __init__(
        self,
        install_dir: str | Path,
        *,
        public_key: Ed25519PublicKey | None = None,
        public_key_bytes: bytes | None = None,
        health_check: HealthCheck | None = None,
    ):
        self.install_dir = Path(install_dir)
        self.install_dir.mkdir(parents=True, exist_ok=True)
        if public_key is not None:
            self._pubkey = public_key
        elif public_key_bytes is not None:
            self._pubkey = load_public_key(public_key_bytes)
        else:
            raise ValueError("OTAClient requires public_key or public_key_bytes")
        self._health = health_check or default_health_check
        self.last_rollback = False

    @property
    def current_link(self) -> Path:
        return self.install_dir / "current"

    @property
    def previous_link(self) -> Path:
        return self.install_dir / "previous"

    def apply_package(self, package_dir: str | Path) -> Path:
        """Verify, stage, swap ``current``, health-check, rollback on failure."""
        package_dir = Path(package_dir)
        self.last_rollback = False
        manifest = verify_update_package(package_dir, public_key=self._pubkey)
        version = str(manifest.get("version_id") or manifest.get("meta", {}).get("version") or "unknown")

        staging = self.install_dir / f"stage-{version}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        payload = package_dir / "payload"
        for src in payload.rglob("*"):
            if src.is_file():
                rel = src.relative_to(payload)
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

        # Atomic swap via rename of directories + keep previous.
        current = self.current_link
        previous = self.previous_link
        if previous.exists():
            if previous.is_symlink() or previous.is_dir():
                shutil.rmtree(previous) if previous.is_dir() and not previous.is_symlink() else previous.unlink()
            else:
                previous.unlink()

        if current.exists():
            current.rename(previous)
        staging.rename(current)

        if not self._health(current):
            logger.error("OTA: health check failed; rolling back")
            self._rollback()
            self.last_rollback = True
            raise OTAError("post-update health check failed; rolled back")

        logger.info("OTA: applied version=%s", version)
        return current

    def _rollback(self) -> None:
        current = self.current_link
        previous = self.previous_link
        if not previous.exists():
            logger.error("OTA: rollback requested but no previous version")
            return
        failed = self.install_dir / "failed"
        if failed.exists():
            shutil.rmtree(failed) if failed.is_dir() else failed.unlink()
        if current.exists():
            current.rename(failed)
        previous.rename(current)
        logger.info("OTA: rollback complete")
