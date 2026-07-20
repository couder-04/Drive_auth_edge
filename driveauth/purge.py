"""Driver biometric purge — delete templates, OOD baselines, profile, consent.

Phase E: ``purge_driver`` guarantees removal of recoverable biometric material
for a driver_id. Audit log history is **not** rewritten (Phase B hash chain);
entries retain metadata/scores only (no templates). See
``docs/biometric-data-policy.md``.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from driveauth.consent import delete_consent
from driveauth.enrollment import validate_driver_id

logger = logging.getLogger("driveauth.purge")


def _unlink(path: Path, removed: list[str]) -> None:
    if path.is_file():
        path.unlink()
        removed.append(str(path))
    elif path.is_dir():
        shutil.rmtree(path)
        removed.append(str(path))


def purge_driver_templates(store_dir: str | Path, driver_id: str) -> list[str]:
    """Remove encrypted biometric templates for ``driver_id``."""
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    removed: list[str] = []
    for rel in (
        f"voices/{driver_id}.enc",
        f"faces/{driver_id}.enc",
        f"fingers/{driver_id}.enc",
        f"behavioral/{driver_id}.enc",
    ):
        _unlink(store / rel, removed)
    return removed


def purge_driver_ood(store_dir: str | Path, driver_id: str) -> list[str]:
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir) / "ood_stats"
    removed: list[str] = []
    if not store.is_dir():
        return removed
    for path in store.glob(f"*_{driver_id}.npz"):
        _unlink(path, removed)
    return removed


def purge_driver_profile(store_dir: str | Path, driver_id: str) -> list[str]:
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    removed: list[str] = []
    # Per-driver profile file used by DriveAuth.load
    _unlink(store / "profiles" / f"{driver_id}.json", removed)
    # Also scrub from multi-driver aggregate profile JSON if present
    for path in (store / "profiles").glob("*.json") if (store / "profiles").is_dir() else []:
        if path.name == f"{driver_id}.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and driver_id in data:
            del data[driver_id]
            path.write_text(json.dumps(data), encoding="utf-8")
            removed.append(f"{path}#{driver_id}")
    return removed


def purge_driver_contacts(store_dir: str | Path, driver_id: str) -> list[str]:
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    removed: list[str] = []
    for rel in (
        f"contacts/{driver_id}.mobile",
        f"contacts/{driver_id}.bt_mac",
        f"beneficiaries/{driver_id}.txt",
        f"pins/{driver_id}.pin",
    ):
        _unlink(store / rel, removed)
    return removed


def biometric_residue(store_dir: str | Path, driver_id: str) -> list[str]:
    """Paths that still look like recoverable biometric material for driver_id."""
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    hits: list[str] = []
    for rel in (
        f"voices/{driver_id}.enc",
        f"faces/{driver_id}.enc",
        f"fingers/{driver_id}.enc",
        f"behavioral/{driver_id}.enc",
        f"profiles/{driver_id}.json",
        f"consent/{driver_id}.json",
    ):
        if (store / rel).exists():
            hits.append(rel)
    ood = store / "ood_stats"
    if ood.is_dir():
        for path in ood.glob(f"*_{driver_id}.npz"):
            hits.append(str(path.relative_to(store)))
    return hits


def purge_driver(
    store_dir: str | Path,
    driver_id: str,
    *,
    data_root: str | Path | None = None,
    remove_sample_files: bool = False,
) -> dict[str, Any]:
    """Delete all biometric templates / OOD / profile / consent for a driver.

    Does **not** rewrite the audit log (hash-chain integrity). Sample WAVs/JPGs
    under ``data_root/<id>/`` are removed only when ``remove_sample_files=True``.
    """
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    removed: list[str] = []
    removed.extend(purge_driver_templates(store, driver_id))
    removed.extend(purge_driver_ood(store, driver_id))
    removed.extend(purge_driver_profile(store, driver_id))
    removed.extend(purge_driver_contacts(store, driver_id))
    if delete_consent(store, driver_id):
        removed.append(str(store / "consent" / f"{driver_id}.json"))

    if remove_sample_files and data_root is not None:
        sample_dir = Path(data_root) / driver_id
        if sample_dir.is_dir():
            shutil.rmtree(sample_dir)
            removed.append(str(sample_dir))

    residue = biometric_residue(store, driver_id)
    logger.info(
        "purge_driver id=%s removed=%d residue=%d",
        driver_id,
        len(removed),
        len(residue),
    )
    return {
        "driver_id": driver_id,
        "removed": removed,
        "residue": residue,
        "complete": len(residue) == 0,
    }
