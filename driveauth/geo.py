"""
Geographic helpers for the risk pipeline (review fix #3).

Two features consumed by ``RiskModel`` -- ``dist_from_home`` and ``out_of_zone``
-- had no runtime producer: they were declared on ``RiskContext`` and read by
``_features()``, but nothing in the codebase ever computed them from live GPS.
So in production they were permanently at their dataclass defaults
(``dist_from_home_km=0.0``, ``in_trusted_zone=True``), meaning two of the top
features from the trained model went dead at inference.

This module supplies the producer: a pure Haversine distance and a
zone-membership check. It has no state -- home learning lives on
:class:`driveauth.profile_store.DriverProfile` which uses these helpers.

Design constraints:
  * Fully offline: no external service, no lookup table.
  * Fail-neutral on missing inputs: unknown GPS or unknown home returns
    ``(0.0, True)`` (i.e. "assume familiar"). Missing data must not silently
    escalate risk; the policy layer decides whether missing GPS on its own
    warrants step-up via the sensor-gap path.
  * Numerically stable for the small distances we care about (< 500 km);
    Earth mean radius 6371.0088 km per IUGG.
"""

from __future__ import annotations

import math
from typing import Optional

EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Great-circle distance between two WGS-84 points in kilometres.

    Uses the standard Haversine formula. Accurate to a few metres at
    driving-relevant distances, which is well within GPS accuracy on
    modern in-vehicle receivers.
    """
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.asin(min(1.0, math.sqrt(a)))
    return EARTH_RADIUS_KM * c


def location_context(
    *,
    gps_lat: Optional[float],
    gps_lon: Optional[float],
    home_lat: Optional[float],
    home_lon: Optional[float],
    trusted_zone_radius_km: float,
) -> tuple[float, bool]:
    """
    Derive ``(dist_from_home_km, in_trusted_zone)`` for a single call.

    Returns the fail-neutral pair ``(0.0, True)`` whenever either the current
    fix or the learned home is unknown. This matches the RiskContext
    defaults so downstream feature engineering is a no-op in that case
    rather than silently spiking risk on every no-GPS transaction.

    The caller (typically :class:`DriverProfile`) is responsible for holding
    the home location; this helper stays stateless so it's cheap to test
    and reason about.
    """
    if gps_lat is None or gps_lon is None:
        return 0.0, True
    if home_lat is None or home_lon is None:
        return 0.0, True
    dist = haversine_km(gps_lat, gps_lon, home_lat, home_lon)
    in_zone = dist <= max(0.0, trusted_zone_radius_km)
    return dist, in_zone


def valid_gps_accuracy(gps_accuracy_m: Optional[float], max_m: float) -> bool:
    """
    True when we should trust an incoming fix for home-learning purposes.

    Learning a home centre from wildly inaccurate points would let a single
    tunnel-exit drift or a spoofed fix perturb the learned centre. The
    profile store uses this to gate its Welford update.
    """
    if gps_accuracy_m is None:
        return True  # unknown accuracy -> trust; caller can opt out at the policy level
    try:
        return float(gps_accuracy_m) <= float(max_m)
    except (TypeError, ValueError):
        return False
