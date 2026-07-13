"""
Overfit audit for the risk_gbt model.

We already know train/val on a stratified random split are ~identical
(train_auc=0.9957, val_auc=0.9955 → gap 0.0002). That's necessary but not
sufficient: a random split from the same distribution can still hide two
failure modes:

  * The model memorises per-driver quirks and doesn't generalise to
    unseen drivers -- important because deployments are per-driver.
  * The model is fit to a specific generator seed and would collapse on
    a fresh draw.

Six checks, each answers a specific concern:

  1. Train/val gap                -- basic (early-stopping check).
  2. 5-fold stratified CV         -- is that single-split number reliable?
  3. LEAVE-DRIVERS-OUT holdout    -- does it generalise to unseen drivers?
  4. Cross-seed generalisation    -- does it generalise to a fresh draw?
  5. Shuffled-label baseline      -- sanity check (should collapse to ~0.5).
  6. Feature-ablation stability   -- broad signal use, not one silver bullet.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/home/claude/Drive_auth_edge_fixed")
sys.path.insert(0, str(ROOT))

from scripts.train_risk_gbt import (  # noqa: E402
    FEATURE_ORDER,
    _row_to_features,
    _driver_amount_stats,
)


# ── load helpers ────────────────────────────────────────────────────────────

def load_csv(csv_path: Path):
    with csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    global_mean, global_std, per_driver = _driver_amount_stats(rows, min_legit=5)
    X, y, dids = [], [], []
    for r in rows:
        did = r.get("driver_id", "_")
        drv_mean, drv_std = per_driver.get(did, (global_mean, global_std))
        feats = _row_to_features(r, drv_mean, drv_std)
        X.append([feats[k] for k in FEATURE_ORDER])
        y.append(1 if r["label"].strip().lower() == "suspicious" else 0)
        dids.append(did)
    return np.asarray(X, np.float32), np.asarray(y, np.int32), np.array(dids)


def train_one(X_tr, y_tr, X_va, y_va, seed=0):
    """Same hyperparams the shipped trainer uses. Monotone list sized to
    actual feature count so this helper also serves the ablation check."""
    import lightgbm as lgb
    n_feat = X_tr.shape[1]
    m = lgb.LGBMClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05, num_leaves=15,
        min_child_samples=20, subsample=0.9, colsample_bytree=0.9,
        class_weight="balanced", random_state=seed, verbosity=-1,
        monotone_constraints=[1] * n_feat,
    )
    m.fit(
        X_tr, y_tr,
        eval_set=[(X_va, y_va)],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    return m


# ── checks ──────────────────────────────────────────────────────────────────

def check_1_train_val_gap(X, y):
    """Basic overfit signal: how big is train − val?"""
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    print("\n── Check 1: single 80/20 split (baseline) ──")
    Xt, Xv, yt, yv = train_test_split(X, y, test_size=0.2, random_state=0, stratify=y)
    m = train_one(Xt, yt, Xv, yv)
    tr = roc_auc_score(yt, m.predict_proba(Xt)[:, 1])
    va = roc_auc_score(yv, m.predict_proba(Xv)[:, 1])
    gap = tr - va
    print(f"  train_auc={tr:.4f}  val_auc={va:.4f}  gap={gap:+.4f}")
    verdict = "OK" if abs(gap) < 0.02 else "SUSPECT"
    print(f"  gap < 0.02 threshold → {verdict}")
    return va, gap


def check_2_kfold(X, y, n_splits=5):
    """K-fold CV: is that single-split AUC reliable, or a lucky draw?"""
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score
    print(f"\n── Check 2: {n_splits}-fold stratified CV ──")
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
    aucs = []
    for i, (tr_idx, va_idx) in enumerate(skf.split(X, y)):
        m = train_one(X[tr_idx], y[tr_idx], X[va_idx], y[va_idx])
        auc = roc_auc_score(y[va_idx], m.predict_proba(X[va_idx])[:, 1])
        aucs.append(auc)
        print(f"  fold {i}: val_auc={auc:.4f}")
    mean_auc = float(np.mean(aucs))
    std_auc = float(np.std(aucs))
    print(f"  mean={mean_auc:.4f}  std={std_auc:.4f}")
    verdict = "OK" if std_auc < 0.01 else "SUSPECT"
    print(f"  std < 0.01 threshold → {verdict}")
    return mean_auc, std_auc


def check_3_leave_drivers_out(X, y, dids, holdout_frac=0.2):
    """
    Train on a subset of drivers, evaluate on drivers the model has NEVER
    seen. This is the strongest generalisation test for a per-driver
    deployment: it says "if a new driver enrols tomorrow, will the risk
    head still be calibrated?"
    """
    from sklearn.metrics import roc_auc_score
    print(f"\n── Check 3: leave-drivers-out ({int(holdout_frac*100)}% of drivers unseen) ──")
    rng = np.random.default_rng(0)
    unique_drivers = np.unique(dids)
    rng.shuffle(unique_drivers)
    n_holdout = int(len(unique_drivers) * holdout_frac)
    holdout_drv = set(unique_drivers[:n_holdout].tolist())
    is_holdout = np.array([d in holdout_drv for d in dids])
    Xt, Xv = X[~is_holdout], X[is_holdout]
    yt, yv = y[~is_holdout], y[is_holdout]
    print(f"  train: {len(unique_drivers) - n_holdout} drivers, {len(Xt)} rows")
    print(f"  val:   {n_holdout} drivers ({n_holdout}/{len(unique_drivers)}), {len(Xv)} rows")
    m = train_one(Xt, yt, Xv, yv)
    tr = roc_auc_score(yt, m.predict_proba(Xt)[:, 1])
    va = roc_auc_score(yv, m.predict_proba(Xv)[:, 1])
    gap = tr - va
    print(f"  train_auc={tr:.4f}  val_auc={va:.4f}  gap={gap:+.4f}")
    verdict = "OK" if va >= 0.95 and gap < 0.03 else "SUSPECT"
    print(f"  val ≥ 0.95 AND gap < 0.03 → {verdict}")
    return va, gap


def check_4_cross_seed(model, csv_path_new: Path):
    """Take the shipped model trained on seed=42 data, evaluate on data
    generated with a different seed. If val AUC holds, the model is
    generalising to the underlying scenario distribution, not just
    memorising the specific 50k rows it trained on."""
    from sklearn.metrics import roc_auc_score
    from sklearn.metrics import accuracy_score
    print(f"\n── Check 4: cross-seed generalisation ({csv_path_new.name}) ──")
    X_new, y_new, _ = load_csv(csv_path_new)
    proba = model.predict_proba(X_new)[:, 1]
    va = roc_auc_score(y_new, proba)
    acc = accuracy_score(y_new, proba >= 0.5)
    ml = proba[y_new == 0].mean()
    ms = proba[y_new == 1].mean()
    print(f"  {csv_path_new.name}: val_auc={va:.4f}  acc@0.5={acc:.4f}  "
          f"mean_risk_legit={ml:.3f}  mean_risk_suspicious={ms:.3f}")
    verdict = "OK" if va >= 0.95 else "SUSPECT"
    print(f"  val ≥ 0.95 → {verdict}")
    return va


def check_5_shuffled_labels(X, y):
    """Sanity check: shuffled-label training should collapse to ~0.5 AUC.
    If it doesn't, we've got a data-leak somewhere (e.g. a feature that's
    a deterministic function of the label)."""
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    print("\n── Check 5: shuffled-label baseline (should be ~0.5) ──")
    rng = np.random.default_rng(0)
    y_shuf = y.copy()
    rng.shuffle(y_shuf)
    Xt, Xv, yt, yv = train_test_split(X, y_shuf, test_size=0.2, random_state=0, stratify=y_shuf)
    m = train_one(Xt, yt, Xv, yv)
    va = roc_auc_score(yv, m.predict_proba(Xv)[:, 1])
    print(f"  val_auc on shuffled labels: {va:.4f}")
    verdict = "OK" if 0.45 <= va <= 0.55 else "SUSPECT (possible data leak)"
    print(f"  0.45 ≤ AUC ≤ 0.55 → {verdict}")
    return va


def check_6_feature_ablation(X, y):
    """
    Drop one feature at a time and retrain. An overfit / silver-bullet model
    collapses when its single dominant feature is removed. A well-behaved
    ensemble degrades gracefully because it has learned to distribute
    signal across multiple features.
    """
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    print("\n── Check 6: feature-ablation stability (drop one, retrain) ──")
    Xt, Xv, yt, yv = train_test_split(X, y, test_size=0.2, random_state=0, stratify=y)
    base = train_one(Xt, yt, Xv, yv)
    base_auc = roc_auc_score(yv, base.predict_proba(Xv)[:, 1])
    print(f"  baseline (all features): val_auc={base_auc:.4f}")
    drops = []
    for j, name in enumerate(FEATURE_ORDER):
        mask = np.ones(len(FEATURE_ORDER), bool); mask[j] = False
        m = train_one(Xt[:, mask], yt, Xv[:, mask], yv)
        auc = roc_auc_score(yv, m.predict_proba(Xv[:, mask])[:, 1])
        delta = base_auc - auc
        drops.append((name, auc, delta))
        print(f"  drop {name:<22s} val_auc={auc:.4f}  Δ={delta:+.4f}")
    max_drop = max(d for _, _, d in drops)
    print(f"  worst single-feature drop: {max_drop:+.4f}")
    verdict = "OK" if max_drop < 0.10 else "SUSPECT (silver-bullet feature)"
    print(f"  max drop < 0.10 → {verdict}")
    return max_drop


# ── main ────────────────────────────────────────────────────────────────────

def main():
    csv_a = ROOT / "data" / "driver1" / "transaction" / "txns.csv"
    print(f"Primary dataset: {csv_a}")
    X, y, dids = load_csv(csv_a)
    print(f"  n={len(X)}  n_features={X.shape[1]}  n_drivers={len(set(dids))}  "
          f"suspicious_rate={y.mean():.3f}")

    va, gap = check_1_train_val_gap(X, y)
    mean_auc, std_auc = check_2_kfold(X, y)
    va_ldo, gap_ldo = check_3_leave_drivers_out(X, y, dids)

    # For check 4 we need a NEW dataset from a different seed.
    print("\nGenerating fresh dataset with seed=7 for cross-seed test ...")
    fresh_csv = Path("/tmp/txns_seed7.csv")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_risk_txns.py"),
         "--seed", "7", "--n", "20000",
         "--out", str(fresh_csv),
         "--meta", "/tmp/txns_seed7_meta.json"],
        check=True, cwd=ROOT, stdout=subprocess.DEVNULL,
    )
    # Load the shipped model to check cross-dataset generalisation.
    from sklearn.model_selection import train_test_split
    Xt, Xv, yt, yv = train_test_split(X, y, test_size=0.2, random_state=0, stratify=y)
    shipped = train_one(Xt, yt, Xv, yv)
    va_cross = check_4_cross_seed(shipped, fresh_csv)

    va_shuf = check_5_shuffled_labels(X, y)
    max_drop = check_6_feature_ablation(X, y)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  1. train/val gap (random split):    {gap:+.4f}    "
          f"{'OK' if abs(gap) < 0.02 else 'SUSPECT'}")
    print(f"  2. 5-fold CV mean±std:              {mean_auc:.4f} ± {std_auc:.4f}    "
          f"{'OK' if std_auc < 0.01 else 'SUSPECT'}")
    print(f"  3. leave-drivers-out val_auc:       {va_ldo:.4f}  gap {gap_ldo:+.4f}    "
          f"{'OK' if va_ldo >= 0.95 and gap_ldo < 0.03 else 'SUSPECT'}")
    print(f"  4. cross-seed val_auc:              {va_cross:.4f}    "
          f"{'OK' if va_cross >= 0.95 else 'SUSPECT'}")
    print(f"  5. shuffled-label baseline AUC:     {va_shuf:.4f}    "
          f"{'OK' if 0.45 <= va_shuf <= 0.55 else 'SUSPECT'}")
    print(f"  6. worst feature-ablation drop:     {max_drop:+.4f}    "
          f"{'OK' if max_drop < 0.10 else 'SUSPECT'}")


if __name__ == "__main__":
    main()
