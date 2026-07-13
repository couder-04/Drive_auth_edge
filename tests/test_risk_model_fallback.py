"""Tests for the RiskModel review fixes (#8 strict load, #9 reasons)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driveauth.risk_model import RiskModel, _DEFAULT_FALLBACK_WEIGHTS
from driveauth.types import RiskContext


class TestStrictLoad:
    def test_missing_onnx_is_not_an_error(self, tmp_path: Path) -> None:
        # Fresh install: no risk_gbt.onnx at all. Both strict and non-strict
        # must succeed with additive fallback -- there's nothing corrupt to
        # be strict about.
        m1 = RiskModel.load(str(tmp_path), strict=True)
        m2 = RiskModel.load(str(tmp_path), strict=False)
        assert m1._session is None
        assert m2._session is None

    def test_corrupt_onnx_raises_in_strict_mode(self, tmp_path: Path) -> None:
        # Write garbage into risk_gbt.onnx. Strict load must raise so a bad
        # checkpoint or ORT mismatch is impossible to miss (fix #8). Non-
        # strict logs a warning and falls back -- keeping the pre-fix
        # behaviour available as an opt-out.
        (tmp_path / "risk_gbt.onnx").write_bytes(b"not-actually-onnx")
        with pytest.raises(RuntimeError):
            RiskModel.load(str(tmp_path), strict=True)
        # Non-strict succeeds with additive fallback:
        m = RiskModel.load(str(tmp_path), strict=False)
        assert m._session is None


class TestFallbackWeightsSidecar:
    def test_no_sidecar_uses_default_weights(self, tmp_path: Path) -> None:
        m = RiskModel.load(str(tmp_path), strict=False)
        # Missing sidecar -> the hardcoded defaults are used.
        assert m._fallback_weights == _DEFAULT_FALLBACK_WEIGHTS

    def test_sidecar_weights_override_defaults(self, tmp_path: Path) -> None:
        custom = {
            "amount_z_scaled": 0.5,
            "behavior_anomaly": 0.3,
            "dist_from_home": 0.2,
        }
        (tmp_path / "risk_gbt_fallback_weights.json").write_text(
            json.dumps({"weights": custom})
        )
        m = RiskModel.load(str(tmp_path), strict=False)
        assert m._fallback_weights == custom

    def test_flat_sidecar_shape_also_accepted(self, tmp_path: Path) -> None:
        # Tolerate the simpler {name: weight} shape too (not wrapped in
        # {"weights": ...}) since it's a small correctness win to be
        # permissive on the read side.
        flat = {"behavior_anomaly": 0.7, "amount_norm": 0.3}
        (tmp_path / "risk_gbt_fallback_weights.json").write_text(json.dumps(flat))
        m = RiskModel.load(str(tmp_path), strict=False)
        assert m._fallback_weights == flat

    def test_corrupt_sidecar_falls_back_to_defaults(self, tmp_path: Path) -> None:
        # A malformed sidecar shouldn't refuse to boot -- log + defaults.
        (tmp_path / "risk_gbt_fallback_weights.json").write_text("not json at all")
        m = RiskModel.load(str(tmp_path), strict=False)
        assert m._fallback_weights == _DEFAULT_FALLBACK_WEIGHTS

    def test_dynamic_weights_actually_shape_the_score(self, tmp_path: Path) -> None:
        """
        End-to-end: two RiskModels with the same additive fallback logic but
        different sidecar weights should score the same context differently.
        This is the mechanism that lets a re-trained model's importances
        propagate to the fallback path in a deployment.
        """
        # Model A: all weight on behavior_anomaly.
        (tmp_path / "risk_gbt_fallback_weights.json").write_text(
            json.dumps({"weights": {"behavior_anomaly": 1.0}})
        )
        a = RiskModel.load(str(tmp_path), strict=False)
        # Model B: all weight on out_of_zone.
        (tmp_path / "risk_gbt_fallback_weights.json").write_text(
            json.dumps({"weights": {"out_of_zone": 1.0}})
        )
        b = RiskModel.load(str(tmp_path), strict=False)

        # A ctx where behavior is bad but zone is fine:
        ctx = RiskContext(
            amount=100.0, amount_mean=100.0, amount_std=50.0,
            behavioral_score=0.0,     # -> behavior_anomaly = 1.0
            in_trusted_zone=True,     # -> out_of_zone = 0.0
        )
        risk_a, _ = a.score(ctx)
        risk_b, _ = b.score(ctx)
        assert risk_a > 0.9
        assert risk_b < 0.1


class TestImportanceAwareReasons:
    def test_no_importances_emits_all_threshold_reasons(self, tmp_path: Path) -> None:
        # No sidecar -> importance filter disabled -> pre-fix behaviour.
        m = RiskModel.load(str(tmp_path), strict=False)
        ctx = RiskContext(
            amount=100_000.0, amount_mean=100.0, amount_std=50.0,   # amount_z huge
            beneficiary_known=False,                                   # novel
            in_trusted_zone=False,                                     # out of zone
            behavioral_score=0.0,                                      # anomaly
        )
        _, reasons = m.score(ctx)
        # All the classic reasons should be present.
        for expected in (
            "amount_far_above_usual",
            "large_absolute_amount",
            "first_time_beneficiary",
            "unfamiliar_location",
            "driving_style_anomaly",
        ):
            assert expected in reasons

    def test_low_importance_features_get_filtered_out(self, tmp_path: Path) -> None:
        """
        When the deployed model attributes almost zero gain to ``night``, we
        stop emitting ``unusual_hour`` even at 4am -- the reason would just
        confuse a downstream analyst reading the audit log, because that
        feature isn't actually affecting the risk score in this deployment.
        """
        # Fake meta with night ≈ 0 gain, behaviour ≈ everything else.
        (tmp_path / "risk_gbt.json").write_text(json.dumps({
            "feature_importances_gain": {
                "night": 0.0,
                "behavior_anomaly": 1000.0,
                "beneficiary_novel": 500.0,
            }
        }))
        m = RiskModel.load(str(tmp_path), strict=False)
        ctx = RiskContext(
            amount=100.0, amount_mean=100.0, amount_std=50.0,
            time_hour=3,                # unusual_hour would fire
            beneficiary_known=False,    # first_time_beneficiary should still fire (high share)
        )
        _, reasons = m.score(ctx)
        assert "unusual_hour" not in reasons
        assert "first_time_beneficiary" in reasons

    def test_all_zero_importances_falls_back_to_threshold_only(self, tmp_path: Path) -> None:
        # If the meta report is present but empty of gain data, don't filter.
        (tmp_path / "risk_gbt.json").write_text(json.dumps({"feature_importances_gain": {}}))
        m = RiskModel.load(str(tmp_path), strict=False)
        ctx = RiskContext(
            amount=100.0, amount_mean=100.0, amount_std=50.0,
            time_hour=3,
        )
        _, reasons = m.score(ctx)
        assert "unusual_hour" in reasons
