"""OpenRouter STT / TTS / LLM helpers for the standalone pay flow."""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from driveauth.secrets import get_secret, openrouter_configured

logger = logging.getLogger("driveauth.openrouter")

DEFAULT_BASE = "https://openrouter.ai/api/v1"


class OpenRouterError(RuntimeError):
    pass


@dataclass
class ClarifyResult:
    amount: float | None = None
    beneficiary: str | None = None
    action: str | None = None
    currency: str | None = None
    is_payment: bool | None = None
    ask_prompt: str | None = None
    ask_field: str | None = None  # amount|beneficiary|action|currency
    raw: dict[str, Any] | None = None


# Robust intent extractor system prompt (OpenRouter chat completions).
INTENT_SYSTEM_PROMPT = """\
You are DriveAuth Edge's in-vehicle payment INTENT EXTRACTOR.

The user spoke a command. You receive:
  • transcript — raw STT text (may have ASR errors, missing punctuation, word numbers)
  • known — slots already filled from prior turns or a fast regex pass (may be wrong)

Your job: identify whether this is a PAYMENT intent and fill the dashboard columns
below. If anything required is missing or ambiguous, ask ONE spoken follow-up that
names the exact column the driver must clarify.

══════════════════════════════════════════════════════════════════
COLUMNS (dashboard fields)
══════════════════════════════════════════════════════════════════
1) amount        REQUIRED for payment
   - Positive money amount as a NUMBER (no currency symbol).
   - Convert spoken/word numbers: "fifty"→50, "two hundred"→200, "1.5k"→1500,
     "three thousand"→3000, "lakh"→100000.
   - If several numbers appear, pick the one that is the payment amount
     (not a phone number, PIN, or time). If unclear → ask_field="amount".

2) beneficiary   REQUIRED for payment
   - Person, merchant, or entity to pay / transfer to.
   - Normalize to Title Case for display (e.g. "mom"→"Mom", "starbucks"→"Starbucks").
   - Do NOT put amounts, currencies, or action verbs here.
   - If the name is unclear, two candidates fit, or STT garbled it → ask_field="beneficiary".

3) action        OPTIONAL (default "pay" when payment is clear)
   - One of: pay | transfer | recharge
   - Map synonyms: send/send money→transfer; buy/purchase/order→pay; top up/topup→recharge.
   - Only ask when the verb is genuinely unclear between pay vs transfer vs recharge.

4) currency      OPTIONAL (default "INR" for Indian-context speech)
   - INR or USD only. Map: rupees/rs/₹→INR; dollars/$→USD.
   - Ask only if both currencies are plausible and unspecified.

══════════════════════════════════════════════════════════════════
WHEN IT IS / ISN'T A PAYMENT
══════════════════════════════════════════════════════════════════
is_payment=true when the user wants to move money (pay, transfer, send money,
recharge, buy with an implied checkout, etc.).

is_payment=false for navigation, music, AC, "open …", jokes, or unrelated chat.
If not a payment: set amount/beneficiary/action/currency to null, ask_prompt null,
ask_field null, is_payment false.

══════════════════════════════════════════════════════════════════
FILLING RULES
══════════════════════════════════════════════════════════════════
• Prefer definite values from the NEW transcript; use "known" only to keep
  already-confirmed slots across follow-up turns.
• Never invent a beneficiary or amount that is not supported by the speech.
• If regex "known" looks wrong (e.g. beneficiary="Mom Fifty" absorbing a number),
  CORRECT it: amount=50, beneficiary="Mom".
• Ready to authorize only when amount>0 AND beneficiary is a clear non-empty name.
• On success: ask_prompt=null, ask_field=null.

══════════════════════════════════════════════════════════════════
AMBIGUITY → TTS FOLLOW-UP (exactly one column)
══════════════════════════════════════════════════════════════════
If amount or beneficiary is missing OR ambiguous, you MUST set:
  • ask_field  — exactly one of: "amount" | "beneficiary" | "action" | "currency"
  • ask_prompt — ONE short sentence suitable for TTS (≤20 words), that EXPLICITLY
    names that column so the driver knows what to answer.

Good ask_prompt examples:
  • ask_field=amount      → "What Amount should I pay?"
  • ask_field=beneficiary → "Who is the Beneficiary — who should I pay?"
  • ask_field=action      → "Should the Action be pay, transfer, or recharge?"
  • ask_field=currency    → "Which Currency — Indian rupees or US dollars?"

Ask priority if several are missing: amount → beneficiary → action → currency.
Ask about only ONE field per turn. Do not combine two questions.

══════════════════════════════════════════════════════════════════
OUTPUT — return ONLY a JSON object (no markdown, no prose)
══════════════════════════════════════════════════════════════════
{
  "is_payment": true|false,
  "amount": <number|null>,
  "beneficiary": <string|null>,
  "action": "pay"|"transfer"|"recharge"|null,
  "currency": "INR"|"USD"|null,
  "ask_field": "amount"|"beneficiary"|"action"|"currency"|null,
  "ask_prompt": <string|null>
}
"""


def _base_url() -> str:
    return get_secret("OPENROUTER_BASE_URL", DEFAULT_BASE).rstrip("/")


def _api_key() -> str:
    key = get_secret("OPENROUTER_API_KEY").strip()
    if not key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY missing — copy secrets.env.example → secrets.env"
        )
    return key


def _headers(*, content_type: str = "application/json") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": content_type,
        "HTTP-Referer": "https://github.com/driveauth-edge",
        "X-Title": "DriveAuth Edge Standalone",
    }


def _request(
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 90.0,
) -> tuple[int, bytes, str]:
    url = f"{_base_url()}{path}"
    req = urllib.request.Request(
        url,
        data=body,
        headers=_headers(content_type=content_type),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            return resp.getcode(), resp.read(), ctype
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenRouterError(f"OpenRouter network error: {exc}") from exc


def transcribe(
    audio_bytes: bytes,
    *,
    audio_format: str = "wav",
    language: str = "en",
) -> str:
    """STT via ``POST /audio/transcriptions``."""
    if not audio_bytes:
        raise OpenRouterError("empty audio")
    model = get_secret("OPENROUTER_STT_MODEL", "openai/whisper-1")
    payload = {
        "model": model,
        "language": language,
        "input_audio": {
            "data": base64.b64encode(audio_bytes).decode("ascii"),
            "format": audio_format.lstrip("."),
        },
    }
    _code, raw, _ctype = _request(
        "POST",
        "/audio/transcriptions",
        body=json.dumps(payload).encode("utf-8"),
    )
    data = json.loads(raw.decode("utf-8"))
    text = (data.get("text") or "").strip()
    if not text:
        raise OpenRouterError(f"empty transcription: {data!r}")
    return text


def speak(text: str, *, response_format: str = "mp3") -> bytes:
    """TTS via ``POST /audio/speech`` — returns raw audio bytes."""
    text = (text or "").strip()
    if not text:
        raise OpenRouterError("empty TTS text")
    model = get_secret("OPENROUTER_TTS_MODEL", "openai/gpt-4o-mini-tts")
    voice = get_secret("OPENROUTER_TTS_VOICE", "alloy")
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": response_format,
    }
    _code, raw, _ctype = _request(
        "POST",
        "/audio/speech",
        body=json.dumps(payload).encode("utf-8"),
    )
    if not raw:
        raise OpenRouterError("empty TTS audio")
    return raw


_ALLOWED_ACTIONS = frozenset({"pay", "transfer", "recharge"})
_ALLOWED_CURRENCIES = frozenset({"INR", "USD"})
_ALLOWED_ASK_FIELDS = frozenset({"amount", "beneficiary", "action", "currency"})


def clarify_payment(
    transcript: str,
    *,
    amount: float = 0.0,
    beneficiary: str = "",
    action: str = "",
    currency: str = "INR",
    prior_transcript: str = "",
) -> ClarifyResult:
    """LLM slot-fill / one column-specific TTS clarification for a payment utterance."""
    model = get_secret("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini")
    user = json.dumps(
        {
            "transcript": transcript,
            "prior_transcript": prior_transcript or None,
            "known": {
                "amount": amount if amount and amount > 0 else None,
                "beneficiary": beneficiary or None,
                "action": action or None,
                "currency": currency or None,
            },
            "columns": ["amount", "beneficiary", "action", "currency"],
            "required_for_ready": ["amount", "beneficiary"],
        }
    )
    payload = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    _code, raw, _ctype = _request(
        "POST",
        "/chat/completions",
        body=json.dumps(payload).encode("utf-8"),
    )
    data = json.loads(raw.decode("utf-8"))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"bad chat response: {data!r}") from exc
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    if isinstance(content, str):
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        parsed = json.loads(content)
    else:
        parsed = content
    if not isinstance(parsed, dict):
        raise OpenRouterError(f"LLM did not return JSON object: {parsed!r}")

    amount_out: float | None = None
    if parsed.get("amount") is not None:
        try:
            amount_out = float(parsed["amount"])
            if amount_out <= 0:
                amount_out = None
        except (TypeError, ValueError):
            amount_out = None

    action_out = None
    if parsed.get("action"):
        a = str(parsed["action"]).strip().lower()
        action_out = a if a in _ALLOWED_ACTIONS else None

    currency_out = None
    if parsed.get("currency"):
        c = str(parsed["currency"]).strip().upper()
        currency_out = c if c in _ALLOWED_CURRENCIES else None

    ask_field = None
    if parsed.get("ask_field"):
        f = str(parsed["ask_field"]).strip().lower()
        ask_field = f if f in _ALLOWED_ASK_FIELDS else None

    ask_prompt = (
        str(parsed["ask_prompt"]).strip() if parsed.get("ask_prompt") else None
    ) or None

    # If model asked without naming a field, infer from missing required slots.
    if ask_prompt and not ask_field:
        if amount_out is None and not (amount and amount > 0):
            ask_field = "amount"
        elif not (parsed.get("beneficiary") or beneficiary):
            ask_field = "beneficiary"

    is_pay = parsed.get("is_payment")
    if is_pay is None:
        is_pay = bool(amount_out or parsed.get("beneficiary") or ask_prompt)

    return ClarifyResult(
        amount=amount_out,
        beneficiary=(
            str(parsed["beneficiary"]).strip() if parsed.get("beneficiary") else None
        ),
        action=action_out,
        currency=currency_out,
        is_payment=bool(is_pay),
        ask_prompt=ask_prompt,
        ask_field=ask_field,
        raw=parsed,
    )


def available() -> bool:
    return openrouter_configured()
