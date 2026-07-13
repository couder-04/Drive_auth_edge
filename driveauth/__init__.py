"""
DriveAuth Edge — Trust/Risk-separated vehicle biometric authorization.

Public API: :class:`DriveAuth` in :mod:`driveauth.api`.
"""

from driveauth.api import DriveAuth
from driveauth.escalation import EscalationPlan, EscalationPolicy
from driveauth.intent import (
    TransactionIntent,
    is_payment_utterance,
    parse_transaction_intent,
)
from driveauth.profile_store import DriverProfile, ProfileStore
from driveauth.types import (
    Decision,
    DriveAuthResult,
    ModalityResult,
    QualityFlags,
    RiskContext,
)

__version__ = "0.2.0"

__all__ = [
    "DriveAuth",
    "DriveAuthResult",
    "Decision",
    "ModalityResult",
    "QualityFlags",
    "RiskContext",
    "EscalationPolicy",
    "EscalationPlan",
    "ProfileStore",
    "DriverProfile",
    "TransactionIntent",
    "parse_transaction_intent",
    "is_payment_utterance",
    "__version__",
]
