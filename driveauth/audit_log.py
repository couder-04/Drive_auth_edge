"""Append-only audit log for every authentication decision."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from driveauth.types import DriveAuthResult

logger = logging.getLogger("driveauth.audit")


class AuditLog:
    def __init__(self, log_path: Path):
        self._path = log_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log_decision(
        self,
        *,
        event: str,
        driver_id: str,
        result: DriveAuthResult,
        transcript: str = "",
        session_id: str = "",
    ) -> dict:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "session_id": session_id or result.session_id,
            "driver_id": driver_id or result.driver_id,
            "decision": result.decision.value,
            "tier": result.tier,
            "trust_score": round(result.trust_score, 4),
            "risk_score": round(result.risk_score, 4),
            "confidence": round(result.confidence_score, 4),
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
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

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
