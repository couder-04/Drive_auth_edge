"""
Lightweight transaction-intent parser (fix #1).

Extracts (amount, beneficiary, action, currency) from a spoken/typed command so
the gate can tier and risk-score the ACTUAL transaction instead of defaulting
to zero. Case-insensitive — STT rarely preserves Title Case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_AMOUNT_RE = re.compile(
    r"(?:(?:rs|inr|₹|rupees?|dollars?|usd|\$)\s*)?"
    r"(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?:rs|inr|₹|rupees?|dollars?|usd|k))?",
    re.IGNORECASE,
)
_MULTIPLIER = {"k": 1_000, "thousand": 1_000, "lakh": 100_000, "million": 1_000_000}

_ACTION_RE = re.compile(
    r"\b(transfer|send money|send|pay|purchase|buy|order|checkout|recharge|top.?up)\b",
    re.IGNORECASE,
)
_ACTION_CANON = {
    "transfer": "transfer",
    "send money": "transfer",
    "send": "transfer",
    "pay": "pay",
    "purchase": "pay",
    "buy": "pay",
    "order": "pay",
    "checkout": "pay",
    "recharge": "recharge",
    "topup": "recharge",
    "top up": "recharge",
    "top-up": "recharge",
}

# "to/for <name>" or "pay/send/transfer <name> <amount>"
# Names are letters only (optionally multi-word); case-insensitive.
_BENEFICIARY_RE = re.compile(
    r"\b(?:to|for|pay|send|transfer)\s+([A-Za-z][A-Za-z]*(?:\s+[A-Za-z][A-Za-z]*)?)\b",
    re.IGNORECASE,
)

_CURRENCY_RE = re.compile(r"\b(inr|rs|rupees?|₹|usd|dollars?|\$)\b", re.IGNORECASE)
_CURRENCY_CANON = {
    "inr": "INR",
    "rs": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "₹": "INR",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "$": "USD",
}

_PAYMENT_RE = re.compile(
    r"\b(order|buy|purchase|pay|send money|transfer|checkout|coffee|burger"
    r"|pizza|food|latte|cappuccino|add to cart|top.?up|recharge)\b",
    re.IGNORECASE,
)

_STOP_NAMES = set(_ACTION_CANON) | {
    "money",
    "rupees",
    "rupee",
    "dollars",
    "dollar",
    "inr",
    "usd",
    "rs",
}


@dataclass
class TransactionIntent:
    amount: float = 0.0
    beneficiary: str = ""
    action: str = ""
    currency: str = "INR"
    channel: str = "voice"
    raw: str = ""
    is_payment: bool = False


def is_payment_utterance(text: str) -> bool:
    """True when the utterance looks like a payment / transfer command."""
    return bool(_PAYMENT_RE.search(text or ""))


def parse_transaction_intent(text: str, *, channel: str = "voice") -> TransactionIntent:
    cleaned = re.sub(r"[^\w\s.$₹]", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    intent = TransactionIntent(raw=text or "", channel=channel)
    intent.is_payment = is_payment_utterance(cleaned)

    m = _ACTION_RE.search(cleaned)
    if m:
        raw_act = m.group(1).lower()
        key = raw_act.replace("-", "").replace(" ", "")
        intent.action = _ACTION_CANON.get(raw_act, _ACTION_CANON.get(key, "pay"))

    cm = _CURRENCY_RE.search(cleaned)
    if cm:
        intent.currency = _CURRENCY_CANON.get(cm.group(1).lower(), "INR")

    am = _AMOUNT_RE.search(cleaned)
    if am:
        try:
            val = float(am.group(1).replace(",", ""))
            matched = am.group(0).lower().rstrip()
            tail = cleaned[am.end() : am.end() + 12].strip().lower()
            if re.search(r"\dk\b", matched):
                val *= 1_000
            else:
                for word, mult in _MULTIPLIER.items():
                    if tail.startswith(word):
                        val *= mult
                        break
            intent.amount = val
        except ValueError:
            intent.amount = 0.0

    # Prefer "to/for <name>"; fall back to "pay/send/transfer <name>".
    for bm in _BENEFICIARY_RE.finditer(cleaned):
        cand = bm.group(1).strip()
        if cand.lower() in _STOP_NAMES:
            continue
        # Skip if the capture is purely numeric-adjacent action residue.
        if cand.isdigit():
            continue
        intent.beneficiary = cand.title() if cand.islower() or cand.isupper() else cand
        break

    return intent
