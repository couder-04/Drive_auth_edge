"""Append-only audit log for every authentication decision.

Phase B: each entry carries ``prev_hash`` / ``entry_hash`` (SHA-256) so
history tampering is detectable via :meth:`AuditLog.verify_chain`.
Optional remote shipping (``DRIVEAUTH_AUDIT_REMOTE_URL``) is off by default —
once enabled, a vehicle owner with local disk access cannot quietly rewrite
the trail without also controlling the remote sink.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from driveauth.types import DriveAuthResult

logger = logging.getLogger("driveauth.audit")

GENESIS_HASH = "0" * 64

# Injected in unit tests: (url, body_bytes, headers) -> None
RemoteSink = Callable[[str, bytes, dict[str, str]], None]


def _canonical_bytes(entry: dict[str, Any]) -> bytes:
    """Stable JSON for hashing — excludes ``entry_hash`` itself."""
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_entry(entry: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(entry)).hexdigest()


def verify_chain(entries: list[dict[str, Any]]) -> tuple[bool, str]:
    """Return ``(ok, reason)``. Empty list is valid (vacuous chain)."""
    prev = GENESIS_HASH
    for i, entry in enumerate(entries):
        if "prev_hash" not in entry or "entry_hash" not in entry:
            return False, f"entry[{i}] missing chain fields (legacy or truncated)"
        if entry.get("prev_hash") != prev:
            return False, f"entry[{i}] prev_hash mismatch"
        expected = hash_entry(entry)
        if entry.get("entry_hash") != expected:
            return False, f"entry[{i}] entry_hash mismatch"
        prev = entry["entry_hash"]
    return True, "ok"


def _default_remote_sink(url: str, body: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def score_bucket(score: float, *, edges: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)) -> str:
    """Bucket a [0,1] score for drift logging — no raw biometric content.

    Phase I: collection only. Does **not** close fairness / skin-tone
    validation gaps; it only creates histogram-friendly fields for later
    analysis once real field data exists.
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "invalid"
    if s != s:  # NaN
        return "invalid"
    s = max(0.0, min(1.0, s))
    lo = 0.0
    for i, edge in enumerate(edges):
        if s < edge:
            return f"{lo:.1f}-{edge:.1f}"
        lo = edge
    return f"{lo:.1f}-1.0"


class AuditLog:
    def __init__(
        self,
        log_path: Path,
        *,
        remote_url: str | None = None,
        remote_sink: RemoteSink | None = None,
    ):
        self._path = log_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        env_url = (remote_url if remote_url is not None else os.getenv("DRIVEAUTH_AUDIT_REMOTE_URL", "")).strip()
        self._remote_url = env_url or None
        self._remote_sink = remote_sink or _default_remote_sink
        self._last_hash = self._tail_hash()

    def _tail_hash(self) -> str:
        if not self._path.exists():
            return GENESIS_HASH
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            if not lines:
                return GENESIS_HASH
            last = json.loads(lines[-1])
            return str(last.get("entry_hash") or GENESIS_HASH)
        except (json.JSONDecodeError, OSError, TypeError):
            return GENESIS_HASH

    def log_decision(
        self,
        *,
        event: str,
        driver_id: str,
        result: DriveAuthResult,
        transcript: str = "",
        session_id: str = "",
    ) -> dict:
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "session_id": session_id or result.session_id,
            "driver_id": driver_id or result.driver_id,
            "decision": result.decision.value,
            "tier": result.tier,
            "trust_score": round(result.trust_score, 4),
            "risk_score": round(result.risk_score, 4),
            "confidence": round(result.confidence_score, 4),
            # Phase I — bucketed scores for drift / fairness analysis later.
            # Not a claim that fairness is validated across demographics.
            "trust_bucket": score_bucket(result.trust_score),
            "risk_bucket": score_bucket(result.risk_score),
            "confidence_bucket": score_bucket(result.confidence_score),
            "fraud_state": result.fraud_state,
            "policy_rule": result.policy_rule,
            "step_up_method": result.step_up_method,
            "amount": result.amount,
            "currency": result.currency,
            "beneficiary": result.beneficiary,
            "action": result.action,
            "channel": result.channel,
            "modality_scores": result.modality_scores,
            "active_thresholds": result.active_thresholds,
            "ood_flags": result.ood_flags,
            "explanations": result.explanations,
            "is_payment": result.is_payment,
            "transcript": transcript[:120],
        }
        with self._lock:
            entry["prev_hash"] = self._last_hash
            entry["entry_hash"] = hash_entry(entry)
            line = json.dumps(entry) + "\n"
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
            self._last_hash = entry["entry_hash"]
            if self._remote_url:
                self._ship_remote(line.encode("utf-8"))
        return entry

    def _ship_remote(self, body: bytes) -> None:
        assert self._remote_url is not None
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "driveauth-edge-audit/1",
        }
        try:
            self._remote_sink(self._remote_url, body, headers)
        except Exception as exc:
            # Never log body (may contain PII metadata); type only.
            logger.warning(
                "AuditLog: remote sink failed (%s)",
                type(exc).__name__,
            )

    def read_entries(self, limit: int = 100) -> list[dict]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        out: list[dict] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def read_all_entries(self, *, strict: bool = False) -> list[dict]:
        """Load every audit line.

        Lenient (default): skip blank / unparseable lines — used by UI log
        viewers that should still show intact neighbors after a partial write.

        Strict: any non-blank line that fails ``json.loads`` raises
        ``ValueError`` so :meth:`verify_chain` can treat it as tamper evidence
        instead of a vacuous “that entry never existed” pass.
        """
        if not self._path.exists():
            return []
        out: list[dict] = []
        # Index counts non-blank lines (entries), matching verify_chain's entry[i].
        entry_idx = 0
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if strict:
                    raise ValueError(
                        f"entry[{entry_idx}] unparseable — file corrupted"
                    ) from exc
                # Lenient path: drop the bad line and keep scanning.
                entry_idx += 1
                continue
            entry_idx += 1
        return out

    def verify_chain(self) -> tuple[bool, str]:
        try:
            entries = self.read_all_entries(strict=True)
        except ValueError as exc:
            return False, str(exc)
        return verify_chain(entries)
