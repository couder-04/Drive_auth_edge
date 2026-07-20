#!/usr/bin/env python3
"""Export versioned OpenAPI schema for the dashboard FastAPI app."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Avoid requiring a real admin key while importing the app for schema dump.
os.environ.setdefault("DRIVEAUTH_ALLOW_INSECURE_DASHBOARD", "1")
os.environ.setdefault("DRIVEAUTH_USE_MOCK", "1")


def main() -> int:
    from dashboard.app import app

    schema = app.openapi()
    schema["info"]["version"] = app.version
    out_dir = ROOT / "docs" / "openapi"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = str(schema["info"].get("version", "0.0.0"))
    versioned = out_dir / f"openapi-v{version}.json"
    latest = out_dir / "openapi.json"
    payload = json.dumps(schema, indent=2) + "\n"
    versioned.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print("wrote", versioned.relative_to(ROOT))
    print("wrote", latest.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
