# Contributing to DriveAuth Edge

Thanks for helping improve in-vehicle biometric authorization.

## Quick start

```bash
git clone <repo-url>
cd staged_driveauth-edge
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp secrets.env.example secrets.env
# Set DRIVEAUTH_DASHBOARD_API_KEY (or DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1 for localhost)
make bootstrap   # downloads Stage-1 models; reports Stage-2 status
make test
make demo        # http://127.0.0.1:8765
```

## Development norms

- Prefer the **smallest correct change**. Do not redesign architecture.
- Preserve public APIs (`DriveAuth.load`, authenticate contract) unless the PR explicitly versions a break.
- Prefer dependency injection / `app.state` over module-level mutable singletons.
- If you change code, update or add tests. Do not reduce coverage.
- If docs become wrong, fix them in the same PR.
- Run before opening a PR:

```bash
make lint
make test
make coverage
```

## Dashboard admin auth

Mutating dashboard routes require `DRIVEAUTH_DASHBOARD_API_KEY` via
`Authorization: Bearer <key>` or `X-API-Key: <key>`.
Local demos may set `DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1` (never on a public bind).

## Models

- **Mock path (explicit):** `DRIVEAUTH_USE_MOCK=1`
- **Real matchers:** run `python scripts/bootstrap.py` then enroll drivers
- **No silent mock fallback.** Optional hybrid only with `DRIVEAUTH_ALLOW_MOCK_FALLBACK=1`

## Pull requests

Use the PR template. Keep descriptions focused on *why*. Link issues when applicable.

## Code of conduct

Be respectful. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
