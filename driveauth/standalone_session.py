"""Standalone pay session: STT transcript → intent slots → TTS re-prompt."""

from __future__ import annotations

import base64
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from driveauth.intent import TransactionIntent, parse_transaction_intent
from driveauth.openrouter_client import (
    ClarifyResult,
    OpenRouterError,
    clarify_payment,
    speak,
    transcribe,
)

logger = logging.getLogger("driveauth.standalone")


@dataclass
class IntentSlots:
    amount: float = 0.0
    beneficiary: str = ""
    action: str = "pay"
    currency: str = "INR"
    transcript: str = ""
    is_payment: bool = False

    def missing(self) -> list[str]:
        miss: list[str] = []
        if self.is_payment or self.amount > 0 or self.beneficiary:
            if not self.amount or self.amount <= 0:
                miss.append("amount")
            if not (self.beneficiary or "").strip():
                miss.append("beneficiary")
        return miss

    def ready(self) -> bool:
        return bool(self.is_payment or self.amount > 0) and not self.missing()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionResult:
    status: str  # ready | need_input | not_payment | error
    intent: IntentSlots = field(default_factory=IntentSlots)
    prompt: str | None = None
    ask_field: str | None = None  # column to clarify: amount|beneficiary|action|currency
    tts_audio_b64: str | None = None
    tts_mime: str = "audio/mpeg"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "intent": self.intent.as_dict(),
            "prompt": self.prompt,
            "ask_field": self.ask_field,
            "tts_audio_b64": self.tts_audio_b64,
            "tts_mime": self.tts_mime,
            "error": self.error,
            "missing": self.intent.missing(),
        }


def _merge_regex(intent: TransactionIntent) -> IntentSlots:
    return IntentSlots(
        amount=float(intent.amount or 0.0),
        beneficiary=(intent.beneficiary or "").strip(),
        action=(intent.action or "pay") or "pay",
        currency=(intent.currency or "INR") or "INR",
        transcript=intent.raw or "",
        is_payment=bool(intent.is_payment),
    )


def _apply_clarify(slots: IntentSlots, clr: ClarifyResult) -> IntentSlots:
    if clr.is_payment is False:
        slots.is_payment = False
    if clr.amount is not None and clr.amount > 0:
        slots.amount = float(clr.amount)
    if clr.beneficiary is not None:
        # Allow clearing a bad regex capture when LLM returns "".
        slots.beneficiary = clr.beneficiary.strip()
    if clr.action:
        slots.action = clr.action
    if clr.currency:
        slots.currency = clr.currency
    if clr.is_payment is True or slots.amount > 0 or slots.beneficiary:
        slots.is_payment = True
    return slots


def _default_prompt(missing: list[str], ask_field: str | None = None) -> tuple[str, str]:
    """Return (ask_prompt, ask_field) naming the dashboard column for TTS."""
    field = ask_field
    if not field:
        if "amount" in missing:
            field = "amount"
        elif "beneficiary" in missing:
            field = "beneficiary"
        else:
            field = "amount"
    prompts = {
        "amount": "What Amount should I pay?",
        "beneficiary": "Who is the Beneficiary — who should I pay?",
        "action": "Should the Action be pay, transfer, or recharge?",
        "currency": "Which Currency — Indian rupees or US dollars?",
    }
    return prompts.get(field, "Please clarify the payment Amount and Beneficiary."), field


def process_transcript(
    transcript: str,
    *,
    prior: IntentSlots | None = None,
    use_llm: bool = True,
    synthesize_tts: bool = True,
    clarify_fn: Callable[..., ClarifyResult] | None = None,
    speak_fn: Callable[[str], bytes] | None = None,
) -> SessionResult:
    """Regex intent first; LLM fill + column-named TTS when ambiguous/missing."""
    text = (transcript or "").strip()
    if not text:
        return SessionResult(status="error", error="empty transcript")

    slots = _merge_regex(parse_transaction_intent(text, channel="voice"))
    prior_transcript = ""
    if prior is not None:
        if prior.amount > 0 and not slots.amount:
            slots.amount = prior.amount
        if prior.beneficiary and not slots.beneficiary:
            slots.beneficiary = prior.beneficiary
        if prior.action and (not slots.action or slots.action == "pay"):
            slots.action = prior.action
        if prior.currency:
            slots.currency = prior.currency
        if prior.is_payment:
            slots.is_payment = True
        prior_transcript = prior.transcript or ""
        if prior.transcript and prior.transcript != slots.transcript:
            slots.transcript = f"{prior.transcript} | {slots.transcript}"

    look_like_payment = bool(
        slots.is_payment or slots.amount > 0 or slots.beneficiary
    )
    if not look_like_payment and not use_llm:
        return SessionResult(status="not_payment", intent=slots)

    ask: str | None = None
    ask_field: str | None = None

    # When LLM is enabled, always run it so word-numbers / garbled slots /
    # ambiguity get corrected; ask_field names the dashboard column for TTS.
    if use_llm:
        fn = clarify_fn or clarify_payment
        try:
            try:
                clr = fn(
                    text,
                    amount=slots.amount,
                    beneficiary=slots.beneficiary,
                    action=slots.action,
                    currency=slots.currency,
                    prior_transcript=prior_transcript,
                )
            except TypeError:
                # Test doubles / older stubs may not accept prior_transcript=
                clr = fn(
                    text,
                    amount=slots.amount,
                    beneficiary=slots.beneficiary,
                    action=slots.action,
                    currency=slots.currency,
                )
            slots = _apply_clarify(slots, clr)
            ask = clr.ask_prompt
            ask_field = getattr(clr, "ask_field", None)
            if clr.is_payment is False and not slots.amount and not slots.beneficiary:
                return SessionResult(status="not_payment", intent=slots)
        except OpenRouterError as exc:
            logger.warning("LLM clarify failed: %s", exc)
        except Exception as exc:  # noqa: BLE001 — fall back to regex-only
            logger.warning("LLM clarify unexpected: %s", exc)

    missing = slots.missing()
    if not missing and slots.ready() and not ask:
        return SessionResult(status="ready", intent=slots, ask_field=None)

    if not slots.is_payment and not missing and not ask:
        return SessionResult(status="not_payment", intent=slots)

    if ask:
        prompt = ask.strip()
        if not ask_field:
            _, ask_field = _default_prompt(missing, None)
    else:
        prompt, ask_field = _default_prompt(missing, ask_field)

    tts_b64 = None
    if synthesize_tts:
        sfn = speak_fn or speak
        try:
            audio = sfn(prompt)
            tts_b64 = base64.b64encode(audio).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            logger.warning("TTS failed: %s", exc)

    return SessionResult(
        status="need_input",
        intent=slots,
        prompt=prompt,
        ask_field=ask_field,
        tts_audio_b64=tts_b64,
    )


def process_audio(
    audio_bytes: bytes,
    *,
    audio_format: str = "wav",
    prior: IntentSlots | None = None,
    use_llm: bool = True,
    synthesize_tts: bool = True,
    transcribe_fn: Callable[..., str] | None = None,
    **kwargs: Any,
) -> SessionResult:
    """STT then :func:`process_transcript`."""
    tfn = transcribe_fn or transcribe
    try:
        text = tfn(audio_bytes, audio_format=audio_format)
    except OpenRouterError as exc:
        return SessionResult(status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return SessionResult(status="error", error=f"STT failed: {exc}")
    return process_transcript(
        text,
        prior=prior,
        use_llm=use_llm,
        synthesize_tts=synthesize_tts,
        **kwargs,
    )
