#!/usr/bin/env python3
"""Sign an integrity manifest for policy + model files (Phase D).

Example:
  python scripts/sign_manifest.py \\
    --store ./driveauth_store_phase2a \\
    --policy driveauth/policy.yaml \\
    --out-dir ./driveauth_store_phase2a \\
    --write-pubkey
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.integrity import (  # noqa: E402
    MANIFEST_NAME,
    SIG_NAME,
    build_manifest,
    default_model_relpaths,
    dump_private_key,
    dump_public_key,
    generate_keypair,
    load_private_key,
    sha256_file,
    sign_manifest,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, required=True, help="Model store directory")
    ap.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "driveauth" / "policy.yaml",
        help="policy.yaml path (hashed as policy.yaml in manifest)",
    )
    ap.add_argument("--out-dir", type=Path, default=None, help="Where to write manifest+sig")
    ap.add_argument("--privkey", type=Path, default=None, help="Raw Ed25519 private key file")
    ap.add_argument("--write-pubkey", action="store_true", help="Also write integrity_ed25519.pub")
    ap.add_argument("--extra", action="append", default=[], help="Extra relative paths under store")
    args = ap.parse_args()

    store = args.store.resolve()
    out_dir = (args.out_dir or store).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rels = default_model_relpaths(store)
    for extra in args.extra:
        rels.append(extra)

    # Build file map: models relative to store + policy under stable key.
    files: dict[str, str] = {}
    for rel in rels:
        path = store / rel
        if path.is_file():
            files[rel.replace("\\", "/")] = sha256_file(path)
    policy = args.policy.resolve()
    if not policy.is_file():
        raise SystemExit(f"policy not found: {policy}")
    files["policy.yaml"] = sha256_file(policy)

    manifest = {
        "version": 1,
        "files": files,
        "meta": {"store": str(store), "policy": str(policy)},
    }

    if args.privkey and args.privkey.is_file():
        priv = load_private_key(args.privkey.read_bytes())
        pub = priv.public_key()
    else:
        priv, pub = generate_keypair()
        key_path = out_dir / "integrity_ed25519.key"
        key_path.write_bytes(dump_private_key(priv))
        print(f"wrote private key {key_path} (keep offline — never ship on vehicle)")

    sig = sign_manifest(manifest, priv)
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / SIG_NAME).write_bytes(sig)
    if args.write_pubkey:
        pub_path = out_dir / "integrity_ed25519.pub"
        pub_path.write_bytes(dump_public_key(pub))
        print(f"wrote public key {pub_path}")
    else:
        # Always emit pubkey next to the signature so vehicles can verify.
        pub_path = out_dir / "integrity_ed25519.pub"
        if not pub_path.is_file():
            pub_path.write_bytes(dump_public_key(pub))
            print(f"wrote public key {pub_path}")

    print(f"wrote {out_dir / MANIFEST_NAME}")
    print(f"wrote {out_dir / SIG_NAME}")
    print(f"files hashed: {len(files)}")


if __name__ == "__main__":
    main()
