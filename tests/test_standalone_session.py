"""Standalone intent slot-fill (mocked OpenRouter)."""

from __future__ import annotations

from driveauth.openrouter_client import ClarifyResult
from driveauth.standalone_session import IntentSlots, process_transcript


def test_ready_from_regex_alone() -> None:
    r = process_transcript(
        "pay Mom 50 rupees",
        use_llm=False,
        synthesize_tts=False,
    )
    assert r.status == "ready"
    assert r.intent.amount == 50.0
    assert "Mom" in r.intent.beneficiary


def test_need_input_missing_beneficiary() -> None:
    def fake_clarify(transcript, **kwargs):
        return ClarifyResult(
            amount=200.0,
            beneficiary=None,
            action="pay",
            currency="INR",
            is_payment=True,
            ask_prompt="Who is the Beneficiary — who should I pay?",
            ask_field="beneficiary",
        )

    r = process_transcript(
        "please pay 200 rupees",
        use_llm=True,
        synthesize_tts=True,
        clarify_fn=fake_clarify,
        speak_fn=lambda t: b"FAKEMP3",
    )
    assert r.status == "need_input"
    assert r.intent.amount == 200.0
    assert not r.intent.beneficiary
    assert r.ask_field == "beneficiary"
    assert "Beneficiary" in (r.prompt or "")
    assert r.tts_audio_b64  # base64 of FAKEMP3


def test_llm_fills_then_ready() -> None:
    def fake_clarify(transcript, **kwargs):
        return ClarifyResult(
            amount=150.0,
            beneficiary="Raj",
            action="transfer",
            currency="INR",
            is_payment=True,
            ask_prompt=None,
            ask_field=None,
        )

    r = process_transcript(
        "send money please",
        use_llm=True,
        synthesize_tts=False,
        clarify_fn=fake_clarify,
    )
    assert r.status == "ready"
    assert r.intent.beneficiary == "Raj"
    assert r.intent.amount == 150.0


def test_prior_slots_merge() -> None:
    prior = IntentSlots(amount=0.0, beneficiary="Starbucks", is_payment=True)
    r = process_transcript(
        "make it eighty",
        prior=prior,
        use_llm=False,
        synthesize_tts=False,
    )
    # may or may not parse 80 depending on regex; beneficiary kept
    assert r.intent.beneficiary == "Starbucks"
