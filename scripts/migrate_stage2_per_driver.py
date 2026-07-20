#!/usr/bin/env python3
"""Idempotent migration: copy legacy shared Stage-2 bio heads into per-driver dirs.

Detects store-root ``face_pad.onnx`` / ``face_calibrator.onnx`` /
``voice_calibrator.onnx`` and copies them into every enrolled driver's
``faces/{id}/`` or ``voices/{id}/`` directory.

- Preserves originals (never deletes shared artifacts)
- Skips copy when per-driver file already exists (unless ``--force``)
- Safe to run multiple times
- Writes a JSON summary

Usage:
  python scripts/migrate_stage2_per_driver.py --store driveauth_store_phase2a
  python scripts/migrate_stage2_per_driver.py --store … --drivers driver1,driver7
  python scripts/migrate_stage2_per_driver.py --store … --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.stage2_artifacts import (  # noqa: E402
    BIO_ARTIFACTS,
    FACE_CALIBRATOR,
    FACE_PAD,
    VOICE_CALIBRATOR,
    list_enrolled_driver_ids,
    per_driver_json_relpath,
    per_driver_onnx_relpath,
    trainer_output_dir,
)

LEGACY = {
    FACE_PAD: ("face_pad.onnx", "face_pad.json"),
    FACE_CALIBRATOR: ("face_calibrator.onnx", "face_calibrator.json"),
    VOICE_CALIBRATOR: ("voice_calibrator.onnx", "voice_calibrator.json"),
}


def _copy_pair(
    store: Path,
    driver_id: str,
    artifact: str,
    *,
    force: bool,
    dry_run: bool,
) -> dict:
    leg_onnx_name, leg_json_name = LEGACY[artifact]
    src_onnx = store / leg_onnx_name
    src_json = store / leg_json_name
    dest_rel = per_driver_onnx_relpath(artifact, driver_id)
    dest_onnx = store / dest_rel
    dest_json = store / per_driver_json_relpath(artifact, driver_id)

    entry: dict = {
        "driver_id": driver_id,
        "artifact": artifact,
        "src": leg_onnx_name if src_onnx.is_file() else None,
        "dest": dest_rel,
        "action": "skip",
    }

    if not src_onnx.is_file():
        entry["action"] = "no_legacy_source"
        return entry

    if dest_onnx.is_file() and not force:
        entry["action"] = "already_present"
        return entry

    trainer_output_dir(store, driver_id, artifact)
    if dry_run:
        entry["action"] = "would_copy"
        return entry

    shutil.copy2(src_onnx, dest_onnx)
    if src_json.is_file():
        shutil.copy2(src_json, dest_json)
        # Stamp migration meta without losing training fields
        try:
            meta = json.loads(dest_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        meta["driver_id"] = driver_id
        meta["migrated_from"] = leg_onnx_name
        meta["migrated_at"] = datetime.now(timezone.utc).isoformat()
        dest_json.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    entry["action"] = "copied"
    return entry


def migrate(
    store: Path,
    *,
    drivers: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    store = Path(store)
    enrolled = list_enrolled_driver_ids(store)
    target_ids = drivers if drivers else enrolled
    if not target_ids:
        # Still useful: report legacy presence even with no templates
        target_ids = []

    legacy_present = {
        art: (store / LEGACY[art][0]).is_file() for art in BIO_ARTIFACTS
    }
    actions: list[dict] = []
    for did in target_ids:
        for art in BIO_ARTIFACTS:
            actions.append(
                _copy_pair(store, did, art, force=force, dry_run=dry_run)
            )

    summary = {
        "store": str(store.resolve()),
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "force": force,
        "enrolled_drivers": enrolled,
        "target_drivers": target_ids,
        "legacy_shared_present": legacy_present,
        "legacy_preserved": True,
        "actions": actions,
        "counts": {
            "copied": sum(1 for a in actions if a["action"] == "copied"),
            "would_copy": sum(1 for a in actions if a["action"] == "would_copy"),
            "already_present": sum(1 for a in actions if a["action"] == "already_present"),
            "no_legacy_source": sum(1 for a in actions if a["action"] == "no_legacy_source"),
        },
        "note": (
            "Shared store-root Stage-2 bio heads were NOT deleted. "
            "Retrain per-driver with scripts/train_*.py to replace migrated copies."
        ),
    }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument(
        "--drivers",
        default="",
        help="Comma-separated driver ids (default: all enrolled)",
    )
    ap.add_argument("--force", action="store_true", help="Overwrite existing per-driver files")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--write-summary",
        type=Path,
        default=None,
        help="Optional JSON summary path (default: store/stage2_migration_summary.json)",
    )
    args = ap.parse_args()

    drivers = [d.strip() for d in args.drivers.split(",") if d.strip()] or None
    summary = migrate(
        args.store, drivers=drivers, force=args.force, dry_run=args.dry_run
    )
    out = args.write_summary or (args.store / "stage2_migration_summary.json")
    if not args.dry_run:
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    print(json.dumps({k: summary[k] for k in ("store", "counts", "legacy_shared_present", "target_drivers")}, indent=2))
    for a in summary["actions"]:
        if a["action"] in ("copied", "would_copy", "already_present"):
            print(f"  {a['action']:16} {a['driver_id']}/{a['artifact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
