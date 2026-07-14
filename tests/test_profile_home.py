"""Tests for the new home-learning path in ProfileStore (review fix #3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driveauth import config
from driveauth.profile_store import DriverProfile, ProfileStore, _migrate
from driveauth.types import RiskContext


@pytest.fixture
def store_dir(tmp_path: Path) -> Path:
    return tmp_path


def _new_store(driver_id: str, store_dir: Path) -> ProfileStore:
    return ProfileStore(path=store_dir / f"{driver_id}.json", driver_id=driver_id)


class TestMigration:
    def test_v1_record_forward_migrates_all_the_way_to_v3(self) -> None:
        # v1 records (from Phase 2a) don't have amount_m2 OR home_* fields.
        v1 = {"driver_id": "drv_1", "amount_mean": 500.0, "txn_count": 4, "schema_version": 1}
        migrated = _migrate(v1)
        assert migrated["schema_version"] == 3
        assert migrated["amount_m2"] == 0.0
        assert migrated["home_lat"] is None
        assert migrated["home_lon"] is None
        assert migrated["home_n"] == 0

    def test_v2_record_gains_home_fields(self) -> None:
        v2 = {
            "driver_id": "drv_2",
            "amount_mean": 500.0,
            "amount_m2": 10.0,
            "txn_count": 4,
            "ood_version": 1,
            "ood_last_refresh_at": 12345.0,
            "schema_version": 2,
        }
        migrated = _migrate(v2)
        assert migrated["schema_version"] == 3
        assert migrated["home_lat"] is None and migrated["home_lon"] is None
        # v2 fields untouched
        assert migrated["amount_mean"] == 500.0
        assert migrated["ood_version"] == 1

    def test_v3_record_passes_through(self) -> None:
        v3 = {
            "driver_id": "drv_3",
            "amount_mean": 500.0,
            "amount_m2": 10.0,
            "txn_count": 4,
            "ood_version": 1,
            "ood_last_refresh_at": 12345.0,
            "home_lat": 28.6,
            "home_lon": 77.2,
            "home_n": 5,
            "home_last_update_at": 999.0,
            "schema_version": 3,
        }
        assert _migrate(v3) == v3

    def test_old_profile_on_disk_can_be_loaded(self, store_dir: Path) -> None:
        """
        Round-trip the v2-on-disk case: an existing installation with older
        JSON files must open and immediately be usable, without a hand
        migration step. This is what protects existing users through the
        v2 -> v3 upgrade.
        """
        # Write a v2 file directly to disk, bypassing the store constructor.
        v2 = {
            "driver_id": "drv_disk",
            "created_at": 0.0,
            "last_txn_at": 0.0,
            "txn_count": 3,
            "amount_mean": 250.0,
            "amount_m2": 100.0,
            "ood_version": 1,
            "ood_last_refresh_at": 0.0,
            "schema_version": 2,
        }
        path = store_dir / "drv_disk.json"
        # The on-disk format wraps per-driver records under the driver_id key.
        path.write_text(json.dumps({"drv_disk": v2}))
        s = ProfileStore(path=path, driver_id="drv_disk")
        # Fields from v2 survive:
        assert s._p.amount_mean == 250.0
        assert s._p.txn_count == 3
        # New v3 fields default to fail-neutral values:
        assert s._p.home_lat is None
        assert s._p.home_n == 0


class TestRecordLocation:
    def test_first_fix_seeds_home(self, store_dir: Path) -> None:
        s = _new_store("drv_seed", store_dir)
        s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        assert s._p.home_lat == pytest.approx(28.6139)
        assert s._p.home_lon == pytest.approx(77.2090)
        assert s._p.home_n == 1

    def test_welford_running_mean_converges(self, store_dir: Path) -> None:
        s = _new_store("drv_welford", store_dir)
        # Push 10 fixes clustered around a centre with symmetric noise --
        # the running mean should be very close to the centre.
        centre_lat, centre_lon = 28.6139, 77.2090
        offsets = [0.001, -0.001, 0.002, -0.002, 0.0015, -0.0015, 0.001, -0.001, 0.0005, -0.0005]
        for o in offsets:
            s.record_location(centre_lat + o, centre_lon + o, gps_accuracy_m=20.0)
        assert s._p.home_n == 10
        assert abs(s._p.home_lat - centre_lat) < 1e-4
        assert abs(s._p.home_lon - centre_lon) < 1e-4

    def test_bad_accuracy_drops_the_fix(self, store_dir: Path) -> None:
        s = _new_store("drv_badgps", store_dir)
        # Seed one good fix so home is set to something we can compare against.
        s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        # Then push a wildly-inaccurate fix -- it should be ignored.
        s.record_location(19.0760, 72.8777, gps_accuracy_m=500.0)
        assert s._p.home_n == 1
        assert s._p.home_lat == pytest.approx(28.6139)

    def test_missing_lat_or_lon_is_a_noop(self, store_dir: Path) -> None:
        s = _new_store("drv_nogps", store_dir)
        s.record_location(None, None)
        s.record_location(28.6139, None)
        s.record_location(None, 77.2090)
        assert s._p.home_n == 0
        assert s._p.home_lat is None

    def test_persistence_across_store_reload(self, store_dir: Path) -> None:
        s1 = _new_store("drv_persist", store_dir)
        s1.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        s1.record_location(28.6145, 77.2095, gps_accuracy_m=20.0)
        # Reload from disk -- new instance, same directory.
        s2 = _new_store("drv_persist", store_dir)
        assert s2._p.home_n == 2
        assert s2._p.home_lat == pytest.approx(s1._p.home_lat)


class TestLocationContext:
    def test_below_min_samples_is_fail_neutral(self, store_dir: Path) -> None:
        """
        Until we've seen ``HOME_LEARN_MIN_SAMPLES`` accepted-auth fixes, home
        is treated as "not yet learned" and the derived features stay at
        their fail-neutral defaults. Otherwise a fresh install with one lucky
        fix could set home to a random parking lot forever.
        """
        s = _new_store("drv_bootstrap", store_dir)
        s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)  # 1 sample
        dist, in_zone = s.location_context(28.6139, 77.2090)
        assert dist == 0.0 and in_zone is True

    def test_after_min_samples_returns_real_distance(self, store_dir: Path) -> None:
        s = _new_store("drv_learned", store_dir)
        for _ in range(config.HOME_LEARN_MIN_SAMPLES):
            s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        # Same location -> distance ~0, in zone.
        dist, in_zone = s.location_context(28.6139, 77.2090)
        assert dist < 0.01 and in_zone is True
        # A far location -> distance large, out of zone.
        dist2, in_zone2 = s.location_context(19.0760, 72.8777)
        assert dist2 > 1000.0 and in_zone2 is False


class TestApplyToContext:
    def test_fills_geo_when_caller_did_not(self, store_dir: Path) -> None:
        s = _new_store("drv_fill", store_dir)
        for _ in range(config.HOME_LEARN_MIN_SAMPLES):
            s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        ctx = RiskContext(gps_lat=19.0760, gps_lon=72.8777)  # far away
        s.apply_to_context(ctx)
        assert ctx.dist_from_home_km > 1000.0
        assert ctx.in_trusted_zone is False

    def test_respects_caller_override_of_out_of_zone(self, store_dir: Path) -> None:
        """
        A caller (e.g. Nova) that explicitly set ``in_trusted_zone=False``
        via update_vehicle_context must have that respected, even if the
        profile would compute in_zone=True. Explicit override always wins.
        """
        s = _new_store("drv_override", store_dir)
        for _ in range(config.HOME_LEARN_MIN_SAMPLES):
            s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        ctx = RiskContext(
            gps_lat=28.6139, gps_lon=77.2090,   # would be in-zone
            in_trusted_zone=False,               # caller override
            dist_from_home_km=99.0,              # caller override
        )
        s.apply_to_context(ctx)
        assert ctx.in_trusted_zone is False
        assert ctx.dist_from_home_km == 99.0

    def test_no_gps_leaves_defaults(self, store_dir: Path) -> None:
        s = _new_store("drv_nogps", store_dir)
        for _ in range(config.HOME_LEARN_MIN_SAMPLES):
            s.record_location(28.6139, 77.2090, gps_accuracy_m=20.0)
        ctx = RiskContext()  # no GPS
        s.apply_to_context(ctx)
        # Defaults still zero / True -- the profile doesn't manufacture geo
        # signals when the caller hasn't provided a fix.
        assert ctx.dist_from_home_km == 0.0
        assert ctx.in_trusted_zone is True


class TestSetHome:
    def test_explicit_pin_enables_distance_immediately(self, store_dir: Path) -> None:
        s = _new_store("drv_pin", store_dir)
        s.set_home(12.9716, 77.5946)
        lat, lon, n = s.home_coords()
        assert lat == pytest.approx(12.9716)
        assert lon == pytest.approx(77.5946)
        assert n >= config.HOME_LEARN_MIN_SAMPLES
        dist, in_zone = s.location_context(12.9716, 77.5946)
        assert dist < 0.05 and in_zone is True
        dist2, in_zone2 = s.location_context(13.0827, 80.2707)  # Chennai-ish
        assert dist2 > 200.0 and in_zone2 is False
