"""Explicit biometric consent records (Phase E).

Enrollment must not proceed without a consent record for that driver.
This is a process/code gate — **not** a legal certification. BIPA / GDPR-class
biometric statutes still require counsel sign-off before enrolling non-test
drivers. See ``docs/biometric-data-policy.md``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("driveauth.consent")

# What we collect under a typical enrollment — recorded for transparency.
DEFAULT_COLLECTED = (
    "voice_embedding",
    "face_embedding",
    "ood_baseline_stats",
    "optional_fingerprint_template",
)


class ConsentRequiredError(RuntimeError):
    """Raised when enrollment is attempted without a consent record."""


def consent_path(store_dir: str | Path, driver_id: str) -> Path:
    return Path(store_dir) / "consent" / f"{driver_id}.json"


def record_consent(
    store_dir: str | Path,
    driver_id: str,
    *,
    collected: tuple[str, ...] | list[str] | None = None,
    notes: str = "",
    timestamp: float | None = None,
) -> dict[str, Any]:
    """Write an explicit consent record. Returns the record dict."""
    from driveauth.enrollment import validate_driver_id

    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    path = consent_path(store, driver_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "driver_id": driver_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp or time.time())),
        "ts_unix": float(timestamp if timestamp is not None else time.time()),
        "collected": list(collected) if collected is not None else list(DEFAULT_COLLECTED),
        "notes": (notes or "")[:500],
        "version": 1,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info("Consent recorded for driver_id=%s path=%s", driver_id, path)
    return record


def load_consent(store_dir: str | Path, driver_id: str) -> dict[str, Any] | None:
    from driveauth.enrollment import validate_driver_id

    driver_id = validate_driver_id(driver_id)
    path = consent_path(store_dir, driver_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("driver_id") != driver_id:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def require_consent(store_dir: str | Path, driver_id: str) -> dict[str, Any]:
    """Return the consent record or raise :class:`ConsentRequiredError`."""
    rec = load_consent(store_dir, driver_id)
    if rec is None:
        raise ConsentRequiredError(
            f"No consent record for driver_id={driver_id!r}; "
            "call driveauth.consent.record_consent() before enrollment. "
            "Legal review (BIPA/GDPR-class) is still required for non-test drivers."
        )
    return rec


def delete_consent(store_dir: str | Path, driver_id: str) -> bool:
    path = consent_path(store_dir, driver_id)
    if path.is_file():
        path.unlink()
        return True
    return False
