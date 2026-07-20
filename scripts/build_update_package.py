#!/usr/bin/env python3
"""Build a signed OTA update package (Phase F).

Bundles payload files + Ed25519-signed manifest for ``hardware.ota_client.OTAClient``.

Example:
  python scripts/build_update_package.py \\
    --payload-dir ./ota_payload \\
    --out ./dist/update_v2 \\
    --version-id v2 \\
    --privkey ./signing/ota_ed25519.key
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.integrity import (  # noqa: E402
    dump_private_key,
    dump_public_key,
    generate_keypair,
    load_private_key,
    sign_manifest,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--payload-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--version-id", required=True)
    ap.add_argument("--privkey", type=Path, default=None)
    ap.add_argument("--write-pubkey", type=Path, default=None)
    args = ap.parse_args()

    payload_src = args.payload_dir.resolve()
    if not payload_src.is_dir():
        raise SystemExit(f"payload-dir not found: {payload_src}")

    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    payload_dst = out / "payload"
    shutil.copytree(payload_src, payload_dst)

    files: dict[str, str] = {}
    for path in sorted(payload_dst.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(payload_dst)).replace("\\", "/")
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "version": 1,
        "version_id": args.version_id,
        "files": files,
        "meta": {"version": args.version_id},
    }

    if args.privkey and args.privkey.is_file():
        priv = load_private_key(args.privkey.read_bytes())
    else:
        priv, pub = generate_keypair()
        key_out = out / "ota_ed25519.key"
        key_out.write_bytes(dump_private_key(priv))
        print(f"generated signing key {key_out} (keep offline)")
        if args.write_pubkey:
            args.write_pubkey.parent.mkdir(parents=True, exist_ok=True)
            args.write_pubkey.write_bytes(dump_public_key(pub))

    sig = sign_manifest(manifest, priv)
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "manifest.sig").write_bytes(sig)
    if args.write_pubkey and args.privkey:
        pub = priv.public_key()
        args.write_pubkey.parent.mkdir(parents=True, exist_ok=True)
        args.write_pubkey.write_bytes(dump_public_key(pub))

    print(f"package ready: {out}")
    print(f"  version_id={args.version_id} files={len(files)}")


if __name__ == "__main__":
    main()
