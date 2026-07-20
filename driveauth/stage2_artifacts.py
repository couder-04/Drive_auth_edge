"""Per-driver Stage-2 bio artifact resolution.

Layout (preferred)::

    faces/{driver_id}/face_pad.onnx
    faces/{driver_id}/face_calibrator.onnx
    voices/{driver_id}/voice_calibrator.onnx

Legacy (compatibility)::

    {store}/face_pad.onnx
    {store}/face_calibrator.onnx
    {store}/voice_calibrator.onnx

Loading order for each bio head:

1. driver-specific path
2. legacy shared store-root path (logged WARNING — never silent)
3. missing (caller decides; optional heads return None)

Store-global heads (``risk_gbt.onnx``, ``trust_fusion.onnx``) stay at store root.
Encrypted templates remain ``faces/{id}.enc`` / ``voices/{id}.enc``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("driveauth.stage2_artifacts")

SourceKind = Literal["per_driver", "legacy_shared", "missing"]

FACE_PAD = "face_pad"
FACE_CALIBRATOR = "face_calibrator"
VOICE_CALIBRATOR = "voice_calibrator"

BIO_ARTIFACTS = (FACE_PAD, FACE_CALIBRATOR, VOICE_CALIBRATOR)

# Store-global Stage-2 (not per-driver)
GLOBAL_STAGE2 = ("risk_gbt.onnx", "trust_fusion.onnx")


@dataclass(frozen=True)
class ArtifactRef:
    """Resolved path for one Stage-2 bio head."""

    name: str
    driver_id: str
    path: Path | None
    json_path: Path | None
    source: SourceKind
    relpath: str | None = None

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.is_file()


def face_driver_dir(store: Path, driver_id: str) -> Path:
    return Path(store) / "faces" / driver_id


def voice_driver_dir(store: Path, driver_id: str) -> Path:
    return Path(store) / "voices" / driver_id


def per_driver_onnx_relpath(artifact: str, driver_id: str) -> str:
    if artifact in (FACE_PAD, FACE_CALIBRATOR):
        return f"faces/{driver_id}/{artifact}.onnx"
    if artifact == VOICE_CALIBRATOR:
        return f"voices/{driver_id}/{artifact}.onnx"
    raise ValueError(f"unknown bio artifact: {artifact}")


def per_driver_json_relpath(artifact: str, driver_id: str) -> str:
    return per_driver_onnx_relpath(artifact, driver_id).replace(".onnx", ".json")


def legacy_onnx_relpath(artifact: str) -> str:
    return f"{artifact}.onnx"


def resolve_bio_artifact(
    store: Path | str,
    driver_id: str,
    artifact: str,
    *,
    allow_legacy: bool = True,
) -> ArtifactRef:
    """Resolve one bio head with explicit logging on legacy fallback."""
    store_p = Path(store)
    if artifact not in BIO_ARTIFACTS:
        raise ValueError(f"unknown bio artifact: {artifact}")

    rel = per_driver_onnx_relpath(artifact, driver_id)
    per_onnx = store_p / rel
    per_json = store_p / per_driver_json_relpath(artifact, driver_id)
    if per_onnx.is_file():
        logger.info(
            "Stage-2 %s: loaded per-driver artifact for %s (%s)",
            artifact,
            driver_id,
            rel,
        )
        return ArtifactRef(
            name=artifact,
            driver_id=driver_id,
            path=per_onnx,
            json_path=per_json if per_json.is_file() else None,
            source="per_driver",
            relpath=rel,
        )

    if allow_legacy:
        leg_rel = legacy_onnx_relpath(artifact)
        leg_onnx = store_p / leg_rel
        leg_json = store_p / f"{artifact}.json"
        if leg_onnx.is_file():
            logger.warning(
                "Stage-2 %s: using LEGACY shared store-root artifact for %s (%s). "
                "Run scripts/migrate_stage2_per_driver.py — shared heads can "
                "overwrite across drivers.",
                artifact,
                driver_id,
                leg_rel,
            )
            return ArtifactRef(
                name=artifact,
                driver_id=driver_id,
                path=leg_onnx,
                json_path=leg_json if leg_json.is_file() else None,
                source="legacy_shared",
                relpath=leg_rel,
            )

    logger.info(
        "Stage-2 %s: missing for %s (checked %s%s)",
        artifact,
        driver_id,
        rel,
        f" and {legacy_onnx_relpath(artifact)}" if allow_legacy else "",
    )
    return ArtifactRef(
        name=artifact,
        driver_id=driver_id,
        path=None,
        json_path=None,
        source="missing",
        relpath=None,
    )


def resolve_all_bio(
    store: Path | str,
    driver_id: str,
    *,
    allow_legacy: bool = True,
) -> dict[str, ArtifactRef]:
    return {
        name: resolve_bio_artifact(store, driver_id, name, allow_legacy=allow_legacy)
        for name in BIO_ARTIFACTS
    }


def load_artifact_meta(ref: ArtifactRef) -> dict[str, Any]:
    if ref.json_path is None or not ref.json_path.is_file():
        return {}
    try:
        return json.loads(ref.json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_enrolled_driver_ids(store: Path | str) -> list[str]:
    """Drivers with a face and/or voice template on disk."""
    store_p = Path(store)
    ids: set[str] = set()
    faces = store_p / "faces"
    voices = store_p / "voices"
    if faces.is_dir():
        for p in faces.glob("*.enc"):
            ids.add(p.stem)
    if voices.is_dir():
        for p in voices.glob("*.enc"):
            ids.add(p.stem)
    return sorted(ids)


def trainer_output_dir(store: Path | str, driver_id: str, artifact: str) -> Path:
    """Directory where trainers MUST write (never store root for bio heads)."""
    store_p = Path(store)
    if artifact in (FACE_PAD, FACE_CALIBRATOR):
        d = face_driver_dir(store_p, driver_id)
    elif artifact == VOICE_CALIBRATOR:
        d = voice_driver_dir(store_p, driver_id)
    else:
        raise ValueError(f"unknown bio artifact: {artifact}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def trainer_onnx_path(store: Path | str, driver_id: str, artifact: str) -> Path:
    return trainer_output_dir(store, driver_id, artifact) / f"{artifact}.onnx"


def trainer_json_path(store: Path | str, driver_id: str, artifact: str) -> Path:
    return trainer_output_dir(store, driver_id, artifact) / f"{artifact}.json"


def _training_origin(meta: dict[str, Any]) -> str:
    """independent | migrated_copy | unknown — honesty for dashboard / integrity."""
    if meta.get("migrated_from"):
        return "migrated_copy"
    if meta.get("trained_at") or meta.get("driver_id"):
        # Retrain clears migrated_from; presence of trained_at implies fit for this tree
        return "independent"
    return "unknown"


def stage2_status_for_driver(
    store: Path | str,
    driver_id: str,
    *,
    allow_legacy: bool = True,
) -> dict[str, Any]:
    """Dashboard / API snapshot of Stage-2 bio heads for one driver."""
    refs = resolve_all_bio(store, driver_id, allow_legacy=allow_legacy)
    pad_meta = load_artifact_meta(refs[FACE_PAD])
    face_cal_meta = load_artifact_meta(refs[FACE_CALIBRATOR])
    voice_cal_meta = load_artifact_meta(refs[VOICE_CALIBRATOR])
    loo = pad_meta.get("loo_auc")
    try:
        loo_f = float(loo) if loo is not None else None
    except (TypeError, ValueError):
        loo_f = None
    pad_disabled_meta = bool(pad_meta.get("pad_disabled"))
    pad_enabled = (
        refs[FACE_PAD].exists
        and not pad_disabled_meta
        and (loo_f is None or loo_f > 0.55)
    )
    sources = {k: v.source for k, v in refs.items()}
    any_legacy = any(s == "legacy_shared" for s in sources.values())
    all_per = all(s == "per_driver" for s in sources.values() if s != "missing")
    origins = {
        FACE_PAD: _training_origin(pad_meta),
        FACE_CALIBRATOR: _training_origin(face_cal_meta),
        VOICE_CALIBRATOR: _training_origin(voice_cal_meta),
    }
    any_migrated = any(o == "migrated_copy" for o in origins.values())
    return {
        "driver_id": driver_id,
        "artifacts": {
            k: {
                "source": v.source,
                "path": str(v.path) if v.path else None,
                "relpath": v.relpath,
                "present": v.exists,
                "training_origin": origins[k],
            }
            for k, v in refs.items()
        },
        "pad_enabled": pad_enabled,
        "pad_loo_auc": loo_f,
        "pad_threshold": pad_meta.get("threshold"),
        "face_calibrator_loo_auc": face_cal_meta.get("loo_auc"),
        "voice_calibrator_loo_auc": voice_cal_meta.get("loo_auc"),
        "calibration_timestamps": {
            "face_pad": pad_meta.get("trained_at") or pad_meta.get("timestamp"),
            "face_calibrator": face_cal_meta.get("trained_at")
            or face_cal_meta.get("timestamp"),
            "voice_calibrator": voice_cal_meta.get("trained_at")
            or voice_cal_meta.get("timestamp"),
        },
        "needs_retrain": any_migrated,
        "mode": (
            "legacy_shared"
            if any_legacy
            else (
                "per_driver_migrated"
                if any_migrated and all_per
                else (
                    "per_driver"
                    if all_per and any(refs[a].exists for a in BIO_ARTIFACTS)
                    else "incomplete"
                )
            )
        ),
    }


def default_bio_model_relpaths(store_dir: Path, driver_ids: list[str] | None = None) -> list[str]:
    """Integrity / manifest candidates: per-driver first, then legacy if present."""
    store = Path(store_dir)
    ids = driver_ids if driver_ids is not None else list_enrolled_driver_ids(store)
    out: list[str] = []
    for did in ids:
        for art in BIO_ARTIFACTS:
            rel = per_driver_onnx_relpath(art, did)
            if (store / rel).is_file():
                out.append(rel)
    for art in BIO_ARTIFACTS:
        leg = legacy_onnx_relpath(art)
        if (store / leg).is_file():
            out.append(leg)
    return out
