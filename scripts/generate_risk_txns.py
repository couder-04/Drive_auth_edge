#!/usr/bin/env python3
"""
generate_risk_txns.py
Production-grade synthetic training data generator for DriveAuth Edge risk head.

Simulates >=200 synthetic drivers with individual profiles (amount baseline,
trusted-zone radius, known-beneficiary set, hour-of-day mixture), then samples
transactions conditional on those profiles across 11 realistic scenarios
(5 legit, 6 suspicious), injects border-case noise/overlap, computes the
model's engineered features, runs the QA gates from spec, and (if scikit-learn
is available) trains a quick logistic-regression sanity check to confirm the
engineered features actually separate the classes (AUC >= 0.88 gate).

Usage:
    python generate_risk_txns.py --seed 42 --n 50000 \
        --out data/driver1/transaction/txns.csv --meta meta.json

Generator version: 1.0.0
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

GENERATOR_VERSION = "1.0.0"

# ----------------------------------------------------------------------------
# Name pools
# ----------------------------------------------------------------------------

KNOWN_POOL = [
    "Mom", "Dad", "Spouse", "Sibling", "Landlord", "Electric Co",
    "Local Cafe", "Grocery Mart", "Fuel Station", "School Fees",
    "Gym Membership", "Netflix", "Amazon", "Uber", "Pharmacy",
    "Insurance Co", "Water Utility", "Mobile Recharge", "Favorite Diner",
    "Auto Mechanic", "Daycare", "Church Donation", "Barber Shop",
    "Coffee Shop", "Parking Garage", "Toll Plaza", "Dry Cleaner",
]

DRIVER_TYPES = ["worker", "night_shift", "student"]
DRIVER_TYPE_WEIGHTS = [0.55, 0.20, 0.25]


# ----------------------------------------------------------------------------
# Driver profile simulation
# ----------------------------------------------------------------------------

def make_driver_profiles(num_drivers, rng):
    drivers = []
    for i in range(num_drivers):
        dtype = rng.choice(DRIVER_TYPES, p=DRIVER_TYPE_WEIGHTS)

        amount_mean = float(np.clip(rng.lognormal(mean=np.log(550), sigma=0.65), 60, 6000))
        amount_std = float(amount_mean * rng.uniform(0.30, 0.60))

        home_x = float(rng.uniform(-60, 60))
        home_y = float(rng.uniform(-60, 60))
        zone_radius = float(rng.uniform(3, 15))

        n_known = int(rng.integers(3, 13))
        known_benefs = list(rng.choice(KNOWN_POOL, size=min(n_known, len(KNOWN_POOL)), replace=False))

        # Hour-of-day activity weights (24 buckets), by driver archetype.
        hours = np.arange(24)
        if dtype == "worker":
            w = np.exp(-0.5 * ((hours - 8) / 2.5) ** 2) + np.exp(-0.5 * ((hours - 18.5) / 2.5) ** 2)
            w += 0.05  # small night floor -> some legit night commuting
        elif dtype == "night_shift":
            # peak covers 21:00-05:00 wrap-around
            shifted = (hours - 22) % 24
            w = np.exp(-0.5 * (shifted / 3.5) ** 2)
            w += 0.05
        else:  # student
            w = np.exp(-0.5 * ((hours - 13) / 4.0) ** 2) + 0.5 * np.exp(-0.5 * ((hours - 23) / 3.0) ** 2)
            w += 0.06
        w = w / w.sum()

        drivers.append(dict(
            driver_id=f"drv_{i:04d}",
            dtype=dtype,
            amount_mean=amount_mean,
            amount_std=amount_std,
            home_x=home_x,
            home_y=home_y,
            zone_radius=zone_radius,
            known_benefs=known_benefs,
            hour_weights=w,
        ))
    return drivers


def sample_hour(driver, rng, night_bias=False):
    if night_bias:
        # force sampling from night hours (23,0-4) regardless of driver type
        night_hours = np.array([23, 0, 1, 2, 3, 4])
        return int(rng.choice(night_hours))
    return int(rng.choice(np.arange(24), p=driver["hour_weights"]))


def novel_beneficiary(rng):
    kind = rng.choice(["UnknownVendor", "NewPayee", "RemoteTransferAcct"])
    return f"{kind}_{int(rng.integers(1000, 9999))}"


def known_beneficiary(driver, rng):
    return str(rng.choice(driver["known_benefs"]))


# ----------------------------------------------------------------------------
# Scenario generators -- each returns a dict of raw row fields (label added by caller)
# ----------------------------------------------------------------------------

def scn_1_parked_known_small(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(0.05, 0.40)
    return dict(
        amount=amount, beneficiary=known_beneficiary(driver, rng), beneficiary_known=1,
        hour=sample_hour(driver, rng), speed_kmh=0.0,
        in_trusted_zone=int(rng.random() < 0.93),
        dist_from_home_km=float(rng.uniform(0, driver["zone_radius"] * 0.8)),
        ignition_on=int(rng.random() < 0.35),
        is_tunnel=int(rng.random() < 0.01),
        behavioral_score=float(np.clip(rng.normal(0.88, 0.08), 0, 1)),
    )


def scn_2_commute_known_mid(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(0.40, 1.20)
    return dict(
        amount=amount, beneficiary=known_beneficiary(driver, rng), beneficiary_known=1,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(8, 65)),
        in_trusted_zone=int(rng.random() < 0.90),
        dist_from_home_km=float(rng.uniform(0.5, driver["zone_radius"] * 1.1)),
        ignition_on=1,
        is_tunnel=int(rng.random() < 0.02),
        behavioral_score=float(np.clip(rng.normal(0.85, 0.09), 0, 1)),
    )


def scn_3_evening_known_in_zone(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(0.30, 1.00)
    return dict(
        amount=amount, beneficiary=known_beneficiary(driver, rng), beneficiary_known=1,
        hour=int(np.clip(rng.integers(17, 23), 0, 23)), speed_kmh=float(rng.uniform(0, 30)),
        in_trusted_zone=int(rng.random() < 0.92),
        dist_from_home_km=float(rng.uniform(0, driver["zone_radius"])),
        ignition_on=int(rng.random() < 0.6),
        is_tunnel=int(rng.random() < 0.015),
        behavioral_score=float(np.clip(rng.normal(0.83, 0.10), 0, 1)),
    )


def scn_4_occasional_larger_known(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(1.5, 3.0)
    return dict(
        amount=amount, beneficiary=known_beneficiary(driver, rng), beneficiary_known=1,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(0, 40)),
        in_trusted_zone=int(rng.random() < 0.85),
        dist_from_home_km=float(rng.uniform(0, driver["zone_radius"] * 1.3)),
        ignition_on=int(rng.random() < 0.55),
        is_tunnel=int(rng.random() < 0.02),
        behavioral_score=float(np.clip(rng.normal(0.75, 0.13), 0, 1)),
    )


def scn_5_out_of_zone_known_normal(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(0.4, 1.4)
    return dict(
        amount=amount, beneficiary=known_beneficiary(driver, rng), beneficiary_known=1,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(0, 90)),
        in_trusted_zone=0,
        dist_from_home_km=float(rng.uniform(driver["zone_radius"] * 1.5, driver["zone_radius"] * 5 + 20)),
        ignition_on=int(rng.random() < 0.8),
        is_tunnel=int(rng.random() < 0.03),
        behavioral_score=float(np.clip(rng.normal(0.78, 0.12), 0, 1)),
    )


def scn_6_first_time_high_amount(driver, rng):
    base = driver["amount_mean"] * rng.uniform(1.3, 3.2)
    amount = rng.uniform(15000, 90000) if rng.random() < 0.08 else base
    return dict(
        amount=amount, beneficiary=novel_beneficiary(rng), beneficiary_known=0,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(0, 70)),
        in_trusted_zone=int(rng.random() < 0.4),
        dist_from_home_km=float(rng.uniform(0, driver["zone_radius"] * 3)),
        ignition_on=int(rng.random() < 0.6),
        is_tunnel=int(rng.random() < 0.16),
        behavioral_score=float(np.clip(rng.normal(0.50, 0.18), 0, 1)),
    )


def scn_7_night_out_of_zone_novel(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(1.2, 2.8)
    return dict(
        amount=amount, beneficiary=novel_beneficiary(rng), beneficiary_known=0,
        hour=sample_hour(driver, rng, night_bias=True), speed_kmh=float(rng.uniform(0, 100)),
        in_trusted_zone=0,
        dist_from_home_km=float(rng.uniform(driver["zone_radius"] * 1.5, driver["zone_radius"] * 6 + 30)),
        ignition_on=int(rng.random() < 0.65),
        is_tunnel=int(rng.random() < 0.32),
        behavioral_score=float(np.clip(rng.normal(0.38, 0.16), 0, 1)),
    )


def scn_8_amount_baseline_zscore(driver, rng):
    z = rng.uniform(1.5, 3.0)
    amount = max(driver["amount_mean"] + z * driver["amount_std"], driver["amount_mean"] * 1.3)
    return dict(
        amount=amount, beneficiary=known_beneficiary(driver, rng), beneficiary_known=1,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(0, 50)),
        in_trusted_zone=int(rng.random() < 0.75),
        dist_from_home_km=float(rng.uniform(0, driver["zone_radius"] * 1.5)),
        ignition_on=int(rng.random() < 0.6),
        is_tunnel=int(rng.random() < 0.11),
        behavioral_score=float(np.clip(rng.normal(0.55, 0.17), 0, 1)),
    )


def scn_9_ignition_off_large_novel_far(driver, rng):
    base = driver["amount_mean"] * rng.uniform(1.3, 3.5)
    amount = rng.uniform(12000, 120000) if rng.random() < 0.08 else base
    novel = rng.random() < 0.7
    return dict(
        amount=amount,
        beneficiary=novel_beneficiary(rng) if novel else known_beneficiary(driver, rng),
        beneficiary_known=0 if novel else 1,
        hour=sample_hour(driver, rng), speed_kmh=0.0,
        in_trusted_zone=int(rng.random() < 0.25),
        dist_from_home_km=float(rng.uniform(driver["zone_radius"], driver["zone_radius"] * 7 + 25)),
        ignition_on=0,
        is_tunnel=int(rng.random() < 0.22),
        behavioral_score=float(np.clip(rng.normal(0.42, 0.16), 0, 1)),
    )


def scn_10_low_behavior_midhigh_amount(driver, rng):
    amount = driver["amount_mean"] * rng.uniform(1.2, 2.2)
    known = rng.random() < 0.5
    return dict(
        amount=amount,
        beneficiary=known_beneficiary(driver, rng) if known else novel_beneficiary(rng),
        beneficiary_known=1 if known else 0,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(0, 60)),
        in_trusted_zone=int(rng.random() < 0.6),
        dist_from_home_km=float(rng.uniform(0, driver["zone_radius"] * 2)),
        ignition_on=int(rng.random() < 0.5),
        is_tunnel=int(rng.random() < 0.17),
        behavioral_score=float(np.clip(rng.normal(0.18, 0.12), 0, 1)),
    )


def scn_11_high_speed_high_amount_out_of_zone(driver, rng):
    base = driver["amount_mean"] * rng.uniform(1.3, 3.0)
    amount = rng.uniform(10000, 60000) if rng.random() < 0.08 else base
    return dict(
        amount=amount, beneficiary=novel_beneficiary(rng), beneficiary_known=0,
        hour=sample_hour(driver, rng), speed_kmh=float(rng.uniform(85, 165)),
        in_trusted_zone=0,
        dist_from_home_km=float(rng.uniform(driver["zone_radius"] * 2, driver["zone_radius"] * 8 + 40)),
        ignition_on=1,
        is_tunnel=int(rng.random() < 0.28),
        behavioral_score=float(np.clip(rng.normal(0.45, 0.17), 0, 1)),
    )


SCENARIOS = [
    ("parked_known_small", 22.0, "legit", scn_1_parked_known_small),
    ("commute_known_mid", 20.0, "legit", scn_2_commute_known_mid),
    ("evening_known_in_zone", 12.0, "legit", scn_3_evening_known_in_zone),
    ("occasional_larger_known", 10.0, "legit", scn_4_occasional_larger_known),
    ("out_of_zone_known_normal", 8.0, "legit", scn_5_out_of_zone_known_normal),
    ("first_time_high_amount", 8.0, "suspicious", scn_6_first_time_high_amount),
    ("night_out_of_zone_novel", 6.0, "suspicious", scn_7_night_out_of_zone_novel),
    ("amount_baseline_zscore", 5.0, "suspicious", scn_8_amount_baseline_zscore),
    ("ignition_off_large_novel_far", 4.0, "suspicious", scn_9_ignition_off_large_novel_far),
    ("low_behavior_midhigh_amount", 3.0, "suspicious", scn_10_low_behavior_midhigh_amount),
    ("high_speed_high_amount_ooz", 2.0, "suspicious", scn_11_high_speed_high_amount_out_of_zone),
]


def allocate_counts(n, scenarios):
    """Exact integer row counts per scenario summing to n, per target pct."""
    raw = [n * pct / 100.0 for _, pct, _, _ in scenarios]
    counts = [int(np.floor(r)) for r in raw]
    remainder = n - sum(counts)
    # give remainder to scenarios with largest fractional part
    fracs = sorted(range(len(scenarios)), key=lambda i: (raw[i] - counts[i]), reverse=True)
    for i in fracs[:remainder]:
        counts[i] += 1
    return counts


# ----------------------------------------------------------------------------
# Border-case noise injection
# ----------------------------------------------------------------------------

def inject_noise(row, label, rng, noise_rate=0.12):
    """With probability noise_rate, nudge 1-2 features toward the opposite
    class's typical range to create ambiguous, non-linearly-separable rows.
    Label is left untouched (ground truth intent doesn't change)."""
    if rng.random() >= noise_rate:
        return row
    n_flip = 1 if rng.random() < 0.7 else 2
    flip_pool = ["in_trusted_zone", "ignition_on", "is_tunnel", "behavioral_score", "hour", "speed_kmh"]
    chosen = rng.choice(flip_pool, size=min(n_flip, len(flip_pool)), replace=False)
    for feat in chosen:
        if feat == "in_trusted_zone":
            row["in_trusted_zone"] = 1 - row["in_trusted_zone"]
        elif feat == "ignition_on":
            row["ignition_on"] = 1 - row["ignition_on"]
        elif feat == "is_tunnel":
            row["is_tunnel"] = 1 - row["is_tunnel"]
        elif feat == "behavioral_score":
            if label == "legit":
                row["behavioral_score"] = float(np.clip(row["behavioral_score"] - rng.uniform(0.25, 0.5), 0, 1))
            else:
                row["behavioral_score"] = float(np.clip(row["behavioral_score"] + rng.uniform(0.25, 0.5), 0, 1))
        elif feat == "hour":
            row["hour"] = int(rng.integers(0, 24))
        elif feat == "speed_kmh":
            row["speed_kmh"] = float(np.clip(row["speed_kmh"] + rng.normal(0, 25), 0, 180))
    return row


# ----------------------------------------------------------------------------
# Main generation
# ----------------------------------------------------------------------------

def generate(n, seed, num_drivers=250):
    rng = np.random.default_rng(seed)
    drivers = make_driver_profiles(num_drivers, rng)
    counts = allocate_counts(n, SCENARIOS)

    rows = []
    for (name, pct, label, fn), cnt in zip(SCENARIOS, counts):
        for _ in range(cnt):
            driver = drivers[int(rng.integers(0, len(drivers)))]
            row = fn(driver, rng)
            row = inject_noise(row, label, rng)
            row["label"] = label
            row["driver_id"] = driver["driver_id"]
            row["scenario"] = name
            rows.append(row)

    rng.shuffle(rows)  # in-place shuffle of the python list order isn't numpy-native; do manually
    idx = rng.permutation(len(rows))
    rows = [rows[i] for i in idx]

    df = pd.DataFrame(rows)

    # physical plausibility clamps
    df["amount"] = df["amount"].clip(lower=10, upper=250000).round(2)
    df["hour"] = df["hour"].clip(lower=0, upper=23).astype(int)
    df["speed_kmh"] = df["speed_kmh"].clip(lower=0, upper=180).round(1)
    df["dist_from_home_km"] = df["dist_from_home_km"].clip(lower=0, upper=500).round(2)
    df["behavioral_score"] = df["behavioral_score"].clip(lower=0.0, upper=1.0).round(3)
    for b in ["beneficiary_known", "in_trusted_zone", "ignition_on", "is_tunnel"]:
        df[b] = df[b].astype(int)

    # de-dup guard: if too many exact duplicate feature vectors, jitter amount slightly
    feat_cols = ["amount", "beneficiary_known", "hour", "speed_kmh", "in_trusted_zone",
                 "dist_from_home_km", "ignition_on", "is_tunnel", "behavioral_score", "label"]
    dup_mask = df.duplicated(subset=feat_cols, keep="first")
    if dup_mask.sum() > 0:
        jitter = rng.normal(0, 1.0, size=dup_mask.sum())
        df.loc[dup_mask, "amount"] = (df.loc[dup_mask, "amount"] + jitter).clip(lower=10).round(2)

    return df, drivers


# ----------------------------------------------------------------------------
# Feature engineering (mirrors trainer / inference)
# ----------------------------------------------------------------------------

def engineer_features(df):
    legit_amounts = df.loc[df["label"] == "legit", "amount"]
    amount_mean = float(legit_amounts.mean())
    amount_std = float(legit_amounts.std())

    out = pd.DataFrame(index=df.index)
    out["amount_z"] = ((df["amount"] - amount_mean) / amount_std).clip(-3, 6)
    out["amount_norm"] = (df["amount"] / 100000.0).clip(upper=1.0)
    out["beneficiary_novel"] = 1 - df["beneficiary_known"]
    out["dist_from_home"] = (df["dist_from_home_km"] / 50.0).clip(upper=1.0)
    out["out_of_zone"] = 1 - df["in_trusted_zone"]
    out["night"] = ((df["hour"] < 5) | (df["hour"] >= 23)).astype(int)
    out["moving_fast"] = ((df["speed_kmh"] - 20) / 80.0).clip(lower=0, upper=1.0)
    out["ignition_off_anomaly"] = 1 - df["ignition_on"]
    out["tunnel"] = df["is_tunnel"]
    out["behavior_anomaly"] = 1 - df["behavioral_score"]
    return out, amount_mean, amount_std


# ----------------------------------------------------------------------------
# QA gates
# ----------------------------------------------------------------------------

def run_qa_gates(df):
    results = {}
    failures = []

    n = len(df)
    susp_rate = float((df["label"] == "suspicious").mean())
    results["suspicious_rate"] = susp_rate
    if not (0.20 <= susp_rate <= 0.35):
        failures.append(f"suspicious_rate {susp_rate:.4f} not in [0.20,0.35]")

    night = ((df["hour"] < 5) | (df["hour"] >= 23)).astype(int)
    df2 = df.copy()
    df2["night"] = night
    binary_feats = ["beneficiary_known", "in_trusted_zone", "ignition_on", "is_tunnel", "night"]
    rate_diffs = {}
    for feat in binary_feats:
        r_legit = float(df2.loc[df2["label"] == "legit", feat].mean())
        r_susp = float(df2.loc[df2["label"] == "suspicious", feat].mean())
        diff = abs(r_legit - r_susp)
        rate_diffs[feat] = {"legit_rate": r_legit, "suspicious_rate": r_susp, "abs_diff": diff}
        if diff < 0.08:
            failures.append(f"{feat} class-conditional rate diff {diff:.4f} < 0.08")
    results["binary_feature_rate_diffs"] = rate_diffs

    med_legit = float(df.loc[df["label"] == "legit", "amount"].median())
    med_susp = float(df.loc[df["label"] == "suspicious", "amount"].median())
    ratio = med_susp / med_legit if med_legit > 0 else float("nan")
    results["amount_median_ratio_susp_over_legit"] = ratio
    if not (1.3 <= ratio <= 4.0):
        failures.append(f"amount median ratio {ratio:.3f} not in [1.3,4.0]")

    p90_legit = float(df.loc[df["label"] == "legit", "dist_from_home_km"].quantile(0.90))
    p90_susp = float(df.loc[df["label"] == "suspicious", "dist_from_home_km"].quantile(0.90))
    results["dist_from_home_p90"] = {"legit": p90_legit, "suspicious": p90_susp}
    if not (p90_susp > p90_legit):
        failures.append("dist_from_home_km P90(suspicious) not > P90(legit)")

    beh_legit = float(df.loc[df["label"] == "legit", "behavioral_score"].mean())
    beh_susp = float(df.loc[df["label"] == "suspicious", "behavioral_score"].mean())
    beh_diff = beh_legit - beh_susp
    results["behavioral_score_mean_diff"] = beh_diff
    if beh_diff < 0.15:
        failures.append(f"behavioral_score mean diff {beh_diff:.4f} < 0.15")

    night_rate_all = float(night.mean())
    night_rate_legit = float(night[df["label"] == "legit"].mean())
    results["night_rate_overall"] = night_rate_all
    results["night_rate_legit"] = night_rate_legit
    if night_rate_all < 0.08:
        failures.append(f"overall night rate {night_rate_all:.4f} < 0.08")
    if night_rate_legit < 0.05:
        failures.append(f"legit night rate {night_rate_legit:.4f} < 0.05")

    feat_cols = ["amount", "beneficiary_known", "hour", "speed_kmh", "in_trusted_zone",
                 "dist_from_home_km", "ignition_on", "is_tunnel", "behavioral_score", "label"]
    dup_rate = float(df.duplicated(subset=feat_cols, keep="first").mean())
    results["duplicate_rate"] = dup_rate
    if dup_rate > 0.005:
        failures.append(f"duplicate rate {dup_rate:.4f} > 0.005")

    nan_count = int(df.isna().sum().sum())
    results["nan_count"] = nan_count
    if nan_count > 0:
        failures.append(f"{nan_count} NaNs present")

    bad_binaries = 0
    for b in ["beneficiary_known", "in_trusted_zone", "ignition_on", "is_tunnel"]:
        bad_binaries += int((~df[b].isin([0, 1])).sum())
    results["bad_binary_values"] = bad_binaries
    if bad_binaries > 0:
        failures.append(f"{bad_binaries} non-binary values in binary columns")

    bad_labels = int((~df["label"].isin(["legit", "suspicious"])).sum())
    results["bad_labels"] = bad_labels
    if bad_labels > 0:
        failures.append(f"{bad_labels} invalid label values")

    # QA gate 9: quick classifier sanity check
    auc = None
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import roc_auc_score

        feats, _, _ = engineer_features(df)
        y = (df["label"] == "suspicious").astype(int).values
        X_train, X_val, y_train, y_val = train_test_split(
            feats.values, y, test_size=0.2, random_state=0, stratify=y
        )
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(X_train, y_train)
        val_proba = clf.predict_proba(X_val)[:, 1]
        auc = float(roc_auc_score(y_val, val_proba))
        results["quick_logreg_val_auc"] = auc
        if auc < 0.88:
            failures.append(f"quick logreg val AUC {auc:.4f} < 0.88")
    except ImportError:
        results["quick_logreg_val_auc"] = None
        failures.append("scikit-learn not available; could not run AUC sanity check")

    results["passed"] = len(failures) == 0
    results["failures"] = failures
    return results


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate DriveAuth risk training dataset")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=50000)
    ap.add_argument("--num-drivers", type=int, default=250)
    ap.add_argument("--out", type=str, default="data/driver1/transaction/txns.csv")
    ap.add_argument("--meta", type=str, default="meta.json")
    args = ap.parse_args()

    df, drivers = generate(args.n, args.seed, args.num_drivers)

    export_cols = ["amount", "beneficiary", "beneficiary_known", "hour", "speed_kmh",
                   "in_trusted_zone", "dist_from_home_km", "ignition_on", "is_tunnel",
                   "behavioral_score", "label", "driver_id"]
    df_export = df[export_cols]

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df_export.to_csv(args.out, index=False)

    qa = run_qa_gates(df)
    _, amount_mean_legit, amount_std_legit = engineer_features(df)

    scenario_counts = df["scenario"].value_counts().to_dict()
    class_counts = df["label"].value_counts().to_dict()

    meta = {
        "generator_version": GENERATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "n_rows": int(len(df)),
        "num_drivers": args.num_drivers,
        "class_counts": {k: int(v) for k, v in class_counts.items()},
        "scenario_mix_target_pct": {name: pct for name, pct, _, _ in SCENARIOS},
        "scenario_row_counts": {k: int(v) for k, v in scenario_counts.items()},
        "amount_mean_legit_only": amount_mean_legit,
        "amount_std_legit_only": amount_std_legit,
        "qa_gates": qa,
    }

    with open(args.meta, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Wrote {len(df_export)} rows to {args.out}")
    print(f"Wrote QA/meta report to {args.meta}")
    print(f"QA gates passed: {qa['passed']}")
    if not qa["passed"]:
        print("Failures:")
        for fail in qa["failures"]:
            print(f"  - {fail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
