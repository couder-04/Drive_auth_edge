"""Tests for driveauth/geo.py (review fix #3)."""

from __future__ import annotations

import math


from driveauth import geo


class TestHaversine:
    def test_identical_points_return_zero(self) -> None:
        assert geo.haversine_km(28.6139, 77.2090, 28.6139, 77.2090) == 0.0

    def test_known_distance_delhi_to_mumbai(self) -> None:
        # Delhi (28.6139, 77.2090) -> Mumbai (19.0760, 72.8777) is ~1150km
        # by great-circle. Any half-decent implementation lands within 5 km.
        d = geo.haversine_km(28.6139, 77.2090, 19.0760, 72.8777)
        assert 1145.0 <= d <= 1160.0

    def test_short_distance_stays_small(self) -> None:
        # Two points ~1km apart -- confirms the small-angle math is sensible.
        # 1 degree of latitude ≈ 111 km, so 0.009 deg ≈ ~1 km.
        d = geo.haversine_km(28.6139, 77.2090, 28.6229, 77.2090)
        assert 0.9 <= d <= 1.1

    def test_symmetry(self) -> None:
        d1 = geo.haversine_km(1.0, 2.0, 3.0, 4.0)
        d2 = geo.haversine_km(3.0, 4.0, 1.0, 2.0)
        assert math.isclose(d1, d2, rel_tol=1e-9)


class TestLocationContext:
    def test_no_gps_is_fail_neutral(self) -> None:
        dist, in_zone = geo.location_context(
            gps_lat=None, gps_lon=None,
            home_lat=28.6, home_lon=77.2,
            trusted_zone_radius_km=5.0,
        )
        assert dist == 0.0 and in_zone is True

    def test_no_home_is_fail_neutral(self) -> None:
        dist, in_zone = geo.location_context(
            gps_lat=28.6, gps_lon=77.2,
            home_lat=None, home_lon=None,
            trusted_zone_radius_km=5.0,
        )
        assert dist == 0.0 and in_zone is True

    def test_in_zone_when_close_to_home(self) -> None:
        # ~500m away -- comfortably inside a 5km trusted zone.
        dist, in_zone = geo.location_context(
            gps_lat=28.6089, gps_lon=77.2090,
            home_lat=28.6139, home_lon=77.2090,
            trusted_zone_radius_km=5.0,
        )
        assert dist < 1.0 and in_zone is True

    def test_out_of_zone_when_far(self) -> None:
        dist, in_zone = geo.location_context(
            gps_lat=19.0760, gps_lon=72.8777,   # Mumbai
            home_lat=28.6139, home_lon=77.2090,  # Delhi
            trusted_zone_radius_km=5.0,
        )
        assert dist > 1000.0 and in_zone is False

    def test_zero_radius_only_matches_exact(self) -> None:
        # A radius of exactly 0.0 means "identical fix only". Anything else
        # should be out-of-zone.
        dist, in_zone = geo.location_context(
            gps_lat=28.6139, gps_lon=77.2090,
            home_lat=28.6139, home_lon=77.2090,
            trusted_zone_radius_km=0.0,
        )
        assert dist == 0.0 and in_zone is True

    def test_negative_radius_treated_as_zero(self) -> None:
        # We don't want a config typo (negative radius) to make everything
        # in-zone or to blow up; it's clamped to zero.
        dist, in_zone = geo.location_context(
            gps_lat=28.62, gps_lon=77.21,
            home_lat=28.6139, home_lon=77.2090,
            trusted_zone_radius_km=-1.0,
        )
        assert in_zone is False


class TestValidGpsAccuracy:
    def test_unknown_accuracy_is_trusted(self) -> None:
        # We treat "unknown" as trustworthy -- policy layer can override.
        assert geo.valid_gps_accuracy(None, max_m=50.0) is True

    def test_good_accuracy_passes(self) -> None:
        assert geo.valid_gps_accuracy(30.0, max_m=100.0) is True

    def test_bad_accuracy_rejected(self) -> None:
        assert geo.valid_gps_accuracy(500.0, max_m=100.0) is False

    def test_borderline_accuracy_accepted(self) -> None:
        # The check is ``<=``, so exactly at the threshold is still accepted.
        assert geo.valid_gps_accuracy(100.0, max_m=100.0) is True

    def test_garbage_input_rejected(self) -> None:
        # A non-numeric junk value shouldn't propagate an exception.
        assert geo.valid_gps_accuracy("not-a-number", max_m=100.0) is False  # type: ignore[arg-type]
